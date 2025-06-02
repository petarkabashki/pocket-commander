#%%
import asyncio
import logging
import uuid # Added
from typing import Callable, Awaitable, Any, Optional, List

logger = logging.getLogger(__name__)
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter, Completer, Completion
from prompt_toolkit.document import Document
from rich.console import Console
from rich.text import Text

from pocket_commander.commands.io import AbstractCommandInput
from pocket_commander.commands.terminal_io import TerminalCommandInput, TerminalOutputHandler
from pocket_commander.types import AppServices
from pocket_commander.event_bus import AsyncEventBus # Added
from pocket_commander.events import RequestPromptEvent, PromptResponseEvent # Added

class AppStateAwareCompleter(Completer):
    """
    A prompt-toolkit completer that is aware of the application's state
    to provide dynamic command completions.
    """
    def __init__(self, app_services_provider: Callable[[], AppServices]):
        self.app_services_provider = app_services_provider

    def get_completions(self, document: Document, complete_event) -> List[Completion]:
        # This completer needs significant rework if commands are no longer centrally managed
        # by app_core in 'active_agent_commands'.
        # For now, it will primarily offer global commands and agent names.
        # Agent-specific input suggestions would need a different mechanism,
        # perhaps the agent itself publishing suggestion events.
        completions: List[str] = []
        app_services = self.app_services_provider()
        
        raw_config = app_services.raw_app_config if app_services.raw_app_config else {}
        
        # Global commands (conventionally prefixed with /)
        # Ideally, get these from app_services.global_commands if populated by app_core
        # For now, hardcoding common global command prefixes
        completions.extend(["/exit", "/quit", "/q", "/help", "/agents", "/agent"]) # Removed /tools, /tool as they are agent specific

        # Agent names for /agent command
        # 'resolved_agents' will be the new key for AgentConfig objects
        resolved_agents = raw_config.get('resolved_agents', {}) 
        completions.extend(list(resolved_agents.keys()))

        word_before_cursor = document.get_word_before_cursor(WORD=True)
        for cmd_name in completions:
            if cmd_name.startswith(word_before_cursor):
                yield Completion(cmd_name, start_position=-len(word_before_cursor))


class TerminalInteractionFlow:
    """
    Manages terminal-specific user interaction using prompt-toolkit and Rich.
    Captures input and passes it to the provided input processing callback (which now publishes AppInputEvent).
    Provides concrete I/O handlers (output via event subscription, prompt via event cycle).
    """

    def __init__(
        self, 
        app_services: AppServices,
        # process_input_callback is the top_level_app_input_handler from app_core
        process_input_callback: Callable[[str, AbstractCommandInput], Awaitable[Any]]
    ):
        self.app_services = app_services
        self.event_bus = app_services.event_bus # Get event bus from AppServices
        self.process_input_callback = process_input_callback # This will publish AppInputEvent
        self.console = Console()
        self.session = PromptSession(history=FileHistory('.terminal_history'))
        
        self.command_completer = AppStateAwareCompleter(lambda: self.app_services)
        self._running = False
        
        # TerminalOutputHandler is now initialized in main.py and subscribes to events itself.
        # TIF doesn't need to hold a direct instance if AppServices.output_handler is correctly set up.
        # self._output_handler = TerminalOutputHandler(self.console, self.event_bus) # This line is removed

        self.active_dedicated_prompt_request: Optional[RequestPromptEvent] = None
        self.dedicated_prompt_response_future: Optional[asyncio.Future[str]] = None
        self._prompt_handler_task: Optional[asyncio.Task] = None


    async def initialize(self):
        """Subscribe to events needed by TIF itself."""
        if self.event_bus:
            # TIF needs to handle RequestPromptEvent to then use self.session.prompt_async
            await self.event_bus.subscribe(RequestPromptEvent, self._handle_request_prompt_event) # type: ignore
        else:
            logger.error("Event bus not available in TerminalInteractionFlow during initialization.")


    async def _handle_request_prompt_event(self, event: RequestPromptEvent):
        """Handles RequestPromptEvent by setting up to ask the user for input."""
        if self.active_dedicated_prompt_request:
            logger.warning("TIF received a new RequestPromptEvent while another is active. Ignoring new one.")
            # Optionally, could queue them or reject by publishing an error event.
            return

        logger.debug(f"TIF: Received RequestPromptEvent (id: {event.correlation_id}): {event.prompt_message}")
        self.active_dedicated_prompt_request = event
        self.dedicated_prompt_response_future = asyncio.get_running_loop().create_future()
        # The _main_loop will now pick this up and use self.session.prompt_async

    async def request_dedicated_input(self, prompt_message: str, style: Optional[str] = None) -> str:
        """
        Concrete implementation of PromptFunc for AppServices.
        Publishes a RequestPromptEvent and awaits its corresponding PromptResponseEvent.
        The 'style' parameter is for the initial display of the prompt message by this function.
        """
        if not self.event_bus:
            logger.error("Event bus not available for request_dedicated_input. Returning empty string.")
            return ""

        if self.active_dedicated_prompt_request:
            # This indicates a potential recursive call or overlapping prompt requests.
            # This simple implementation doesn't queue; it might be an issue if agents
            # call prompt_func while another prompt_func call is already awaiting.
            logger.error("request_dedicated_input called while another dedicated prompt is already active. This may lead to issues.")
            # For robustness, could raise an error or use a lock/queue.
            # For now, let it proceed, but it's a design consideration.

        correlation_id = str(uuid.uuid4())
        # The response_event_type is not strictly needed if we use a future tied to correlation_id,
        # but it's good for event clarity if other systems were to also listen.
        response_event_type = f"prompt_response_for_tif_{correlation_id}"

        # Display the prompt message using Rich console if style is provided
        # This is the "calling" side's display of the prompt.
        # The _main_loop will also display it when it actually prompts.
        if style:
            self.console.print(Text(prompt_message, style=style), end=" ")
        else:
            self.console.print(prompt_message, end=" ")

        # This future will be set by _main_loop when it processes the active_dedicated_prompt_request
        local_response_future = asyncio.get_running_loop().create_future()
        
        # Temporarily store this future, keyed by correlation_id, for _main_loop to use
        # This is a simplified way; a more robust way would be a dict of futures.
        # For now, assuming one prompt_func at a time is being awaited.
        # The _handle_request_prompt_event sets self.dedicated_prompt_response_future
        # This function needs to coordinate with that.
        
        # The logic flow:
        # 1. This function (prompt_func) is called.
        # 2. It publishes RequestPromptEvent.
        # 3. _handle_request_prompt_event (subscribed to RequestPromptEvent) receives it, sets
        #    self.active_dedicated_prompt_request and self.dedicated_prompt_response_future.
        # 4. This function then awaits self.dedicated_prompt_response_future.
        
        # Publish the event that _handle_request_prompt_event will pick up
        await self.event_bus.publish(
            RequestPromptEvent(
                prompt_message=prompt_message, # This message is for the _main_loop's prompt_async
                is_sensitive=False, # TODO: Add sensitivity if needed
                response_event_type=response_event_type, # For matching, if not using future directly
                correlation_id=correlation_id
            )
        )
        
        # Wait for _handle_request_prompt_event to set up self.dedicated_prompt_response_future
        # and then for _main_loop to complete it.
        if self.dedicated_prompt_response_future and not self.dedicated_prompt_response_future.done() :
             # Check if the future being awaited corresponds to *this* request.
             # This simple model assumes only one dedicated prompt is active.
             # If self.active_dedicated_prompt_request.correlation_id == correlation_id:
            try:
                user_response = await asyncio.wait_for(self.dedicated_prompt_response_future, timeout=300.0) # 5 min timeout
                return user_response
            except asyncio.TimeoutError:
                logger.error(f"Timeout waiting for dedicated input for prompt: {prompt_message}")
                # Clean up to avoid deadlock on next call
                if self.active_dedicated_prompt_request and self.active_dedicated_prompt_request.correlation_id == correlation_id:
                    self.active_dedicated_prompt_request = None
                    self.dedicated_prompt_response_future = None
                return "" # Or raise an error
        else:
            # This case should ideally not be hit if _handle_request_prompt_event works correctly
            logger.error("Dedicated prompt future not available or already done when request_dedicated_input awaited.")
            return ""


    async def start(self):
        """Starts the terminal interaction loop."""
        self._running = True
        await self.initialize() # Subscribe to events
        logger.info("TerminalInteractionFlow started and initialized.")
        self.console.print("[bold cyan]Welcome to Pocket Commander![/bold cyan]")
        await self._main_loop()

    async def stop(self):
        """Stops the terminal interaction loop."""
        if self._running:
            self._running = False
            logger.info("TerminalInteractionFlow stopping.")
            if self._prompt_handler_task and not self._prompt_handler_task.done():
                self._prompt_handler_task.cancel()


    async def _main_loop(self):
        """The main input processing loop."""
        while self._running:
            try:
                if self.active_dedicated_prompt_request and self.dedicated_prompt_response_future:
                    # Handle active dedicated prompt
                    prompt_event = self.active_dedicated_prompt_request
                    future_to_set = self.dedicated_prompt_response_future
                    
                    # Clear them before await to prevent re-entry issues on this path
                    self.active_dedicated_prompt_request = None
                    self.dedicated_prompt_response_future = None

                    logger.debug(f"TIF MainLoop: Processing dedicated prompt (id: {prompt_event.correlation_id}): {prompt_event.prompt_message}")
                    # Use prompt_toolkit for actual input, using message from the event
                    user_input_str = await self.session.prompt_async(
                        f"{prompt_event.prompt_message} : " # Make it clear it's a special prompt
                    ) # No completer/autosuggest for dedicated prompts for simplicity

                    if not self._running: break

                    # Publish the response event
                    await self.event_bus.publish(
                        PromptResponseEvent(
                            response_event_type=prompt_event.response_event_type,
                            correlation_id=prompt_event.correlation_id,
                            response_text=user_input_str.strip()
                        )
                    )
                    # Set the future for the original requester (request_dedicated_input)
                    if not future_to_set.done():
                        future_to_set.set_result(user_input_str.strip())
                    
                    continue # Go back to start of loop to check for more dedicated prompts or normal input

                # Normal agent interaction prompt
                # Determine current agent name for the prompt
                current_agent_name = "N/A" # Default
                application_state = self.app_services._application_state_DO_NOT_USE_DIRECTLY
                if application_state:
                    agent_name_val = application_state.get('active_agent_name')
                    if agent_name_val is not None: # Ensure it's not None before assigning
                        current_agent_name = agent_name_val
                # If application_state is None, or 'active_agent_name' is None or missing,
                # current_agent_name remains "N/A".
                
                prompt_text_display = f"({current_agent_name})> "
                
                user_input_str = await self.session.prompt_async(
                    prompt_text_display,
                    auto_suggest=AutoSuggestFromHistory(),
                    completer=self.command_completer,
                )

                if not self._running: break

                command_input = TerminalCommandInput(user_input_str)
                # This callback (top_level_app_input_handler) will now publish an AppInputEvent
                await self.process_input_callback(user_input_str, command_input)

            except KeyboardInterrupt:
                self.console.print("\n[italic yellow]Keyboard interrupt. Type /exit to quit.[/italic yellow]")
            except EOFError:
                self.console.print("\n[bold red]EOF received. Exiting...[/bold red]")
                try:
                    await self.process_input_callback("/exit", TerminalCommandInput("/exit"))
                except SystemExit: pass 
                break 
            except SystemExit: 
                logger.info("SystemExit caught in TIF, propagating to stop.")
                await self.stop() 
                raise 
            except Exception as e:
                self.console.print(f"[bold red]An unexpected error occurred in terminal interaction: {e}[/bold red]")
                logger.exception("Terminal interaction loop error")

        logger.info("Terminal interaction loop ended.")
        if self._running: # If loop exited for reasons other than stop() being called
            self.console.print("Goodbye!")
        self._running = False # Ensure state is consistent