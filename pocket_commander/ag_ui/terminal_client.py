#%%
import asyncio
import logging
import uuid
import typing
from typing import Callable, Awaitable, Any, Optional, List, Dict, Type

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from rich.console import Console
from rich.text import Text
from rich.markup import escape

from pocket_commander.types import AppServices
from pocket_commander.event_bus import ZeroMQEventBus
from pocket_commander.ag_ui import events as ag_ui_events
from pocket_commander.events import (
    AppInputEvent,
    RequestPromptEvent,
    PromptResponseEvent,
    # AgUiBaseEvent # Alias for pocket_commander.ag_ui.events.BaseEvent - Not strictly needed if handlers use dicts
)
from pocket_commander.ag_ui.client import AbstractAgUIClient
from pocket_commander.ag_ui.types import Role as AgUiRole # For user message publishing

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
        resolved_agents = raw_config.resolved_agents if raw_config.resolved_agents is not None else {} 
        completions_options.extend([f"/agent {slug}" for slug in resolved_agents.keys()])
        completions_options.extend(list(resolved_agents.keys())) # Allow direct typing of agent slug as command

        word_before_cursor = document.get_word_before_cursor(WORD=True)
        for cmd_name in completions_options:
            if cmd_name.startswith(word_before_cursor):
                yield Completion(cmd_name, start_position=-len(word_before_cursor))


class TerminalAgUIClient(AbstractAgUIClient):
    """
    Terminal-based implementation of the AgUIClient using ZeroMQEventBus.
    Manages user interaction via prompt-toolkit and Rich,
    renders ag_ui events, and handles dedicated input prompts.
    """

    def __init__(self, app_services: AppServices, client_id: str = "terminal_main"):
        super().__init__(app_services, client_id)
        self.console = Console()
        self.session = PromptSession(history=FileHistory(f'.{client_id}_history'))
        
        self.command_completer = AppStateAwareCompleter(lambda: self.app_services)
        self._running = False
        self.session_id = str(uuid.uuid4()) # AI! Add session_id
        
        self.active_dedicated_prompt_request: Optional[RequestPromptEvent] = None # Store the dict data
        self.dedicated_prompt_response_future: Optional[asyncio.Future[str]] = None
        self._main_loop_task: Optional[asyncio.Task] = None

        # Buffers for streaming messages and tool args
        self._message_buffers: Dict[str, List[str]] = {} # message_id -> list of content deltas
        self._message_roles: Dict[str, str] = {} # message_id -> role
        self._tool_call_args_buffers: Dict[str, List[str]] = {} # tool_call_id -> list of arg deltas
        self._tool_call_names: Dict[str, str] = {} # tool_call_id -> tool_name

        # AI! Subscription configuration using new topic strings and direct handlers
        self._subscription_config: List[Dict[str, Any]] = [
            {"topic": "ag_ui.text_message.start", "handler_method_name": "_handle_text_message_stream", "priority": 0},
            {"topic": "ag_ui.text_message.content", "handler_method_name": "_handle_text_message_stream", "priority": 0},
            {"topic": "ag_ui.text_message.end", "handler_method_name": "_handle_text_message_stream", "priority": 0},
            {"topic": "ag_ui.tool_call.start", "handler_method_name": "_handle_tool_call_stream", "priority": 0},
            {"topic": "ag_ui.tool_call.args", "handler_method_name": "_handle_tool_call_stream", "priority": 0},
            {"topic": "ag_ui.tool_call.end", "handler_method_name": "_handle_tool_call_stream", "priority": 0},
            {"topic": "ag_ui.run.error", "handler_method_name": "_handle_run_error", "priority": 0},
            {"topic": "ag_ui.step.started", "handler_method_name": "_handle_step_started", "priority": 0},
            {"topic": "ag_ui.step.finished", "handler_method_name": "_handle_step_finished", "priority": 0},
            # RequestPromptEvent is not an ag_ui.event but handled similarly
            {"topic": RequestPromptEvent.__name__, "handler_method_name": "_handle_request_prompt_event", "priority": 0},
        ]

    # AI! Property to get ZeroMQEventBus instance with type safety
    @property
    def event_bus(self) -> Optional[ZeroMQEventBus]:
        if self.app_services and isinstance(self.app_services.event_bus, ZeroMQEventBus):
            return self.app_services.event_bus
        # Log or raise error if event_bus is not ZeroMQEventBus or not available
        if self.app_services and self.app_services.event_bus is not None:
            logger.error(f"TerminalAgUIClient expected ZeroMQEventBus, but found {type(self.app_services.event_bus)}")
        return None

    async def initialize(self) -> None:
        """Subscribe to events needed by the terminal client using string topics and direct handlers."""
        if not self.event_bus:
            logger.error("ZeroMQEventBus not available in TerminalAgUIClient during initialization.")
            return

        for sub_config in self._subscription_config:
            handler_method_name = sub_config["handler_method_name"]
            topic = sub_config["topic"] 
            priority = sub_config["priority"]
            
            try:
                actual_handler_method = getattr(self, handler_method_name)
                await self.event_bus.subscribe(
                    topic_pattern=topic, 
                    handler_coroutine=actual_handler_method,
                    priority=priority
                )
                logger.debug(f"TerminalAgUIClient subscribed handler '{handler_method_name}' to topic '{topic}' with priority {priority}.")
            except AttributeError:
                logger.error(f"Failed to subscribe: Handler method '{handler_method_name}' not found in TerminalAgUIClient.")
            except Exception as e:
                logger.error(f"Failed to subscribe handler '{handler_method_name}' to topic '{topic}': {e}")
        
        logger.info(f"TerminalAgUIClient '{self.client_id}' initialized and subscriptions set up with ZeroMQEventBus.")

    async def handle_ag_ui_event(self, event: ag_ui_events.Event) -> None:
        # This method is part of the AbstractAgUIClient interface.
        # With specific topic-based subscriptions via ZeroMQEventBus, events are routed directly to handlers.
        # This method should ideally not be called if subscriptions are set up correctly.
        logger.warning(f"TerminalAgUIClient received event via generic handle_ag_ui_event (should be handled by specific ZMQ subscribers): {type(event)}")
        pass

    # --- Refactored ag_ui Event Handlers for Output ---

    async def _handle_text_message_stream(self, topic: str, event_data: dict) -> None:
        """Handles TEXT_MESSAGE_START, TEXT_MESSAGE_CONTENT, and TEXT_MESSAGE_END events based on topic."""
        
        # Determine event type from topic
        # Example: "ag_ui.text_message.start" -> TEXT_MESSAGE_START
        event_type_str = topic.split('.')[-1].upper() # e.g. START, CONTENT, END
        
        try:
            # Map string to enum member if needed, or use string directly
            # For simplicity, we'll compare with expected topic suffixes
            if topic.endswith("text_message.start"):
                # specific_event = ag_ui_events.TextMessageStartEvent.model_validate(event_data) # Optional Pydantic validation
                message_id = event_data.get("message_id")
                role = event_data.get("role")
                logger.debug(f"TerminalClient: TextMessageStart: ID={message_id}, Role={role} (Topic: {topic})")
                if message_id:
                    self._message_buffers[message_id] = []
                    self._message_roles[message_id] = role if role else "unknown"
                if role == "assistant":
                    self.console.print(Text("...", style="italic dim"))

            elif topic.endswith("text_message.content"):
                # specific_event = ag_ui_events.TextMessageContentEvent.model_validate(event_data)
                message_id = event_data.get("message_id")
                delta = event_data.get("delta")
                logger.debug(f"TerminalClient: TextMessageContent: ID={message_id}, Delta='{escape(delta)[:50]}...' (Topic: {topic})")
                if message_id in self._message_buffers:
                    self._message_buffers[message_id].append(delta if delta else "")
                else:
                    logger.warning(f"TerminalClient: Received TextMessageContentEvent for unknown message_id {message_id} (Topic: {topic})")
            
            elif topic.endswith("text_message.end"):
                # specific_event = ag_ui_events.TextMessageEndEvent.model_validate(event_data)
                message_id = event_data.get("message_id")
                logger.debug(f"TerminalClient: TextMessageEnd: ID={message_id} (Topic: {topic})")
                role = self._message_roles.pop(message_id, "unknown")
                buffered_content = "".join(self._message_buffers.pop(message_id, []))
                
                style = self._get_style_for_role(role)
                prefix = ""
                if role == "user":
                    prefix = "[bold green]You:[/bold green] "
                elif role == "assistant":
                    agent_slug = self.app_services.get_current_agent_slug() if self.app_services else 'AI'
                    prefix = f"[bold blue]Assistant ({agent_slug}):[/bold blue] "
                elif role == "tool":
                    prefix = "[bold yellow]Tool Result:[/bold yellow] "
                elif role == "system":
                    prefix = "[dim cyan]System:[/dim cyan] "
                
                self.console.print(Text.from_markup(prefix) + Text(buffered_content, style=style))
            else:
                logger.warning(f"TerminalClient: _handle_text_message_stream received unexpected topic: {topic}")

        except Exception as e:
            logger.error(f"TerminalClient: Error processing text message stream for topic '{topic}': {e}\nData: {event_data}")


    async def _handle_tool_call_stream(self, topic: str, event_data: dict) -> None:
        """Handles TOOL_CALL_START, TOOL_CALL_ARGS, and TOOL_CALL_END events based on topic."""
        try:
            if topic.endswith("tool_call.start"):
                # specific_event = ag_ui_events.ToolCallStartEvent.model_validate(event_data)
                tool_call_id = event_data.get("tool_call_id")
                tool_name = event_data.get("tool_name")
                logger.debug(f"TerminalClient: ToolCallStart: ID={tool_call_id}, Name={tool_name} (Topic: {topic})")
                if tool_call_id:
                    self._tool_call_args_buffers[tool_call_id] = []
                    self._tool_call_names[tool_call_id] = tool_name if tool_name else "unknown_tool"
                self.console.print(Text(f"Calling tool: {tool_name} (ID: {tool_call_id})...", style="italic magenta"))

            elif topic.endswith("tool_call.args"):
                # specific_event = ag_ui_events.ToolCallArgsEvent.model_validate(event_data)
                tool_call_id = event_data.get("tool_call_id")
                delta = event_data.get("delta")
                logger.debug(f"TerminalClient: ToolCallArgs: ID={tool_call_id}, Delta='{escape(delta)[:50]}...' (Topic: {topic})")
                if tool_call_id in self._tool_call_args_buffers:
                    self._tool_call_args_buffers[tool_call_id].append(delta if delta else "")
                else:
                    logger.warning(f"TerminalClient: Received ToolCallArgsEvent for unknown tool_call_id {tool_call_id} (Topic: {topic})")

            elif topic.endswith("tool_call.end"):
                # specific_event = ag_ui_events.ToolCallEndEvent.model_validate(event_data)
                tool_call_id = event_data.get("tool_call_id")
                logger.debug(f"TerminalClient: ToolCallEnd: ID={tool_call_id} (Topic: {topic})")
                tool_name = self._tool_call_names.pop(tool_call_id, "unknown_tool")
                logger.info(f"Tool '{tool_name}' (ID: {tool_call_id}) call processing finished by agent.")
            else:
                logger.warning(f"TerminalClient: _handle_tool_call_stream received unexpected topic: {topic}")
        except Exception as e:
            logger.error(f"TerminalClient: Error processing tool call stream for topic '{topic}': {e}\nData: {event_data}")

    def _get_style_for_role(self, role: str) -> str:
        if role == "user": return "green"
        if role == "assistant": return "blue"
        if role == "tool": return "yellow"
        if role == "system": return "dim cyan"
        if role == "error": return "bold red"
        return ""

    async def _handle_run_error(self, topic: str, event_data: dict):
        # event = ag_ui_events.RunErrorEvent.model_validate(event_data) # Optional Pydantic validation
        message = event_data.get("message", "Unknown error")
        code = event_data.get("code", "N/A")
        logger.error(f"TerminalClient: Received RunErrorEvent (Topic: {topic}): {message} (Code: {code})")
        self.console.print(Text(f"Error during run: {message}", style="bold red"))

    async def _handle_step_started(self, topic: str, event_data: dict):
        # event = ag_ui_events.StepStartedEvent.model_validate(event_data) # Optional Pydantic validation
        step_name = event_data.get("step_name", "Unnamed step")
        logger.info(f"TerminalClient: Step Started (Topic: {topic}): {step_name}")
        self.console.print(Text(f"Step Started: {step_name}", style="dim"))

    async def _handle_step_finished(self, topic: str, event_data: dict):
        # event = ag_ui_events.StepFinishedEvent.model_validate(event_data) # Optional Pydantic validation
        step_name = event_data.get("step_name", "Unnamed step")
        logger.info(f"TerminalClient: Step Finished (Topic: {topic}): {step_name}")
        self.console.print(Text(f"Step Finished: {step_name}", style="dim"))

    # --- Dedicated Prompt Handling ---
    async def _handle_request_prompt_event(self, topic: str, event_data: dict):
        # event = RequestPromptEvent.model_validate(event_data) # Optional Pydantic validation
        if self.active_dedicated_prompt_request:
            logger.warning("TerminalClient received a new RequestPromptEvent while another is active. Ignoring new one.")
            return
        
        correlation_id = event_data.get("correlation_id")
        prompt_message = event_data.get("prompt_message", "Enter input:")
        logger.debug(f"TerminalClient: Received RequestPromptEvent (Topic: {topic}, id: {correlation_id}): {prompt_message}")
        
        # Store the raw event_data as it might be needed by _main_loop
        self.active_dedicated_prompt_request = event_data 
        self.dedicated_prompt_response_future = asyncio.get_running_loop().create_future()

    # AI! Override send_app_input from AbstractAgUIClient for ZeroMQEventBus
    async def send_app_input(self, user_input: str, active_agent_slug: str) -> None: # AI! Added active_agent_slug
        """
        Sends user input to the application core and echoes it to the UI.
        Uses ZeroMQEventBus for publishing.
        """
        logger.info(f"[{self.client_id}] send_app_input called with: '{user_input}', active_agent_slug: '{active_agent_slug}'")

        if not self.event_bus:
            logger.error(f"[{self.client_id}] ZeroMQEventBus not available to send AppInputEvent for '{user_input}'.")
            return

        # 1. Publish user's own message for display (as ag_ui events with new topics)
        # This part makes the user's own input appear in their terminal.
        user_message_id = str(uuid.uuid4())
        logger.debug(f"[{self.client_id}] Publishing user's own input display events (message_id: {user_message_id}) for: '{user_input}'")
        
        try:
            # TextMessageStart
            start_event_data = ag_ui_events.TextMessageStartEvent(
                type=ag_ui_events.EventType.TEXT_MESSAGE_START,
                message_id=user_message_id,
                role="user" # Use literal string value for AgUiRole
            ).model_dump()
            await self.event_bus.publish(ag_ui_events.Topics.TEXT_MESSAGE_START, start_event_data)

            # TextMessageContent
            if user_input: 
                content_event_data = ag_ui_events.TextMessageContentEvent(
                    type=ag_ui_events.EventType.TEXT_MESSAGE_CONTENT,
                    message_id=user_message_id,
                    delta=user_input
                ).model_dump()
                await self.event_bus.publish(ag_ui_events.Topics.TEXT_MESSAGE_CONTENT, content_event_data)

            # TextMessageEnd
            end_event_data = ag_ui_events.TextMessageEndEvent(
                type=ag_ui_events.EventType.TEXT_MESSAGE_END,
                message_id=user_message_id
            ).model_dump()
            await self.event_bus.publish(ag_ui_events.Topics.TEXT_MESSAGE_END, end_event_data)
            logger.debug(f"[{self.client_id}] Successfully published user display events for '{user_input}'.")
        except Exception as e:
            logger.error(f"[{self.client_id}] Error publishing user display events for '{user_input}': {e}", exc_info=True)
            # Continue to attempt publishing AppInputEvent anyway

        # 2. Publish the AppInputEvent for AppCore with the topic "app.ui.input"
        try:
            app_input_event = AppInputEvent(
                input_text=user_input,
                source_ui_client_id=self.client_id
                # session_id and active_agent_slug are not part of current AppInputEvent definition
            )
            app_input_event_data = app_input_event.model_dump() # Convert Pydantic model to dict
            
            logger.info(f"[{self.client_id}] Preparing to publish AppInputEvent to topic '{AppInputEvent.TOPIC}': {app_input_event.model_dump_json(indent=2)}")
            
            await self.event_bus.publish(AppInputEvent.TOPIC, app_input_event_data)
            logger.info(f"[{self.client_id}] AppInputEvent for '{user_input}' published successfully to topic '{AppInputEvent.TOPIC}'.")
        except Exception as e:
            logger.error(f"[{self.client_id}] Error publishing AppInputEvent for '{user_input}': {e}", exc_info=True)


    async def request_dedicated_input(self, prompt_message: str, is_sensitive: bool = False) -> str:
        if not self.event_bus:
            logger.error("ZeroMQEventBus not available for request_dedicated_input.")
            return ""
        
        if self.active_dedicated_prompt_request and not (self.dedicated_prompt_response_future and self.dedicated_prompt_response_future.done()):
             logger.error("request_dedicated_input called while another dedicated prompt is already active by this client.")
             return "" 

        correlation_id = str(uuid.uuid4())
        response_topic_for_this_request = f"prompt_response_for_client_{self.client_id}_{correlation_id}"
        
        request_event_data = RequestPromptEvent(
            prompt_message=prompt_message,
            is_sensitive=is_sensitive,
            response_event_type=response_topic_for_this_request, 
            correlation_id=correlation_id,
        ).model_dump()
        
        request_topic = RequestPromptEvent.__name__
        await self.event_bus.publish(request_topic, request_event_data)
        
        local_future_for_this_request = asyncio.get_running_loop().create_future()
        # _handle_request_prompt_event will set self.active_dedicated_prompt_request (with the dict data)
        # and self.dedicated_prompt_response_future (with this new future instance)
        # This assignment here is slightly ahead, but _handle_request_prompt_event confirms it.
        # The critical part is that _main_loop uses the future set by _handle_request_prompt_event.
        
        # To ensure the future awaited is the one set by the handler:
        # We'll rely on _handle_request_prompt_event to set self.dedicated_prompt_response_future.
        # This method will then await that.
        
        # This creates a new future that this call will wait on.
        # _handle_request_prompt_event will set self.dedicated_prompt_response_future to this instance.
        # _main_loop will then complete self.dedicated_prompt_response_future.
        self.dedicated_prompt_response_future = local_future_for_this_request # Temp store, handler will confirm

        try:
            # Wait for _handle_request_prompt_event to receive the event and set up the future properly.
            # A short sleep might be needed if the event bus is slow, but ideally, it's quick.
            # For robustness, a loop with timeout could check if self.dedicated_prompt_response_future
            # has been set by the handler to `local_future_for_this_request`.
            # However, simpler is to assume the handler runs and sets it.
            # The `_main_loop` will use `self.active_dedicated_prompt_request` (which is the dict)
            # and `self.dedicated_prompt_response_future` (which is the future instance).
            
            # The future that _handle_request_prompt_event sets up is the one we need to await.
            # Let's ensure it's set before awaiting.
            # A more robust pattern might involve passing the future to the handler via the event,
            # or a dictionary mapping correlation_ids to futures.
            # For now, we rely on the modal nature of prompts for this client.

            # The future is created and stored in self.dedicated_prompt_response_future by _handle_request_prompt_event
            # This method then awaits it.
            if not self.dedicated_prompt_response_future or self.dedicated_prompt_response_future.done():
                 # This case implies _handle_request_prompt_event hasn't run or a previous one is stuck.
                 # For simplicity, we assume _handle_request_prompt_event will create a new one.
                 # The assignment in _handle_request_prompt_event is key.
                 pass # The future is set in the handler.

            # The future we await is the one set by _handle_request_prompt_event
            # This `local_future_for_this_request` is effectively what `_handle_request_prompt_event` will assign to `self.dedicated_prompt_response_future`
            
            # The _main_loop will use the `prompt_message` and `is_sensitive` from `self.active_dedicated_prompt_request` (the dict)
            # and will set the result on `self.dedicated_prompt_response_future` (the future instance).

            return await asyncio.wait_for(local_future_for_this_request, timeout=300.0)
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for dedicated input: {prompt_message}")
            # Check if the active request matches this timed-out one
            active_req_data = self.active_dedicated_prompt_request
            if active_req_data and active_req_data.get("correlation_id") == correlation_id:
                self.active_dedicated_prompt_request = None 
            if not local_future_for_this_request.done():
                local_future_for_this_request.cancel()
            return ""
        finally:
            # Clear the global future if it's the one we just processed and it matches
            if self.dedicated_prompt_response_future is local_future_for_this_request:
                 self.dedicated_prompt_response_future = None
            # Clear the active request if it matches this one, regardless of future state
            active_req_data = self.active_dedicated_prompt_request
            if active_req_data and active_req_data.get("correlation_id") == correlation_id:
                self.active_dedicated_prompt_request = None


    # --- Main Loop and Start/Stop ---
    async def start(self) -> None:
        if self._running:
            logger.warning(f"TerminalAgUIClient '{self.client_id}' already running.")
            return
            
        self._running = True
        await self.initialize() # Subscribe to events
        logger.info(f"TerminalAgUIClient '{self.client_id}' started.")
        self.console.print(f"[bold cyan]Welcome to Pocket Commander (Client: {self.client_id})![/bold cyan]")
        
        self._main_loop_task = asyncio.create_task(self._main_loop())

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
                await self._main_loop_task
            except asyncio.CancelledError:
                logger.info(f"Main input loop for '{self.client_id}' was cancelled.")
        self._main_loop_task = None
        logger.info(f"TerminalAgUIClient '{self.client_id}' stopped.")


    async def _main_loop(self):
        while self._running:
            try:
                # Dedicated prompt handling
                if self.active_dedicated_prompt_request and self.dedicated_prompt_response_future:
                    # self.active_dedicated_prompt_request is now a dict
                    prompt_event_data = self.active_dedicated_prompt_request 
                    future_to_set = self.dedicated_prompt_response_future
                    
                    prompt_message = prompt_event_data.get("prompt_message", "Input:")
                    is_sensitive = prompt_event_data.get("is_sensitive", False)
                    correlation_id = prompt_event_data.get("correlation_id")
                    response_event_topic = prompt_event_data.get("response_event_type") # This is the topic

                    logger.debug(f"TerminalClient MainLoop: Processing dedicated prompt (id: {correlation_id}): {prompt_message}")
                    
                    user_input_str = await self.session.prompt_async(
                        f"{prompt_message}: ",
                        is_password=is_sensitive
                    )

                    if not self._running: break 

                    # Publish PromptResponseEvent using ZeroMQEventBus
                    if response_event_topic: # Ensure topic is available
                        response_payload_dict = PromptResponseEvent(
                            response_event_type=response_event_topic, # This field is mostly for consistency now
                            correlation_id=correlation_id,
                            response_text=user_input_str.strip()
                        ).model_dump()
                        if self.event_bus:
                            await self.event_bus.publish(response_event_topic, response_payload_dict)
                    else:
                        logger.error(f"TerminalClient MainLoop: Missing response_event_type (topic) for dedicated prompt {correlation_id}")
                    
                    if future_to_set and not future_to_set.done():
                        future_to_set.set_result(user_input_str.strip())
                    
                    self.active_dedicated_prompt_request = None
                    if self.dedicated_prompt_response_future is future_to_set:
                         self.dedicated_prompt_response_future = None
                    continue

                # Regular prompt
                current_agent_slug = self.app_services.get_current_agent_slug() if self.app_services else "N/A"
                prompt_text_display = f"({current_agent_slug})> "
                
                user_input_str = await self.session.prompt_async(
                    prompt_text_display,
                    auto_suggest=AutoSuggestFromHistory(),
                    completer=self.command_completer,
                )

                if not self._running: break 

                if user_input_str.strip():
                    await self.send_app_input(user_input_str, active_agent_slug=current_agent_slug) 

            except KeyboardInterrupt:
                if not self._running: break
                self.console.print("\n[italic yellow]Keyboard interrupt. Type /exit or /quit to exit.[/italic yellow]")
            except EOFError:
                if not self._running: break
                self.console.print("\n[bold red]EOF received. Exiting...[/bold red]")
                if self._running: 
                    await self.send_app_input("/exit")
                break 
            except asyncio.CancelledError:
                logger.info(f"Main input loop for '{self.client_id}' cancelled during prompt_async or processing.")
                break
            except Exception as e:
                if not self._running: break
                self.console.print(f"[bold red]An unexpected error occurred in terminal client '{self.client_id}': {e}[/bold red]")
                logger.exception(f"Terminal client '{self.client_id}' main loop error")
                await asyncio.sleep(1) 

        logger.info(f"Terminal client '{self.client_id}' main interaction loop ended.")
        if self._running : 
             self.console.print(f"Terminal client {self.client_id} session ended.")