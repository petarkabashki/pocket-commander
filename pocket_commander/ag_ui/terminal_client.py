#%%
import asyncio
import logging
import uuid
from typing import Callable, Awaitable, Any, Optional, List, Dict

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from rich.console import Console
from rich.text import Text
from rich.markup import escape

from pocket_commander.types import AppServices
from pocket_commander.event_bus import AsyncEventBus
from pocket_commander.ag_ui import events as ag_ui_events
from pocket_commander.events import RequestPromptEvent, PromptResponseEvent # Internal prompt events
from pocket_commander.ag_ui.client import AbstractAgUIClient

logger = logging.getLogger(__name__)

# Adapted from TerminalInteractionFlow
class AppStateAwareCompleter(Completer):
    """
    A prompt-toolkit completer that is aware of the application's state
    to provide dynamic command completions.
    """
    def __init__(self, app_services_provider: Callable[[], AppServices]):
        self.app_services_provider = app_services_provider

    def get_completions(self, document: Document, complete_event) -> List[Completion]:
        completions_options: List[str] = []
        app_services = self.app_services_provider()
        
        raw_config = app_services.raw_app_config if app_services.raw_app_config else {}
        
        # Standard commands
        completions_options.extend(["/exit", "/quit", "/q", "/help", "/agents", "/agent"])

        # Agent slugs for direct switching
        resolved_agents = raw_config.get('resolved_agents', {}) 
        completions_options.extend([f"/agent {slug}" for slug in resolved_agents.keys()])
        completions_options.extend(list(resolved_agents.keys())) # Allow direct typing of agent slug as command

        word_before_cursor = document.get_word_before_cursor(WORD=True)
        for cmd_name in completions_options:
            if cmd_name.startswith(word_before_cursor):
                yield Completion(cmd_name, start_position=-len(word_before_cursor))


class TerminalAgUIClient(AbstractAgUIClient):
    """
    Terminal-based implementation of the AgUIClient.
    Manages user interaction via prompt-toolkit and Rich,
    renders ag_ui events, and handles dedicated input prompts.
    """

    def __init__(self, app_services: AppServices, client_id: str = "terminal_main"):
        super().__init__(app_services, client_id)
        self.console = Console()
        self.session = PromptSession(history=FileHistory(f'.{client_id}_history'))
        
        self.command_completer = AppStateAwareCompleter(lambda: self.app_services)
        self._running = False
        
        self.active_dedicated_prompt_request: Optional[RequestPromptEvent] = None
        self.dedicated_prompt_response_future: Optional[asyncio.Future[str]] = None
        self._main_loop_task: Optional[asyncio.Task] = None # To manage the main input loop

        # Buffers for streaming messages and tool args
        self._message_buffers: Dict[str, List[str]] = {} # message_id -> list of content deltas
        self._message_roles: Dict[str, str] = {} # message_id -> role
        self._tool_call_args_buffers: Dict[str, List[str]] = {} # tool_call_id -> list of arg deltas
        self._tool_call_names: Dict[str, str] = {} # tool_call_id -> tool_name

    async def initialize(self) -> None:
        """Subscribe to events needed by the terminal client."""
        if not self.event_bus:
            logger.error("Event bus not available in TerminalAgUIClient during initialization.")
            return

        # For dedicated input prompts
        await self.event_bus.subscribe(RequestPromptEvent, self._handle_request_prompt_event)

        # For rendering ag_ui event stream - subscribe to specific handlers
        await self.event_bus.subscribe(ag_ui_events.TextMessageStartEvent, self._handle_text_message_start)
        await self.event_bus.subscribe(ag_ui_events.TextMessageContentEvent, self._handle_text_message_content)
        await self.event_bus.subscribe(ag_ui_events.TextMessageEndEvent, self._handle_text_message_end)
        
        await self.event_bus.subscribe(ag_ui_events.ToolCallStartEvent, self._handle_tool_call_start)
        await self.event_bus.subscribe(ag_ui_events.ToolCallArgsEvent, self._handle_tool_call_args)
        await self.event_bus.subscribe(ag_ui_events.ToolCallEndEvent, self._handle_tool_call_end)

        await self.event_bus.subscribe(ag_ui_events.RunErrorEvent, self._handle_run_error)
        await self.event_bus.subscribe(ag_ui_events.StepStartedEvent, self._handle_step_started)
        await self.event_bus.subscribe(ag_ui_events.StepFinishedEvent, self._handle_step_finished)
        
        logger.info(f"TerminalAgUIClient '{self.client_id}' initialized and subscribed to relevant events.")

    async def handle_ag_ui_event(self, event: ag_ui_events.Event) -> None:
        # This method could be used if we had a single subscription point,
        # but direct handlers are cleaner for now.
        # Example:
        # if isinstance(event, ag_ui_events.TextMessageStartEvent):
        #     await self._handle_text_message_start(event)
        # ... and so on for other event types.
        logger.debug(f"TerminalAgUIClient received event via generic handler (should be handled by specific subscribers): {event.type}")
        pass


    # --- ag_ui Event Handlers for Output ---
    async def _handle_text_message_start(self, event: ag_ui_events.TextMessageStartEvent):
        logger.debug(f"TerminalClient: TextMessageStart: ID={event.message_id}, Role={event.role}")
        self._message_buffers[event.message_id] = []
        self._message_roles[event.message_id] = event.role
        if event.role == "assistant":
            self.console.print(Text("...", style="italic dim"))

    async def _handle_text_message_content(self, event: ag_ui_events.TextMessageContentEvent):
        logger.debug(f"TerminalClient: TextMessageContent: ID={event.message_id}, Delta='{escape(event.delta)[:50]}...'")
        if event.message_id in self._message_buffers:
            self._message_buffers[event.message_id].append(event.delta)
            # Live streaming can be added here if desired, though it complicates prompt_toolkit
        else:
            logger.warning(f"TerminalClient: Received TextMessageContentEvent for unknown message_id {event.message_id}")

    async def _handle_text_message_end(self, event: ag_ui_events.TextMessageEndEvent):
        logger.debug(f"TerminalClient: TextMessageEnd: ID={event.message_id}")
        role = self._message_roles.pop(event.message_id, "unknown")
        buffered_content = "".join(self._message_buffers.pop(event.message_id, []))
        
        style = self._get_style_for_role(role)
        prefix = ""
        if role == "user": # User messages are published by _publish_user_message_as_ag_ui_events
            prefix = "[bold green]You:[/bold green] "
        elif role == "assistant":
            agent_slug = self.app_services.get_current_agent_slug() if self.app_services else 'AI'
            prefix = f"[bold blue]Assistant ({agent_slug}):[/bold blue] "
        elif role == "tool":
            prefix = "[bold yellow]Tool Result:[/bold yellow] "
        elif role == "system":
            prefix = "[dim cyan]System:[/dim cyan] "
        
        # Basic way to clear the "..." if prompt_toolkit allows easy line manipulation.
        # For now, just print on a new line.
        self.console.print(Text.from_markup(prefix) + Text(buffered_content, style=style))

    def _get_style_for_role(self, role: str) -> str:
        if role == "user": return "green"
        if role == "assistant": return "blue"
        if role == "tool": return "yellow"
        if role == "system": return "dim cyan"
        if role == "error": return "bold red"
        return ""

    async def _handle_tool_call_start(self, event: ag_ui_events.ToolCallStartEvent):
        logger.debug(f"TerminalClient: ToolCallStart: ID={event.tool_call_id}, Name={event.tool_name}")
        self._tool_call_args_buffers[event.tool_call_id] = []
        self._tool_call_names[event.tool_call_id] = event.tool_name
        self.console.print(Text(f"Calling tool: {event.tool_name} (ID: {event.tool_call_id})...", style="italic magenta"))

    async def _handle_tool_call_args(self, event: ag_ui_events.ToolCallArgsEvent):
        logger.debug(f"TerminalClient: ToolCallArgs: ID={event.tool_call_id}, Delta='{escape(event.delta)[:50]}...'")
        if event.tool_call_id in self._tool_call_args_buffers:
            self._tool_call_args_buffers[event.tool_call_id].append(event.delta)
        else:
            logger.warning(f"TerminalClient: Received ToolCallArgsEvent for unknown tool_call_id {event.tool_call_id}")

    async def _handle_tool_call_end(self, event: ag_ui_events.ToolCallEndEvent):
        logger.debug(f"TerminalClient: ToolCallEnd: ID={event.tool_call_id}")
        tool_name = self._tool_call_names.pop(event.tool_call_id, "unknown_tool")
        # Args are buffered but typically not displayed here; result comes as a ToolMessage
        # which is handled by _handle_text_message_end with role="tool"
        logger.info(f"Tool '{tool_name}' (ID: {event.tool_call_id}) call processing finished by agent.")


    async def _handle_run_error(self, event: ag_ui_events.RunErrorEvent):
        logger.error(f"TerminalClient: Received RunErrorEvent: {event.message} (Code: {event.code})")
        self.console.print(Text(f"Error during run: {event.message}", style="bold red"))

    async def _handle_step_started(self, event: ag_ui_events.StepStartedEvent):
        logger.info(f"TerminalClient: Step Started: {event.step_name}")
        self.console.print(Text(f"Step Started: {event.step_name}", style="dim"))

    async def _handle_step_finished(self, event: ag_ui_events.StepFinishedEvent):
        logger.info(f"TerminalClient: Step Finished: {event.step_name}")
        self.console.print(Text(f"Step Finished: {event.step_name}", style="dim"))

    # --- Dedicated Prompt Handling ---
    async def _handle_request_prompt_event(self, event: RequestPromptEvent):
        if self.active_dedicated_prompt_request:
            logger.warning("TerminalClient received a new RequestPromptEvent while another is active. Ignoring new one.")
            # Optionally, queue or reject the new request
            return
        logger.debug(f"TerminalClient: Received RequestPromptEvent (id: {event.correlation_id}): {event.prompt_message}")
        self.active_dedicated_prompt_request = event
        # Create a new future for each request to avoid race conditions
        self.dedicated_prompt_response_future = asyncio.get_running_loop().create_future()


    async def request_dedicated_input(self, prompt_message: str, is_sensitive: bool = False) -> str:
        """
        This method is called by other parts of the system (e.g. an Agent)
        to request dedicated input from the user via this UI client.
        It publishes a RequestPromptEvent, and the main loop will handle it.
        """
        if not self.event_bus:
            logger.error("Event bus not available for request_dedicated_input.")
            return ""
        
        # Ensure no other dedicated prompt is active from this client's perspective
        # This check might be more robust if it considers if _main_loop_task is already handling one
        if self.active_dedicated_prompt_request and not (self.dedicated_prompt_response_future and self.dedicated_prompt_response_future.done()):
             logger.error("request_dedicated_input called while another dedicated prompt is already active by this client.")
             # This might indicate a logic flaw if an agent calls this while UI is already in prompt mode.
             # For now, we allow it, and _handle_request_prompt_event will queue/ignore.
             # A more robust solution might involve a lock or state machine.
             pass


        correlation_id = str(uuid.uuid4())
        # The response_event_type is not strictly needed if we use the future,
        # but good for consistency if other systems listen.
        response_event_type = f"prompt_response_for_client_{self.client_id}_{correlation_id}"
        
        local_future = asyncio.get_running_loop().create_future()

        # This is a "command" to self to enter dedicated prompt mode.
        # The actual prompt display happens in _main_loop when it sees active_dedicated_prompt_request.
        await self.event_bus.publish(
            RequestPromptEvent(
                prompt_message=prompt_message,
                is_sensitive=is_sensitive, # TODO: Implement sensitive input handling in prompt_async
                response_event_type=response_event_type, # For other listeners
                correlation_id=correlation_id,
                # We need a way to link this request to the local_future
                # One way is to store local_future in a dict keyed by correlation_id
                # and _main_loop sets it when it gets the input.
                # For now, _handle_request_prompt_event sets self.dedicated_prompt_response_future
                # which this method will await.
            )
        )
        
        # Wait for the _main_loop to process the RequestPromptEvent and set the future
        # This requires _handle_request_prompt_event to have set self.dedicated_prompt_response_future
        current_dedicated_future = self.dedicated_prompt_response_future
        if current_dedicated_future:
            try:
                # This relies on _main_loop picking up self.active_dedicated_prompt_request
                # and then setting the result on self.dedicated_prompt_response_future
                return await asyncio.wait_for(current_dedicated_future, timeout=300.0) # 5 minutes timeout
            except asyncio.TimeoutError:
                logger.error(f"Timeout waiting for dedicated input: {prompt_message}")
                # Clean up the specific request if it's still this one
                if self.active_dedicated_prompt_request and self.active_dedicated_prompt_request.correlation_id == correlation_id:
                    self.active_dedicated_prompt_request = None
                    if current_dedicated_future and not current_dedicated_future.done():
                        current_dedicated_future.cancel() # Cancel the future
                return ""
            finally:
                 # Ensure future is reset if it was for this specific request
                if self.dedicated_prompt_response_future is current_dedicated_future:
                    self.dedicated_prompt_response_future = None # Reset for next request
        else:
            logger.error("Dedicated prompt future not available when expected.")
            return ""


    # --- Main Loop and Start/Stop ---
    async def start(self) -> None:
        if self._running:
            logger.warning(f"TerminalAgUIClient '{self.client_id}' already running.")
            return
            
        self._running = True
        await self.initialize() # Subscribe to events
        logger.info(f"TerminalAgUIClient '{self.client_id}' started.")
        self.console.print(f"[bold cyan]Welcome to Pocket Commander (Client: {self.client_id})![/bold cyan]")
        
        # Run the main loop in a separate task so start() is not blocking
        self._main_loop_task = asyncio.create_task(self._main_loop())
        # Optionally, add error handling for the task if it exits unexpectedly
        # self._main_loop_task.add_done_callback(self._handle_main_loop_completion)

    async def stop(self) -> None:
        if not self._running:
            logger.info(f"TerminalAgUIClient '{self.client_id}' is not running.")
            return

        self._running = False
        logger.info(f"TerminalAgUIClient '{self.client_id}' stopping.")
        
        if self.active_dedicated_prompt_request and self.dedicated_prompt_response_future and not self.dedicated_prompt_response_future.done():
            self.dedicated_prompt_response_future.cancel("Client stopping")
            self.active_dedicated_prompt_request = None
            self.dedicated_prompt_response_future = None

        if self._main_loop_task and not self._main_loop_task.done():
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task # Allow cleanup within the loop
            except asyncio.CancelledError:
                logger.info(f"Main input loop for '{self.client_id}' was cancelled.")
        self._main_loop_task = None
        logger.info(f"TerminalAgUIClient '{self.client_id}' stopped.")


    async def _main_loop(self):
        while self._running:
            try:
                if self.active_dedicated_prompt_request and self.dedicated_prompt_response_future:
                    # Handle dedicated prompt
                    prompt_event = self.active_dedicated_prompt_request
                    future_to_set = self.dedicated_prompt_response_future
                    
                    # Clear before await, to allow new requests if this one is slow
                    # self.active_dedicated_prompt_request = None 
                    # self.dedicated_prompt_response_future = None # This future is for THIS request.

                    logger.debug(f"TerminalClient MainLoop: Processing dedicated prompt (id: {prompt_event.correlation_id}): {prompt_event.prompt_message}")
                    
                    # Actual prompt display for dedicated input
                    user_input_str = await self.session.prompt_async(
                        f"{prompt_event.prompt_message}: ",
                        is_password=prompt_event.is_sensitive # Use is_sensitive for password mode
                    )

                    if not self._running: break # Check running state after await

                    # Publish response for other systems
                    await self.event_bus.publish(
                        PromptResponseEvent(
                            response_event_type=prompt_event.response_event_type,
                            correlation_id=prompt_event.correlation_id,
                            response_text=user_input_str.strip()
                        )
                    )
                    # Set the future for the original requester
                    if future_to_set and not future_to_set.done():
                        future_to_set.set_result(user_input_str.strip())
                    
                    # Important: Reset after handling to allow next prompt or main input
                    self.active_dedicated_prompt_request = None
                    # self.dedicated_prompt_response_future is reset by request_dedicated_input or if it was this one.
                    # If it was the one set by _handle_request_prompt_event, it should be cleared.
                    if self.dedicated_prompt_response_future is future_to_set:
                         self.dedicated_prompt_response_future = None
                    continue # Go back to start of loop to check for new dedicated prompts or main input

                # Regular input prompt
                current_agent_slug = self.app_services.get_current_agent_slug() if self.app_services else "N/A"
                prompt_text_display = f"({current_agent_slug})> "
                
                user_input_str = await self.session.prompt_async(
                    prompt_text_display,
                    auto_suggest=AutoSuggestFromHistory(),
                    completer=self.command_completer,
                )

                if not self._running: break # Check running state after await

                if user_input_str.strip(): # Only process if there's actual input
                    await self.send_app_input(user_input_str) # This now also publishes ag_ui user message

            except KeyboardInterrupt:
                if not self._running: break
                self.console.print("\n[italic yellow]Keyboard interrupt. Type /exit or /quit to exit.[/italic yellow]")
            except EOFError:
                if not self._running: break
                self.console.print("\n[bold red]EOF received. Exiting...[/bold red]")
                if self._running: # Avoid sending /exit if already stopping
                    await self.send_app_input("/exit") # Gracefully exit via app logic
                break # Exit main loop
            except asyncio.CancelledError:
                logger.info(f"Main input loop for '{self.client_id}' cancelled during prompt_async or processing.")
                break # Exit loop if cancelled
            except Exception as e:
                if not self._running: break
                self.console.print(f"[bold red]An unexpected error occurred in terminal client '{self.client_id}': {e}[/bold red]")
                logger.exception(f"Terminal client '{self.client_id}' main loop error")
                await asyncio.sleep(1) # Avoid fast error loop

        logger.info(f"Terminal client '{self.client_id}' main interaction loop ended.")
        if self._running : # If loop exited but client was not explicitly stopped
             self.console.print(f"Terminal client {self.client_id} session ended.")
        # self._running = False # Ensure state is consistent