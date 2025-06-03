import asyncio
import logging
import uuid
import json # For tool call arguments
from typing import Dict, Any, Optional, List

from pocket_commander.pocketflow.base import AsyncNode
from pocket_commander.types import AppServices, AgentConfig
from pocket_commander.event_bus import ZeroMQEventBus
from pocket_commander.events import AgentLifecycleEvent # Internal lifecycle event
from pocket_commander.ag_ui import events as ag_ui_events
from pocket_commander.ag_ui import types as ag_ui_types

logging.basicConfig(
    level=logging.DEBUG,           # set root level to DEBUG
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)

def _get_ag_ui_topic(event_type: ag_ui_events.EventType) -> str:
    """
    Converts an ag_ui EventType enum to a hierarchical topic string.
    e.g., TEXT_MESSAGE_START -> ag_ui.text_message.start
    e.g., TOOL_CALL_ARGS   -> ag_ui.tool_call.args
    e.g., RUN_FINISHED     -> ag_ui.run.finished
    """
    value_lower = event_type.value.lower()
    last_underscore_idx = value_lower.rfind('_')
    if last_underscore_idx != -1:
        name_part = value_lower[:last_underscore_idx]
        action_part = value_lower[last_underscore_idx+1:]
        return f"ag_ui.{name_part}.{action_part}"
    else:
        # For event types like RAW, CUSTOM that might not have an underscore
        return f"ag_ui.{value_lower}"
class MainDefaultAgent(AsyncNode):
    """
    The main default agent for Pocket Commander.
    Handles basic interactions, provides general information, and can initiate tool calls.
    Interacts via the event bus using ag_ui events and types.
    """

    def __init__(self, app_services: AppServices, **init_args: Any):
        super().__init__()
        self.app_services = app_services
        self.event_bus: ZeroMQEventBus = app_services.event_bus # type: ignore
        self.init_args = init_args
        self.slug = init_args.get("slug", "main")
        self.default_greet_name = init_args.get("default_greet_name", "User")
        self._is_active = False
        self._current_run_id: Optional[str] = None # To associate messages with a run
        self._message_history: List[ag_ui_types.Message] = [] # Simple in-memory history for this agent

        logger.info(f"MainDefaultAgent '{self.slug}' initialized with args: {init_args}")

        if self.event_bus:
            # Subscribe to internal AgentLifecycleEvent for activation/deactivation
            asyncio.create_task(self.event_bus.subscribe("AgentLifecycleEvent", self._handle_internal_lifecycle_event_adapter))
            logger.info(f"MainDefaultAgent '{self.slug}': Subscribed to internal AgentLifecycleEvent.")
            # We will subscribe to ag_ui_events.MessagesSnapshotEvent when a run starts
        else:
            logger.error(f"MainDefaultAgent '{self.slug}': Event bus not available in __init__.")

    async def _publish_text_message(self, content: str, role: ag_ui_types.Role, parent_message_id: Optional[str] = None) -> str:
        """Helper to publish a complete text message sequence."""
        message_id = str(uuid.uuid4())
        
        # Create the message object for internal history
        common_message_args = {"id": message_id, "role": role, "content": content}
        if role == "assistant":
            new_message = ag_ui_types.AssistantMessage(**common_message_args) # type: ignore
        elif role == "user":
            new_message = ag_ui_types.UserMessage(**common_message_args) # type: ignore
        elif role == "system":
            new_message = ag_ui_types.SystemMessage(**common_message_args) # type: ignore
        else: # Fallback, though ideally roles are specific
            new_message = ag_ui_types.DeveloperMessage(id=message_id, role="developer", content=f"Message with role {role}: {content}")

        self._message_history.append(new_message)

        start_event = ag_ui_events.TextMessageStartEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_START, message_id=message_id, role=role)
        await self.event_bus.publish(_get_ag_ui_topic(start_event.type), start_event.model_dump(mode="json"))
        if content: # Only send content event if there is content
            content_event = ag_ui_events.TextMessageContentEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=content)
            await self.event_bus.publish(_get_ag_ui_topic(content_event.type), content_event.model_dump(mode="json"))
        end_event = ag_ui_events.TextMessageEndEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_END, message_id=message_id)
        await self.event_bus.publish(_get_ag_ui_topic(end_event.type), end_event.model_dump(mode="json"))

    async def _handle_internal_lifecycle_event_adapter(self, topic: str, data: dict):
        logger.debug(f"MainDefaultAgent '{self.slug}' received raw lifecycle event on topic '{topic}': {data}")
        try:
            event = AgentLifecycleEvent.model_validate(data)
            await self.handle_internal_lifecycle_event(event)
        except Exception as e:
            logger.error(f"Error processing AgentLifecycleEvent from topic '{topic}': {e}", exc_info=True)

    async def handle_internal_lifecycle_event(self, event: AgentLifecycleEvent):
        logger.debug(f"MainDefaultAgent '{self.slug}' received internal AgentLifecycleEvent: {event.lifecycle_type} for agent '{event.agent_name}'")
        if event.agent_name == self.slug:
            if event.lifecycle_type == "activating" and not self._is_active:
                await self.on_agent_activate()
            elif event.lifecycle_type == "deactivating" and self._is_active:
                await self.on_agent_deactivate()

    async def on_agent_activate(self):
        self._is_active = True
        # We expect a RunStartedEvent to trigger actual message processing subscriptions
        logger.info(f"MainDefaultAgent '{self.slug}' activated. Awaiting RunStartedEvent to begin processing messages.")
        await self._publish_text_message(
            content=f"Welcome! Main Agent '{self.slug}' is active. How can I help?",
            role="assistant"
        )

    async def on_agent_deactivate(self):
        self._is_active = False
        if self._current_run_id: # If a run was active, mark it as finished
            finished_event = ag_ui_events.RunFinishedEvent(type=ag_ui_events.EventType.RUN_FINISHED, thread_id=self.slug, run_id=self._current_run_id) # Using slug as thread_id for now
            await self.event_bus.publish(_get_ag_ui_topic(ag_ui_events.EventType.STEP_FINISHED), finished_event.model_dump(mode="json"))
            self._current_run_id = None
        
        # Unsubscribe from message events
        await self.event_bus.unsubscribe(_get_ag_ui_topic(ag_ui_events.EventType.MESSAGES_SNAPSHOT), self._handle_message_snapshot_adapter)
        # Could also unsubscribe from TextMessageEndEvent if we were listening for user messages that way
        logger.info(f"MainDefaultAgent '{self.slug}' deactivated and unsubscribed from message events.")

    async def _handle_run_started_adapter(self, topic: str, data: dict):
        logger.debug(f"MainDefaultAgent '{self.slug}' received raw run started event on topic '{topic}': {data}")
        try:
            event = ag_ui_events.RunStartedEvent.model_validate(data)
            await self.handle_run_started(event)
        except Exception as e:
            logger.error(f"Error processing RunStartedEvent from topic '{topic}': {e}", exc_info=True)

    async def handle_run_started(self, event: ag_ui_events.RunStartedEvent):
        """Handles the start of a new run, typically initiated by user input."""
        if not self._is_active:
            return
        
        self._current_run_id = event.run_id
        self._message_history = [] # Clear history for the new run
        logger.info(f"MainDefaultAgent '{self.slug}' received RunStartedEvent (ID: {event.run_id}). Subscribing to MessagesSnapshotEvent.")
        # Subscribe to MessagesSnapshotEvent to get the initial context for this run
        await self.event_bus.subscribe(_get_ag_ui_topic(ag_ui_events.EventType.MESSAGES_SNAPSHOT), self._handle_message_snapshot_adapter)

    async def _handle_message_snapshot_adapter(self, topic: str, data: dict):
        logger.debug(f"MainDefaultAgent '{self.slug}' received raw message snapshot on topic '{topic}': {data}")
        try:
            event = ag_ui_events.MessagesSnapshotEvent.model_validate(data)
            await self.handle_message_snapshot(event)
        except Exception as e:
            logger.error(f"Error processing MessagesSnapshotEvent from topic '{topic}': {e}", exc_info=True)

    async def handle_message_snapshot(self, event: ag_ui_events.MessagesSnapshotEvent):
        """Processes a snapshot of messages, typically the user's input."""
        if not self._is_active or not self._current_run_id:
            logger.debug("MainAgent not active or no current run, ignoring message snapshot.")
            return

        self._message_history.extend(event.messages)
        
        # For this agent, we'll assume the last message is the one to process.
        # More complex agents might look at the whole thread.
        last_message = event.messages[-1] if event.messages else None

        if last_message and last_message.role == "user" and isinstance(last_message.content, str):
            raw_text = last_message.content.strip()
            logger.debug(f"MainDefaultAgent '{self.slug}' processing user message (ID: {last_message.id}): '{raw_text}'")
            
            # Simple command parsing for this example agent
            parts = raw_text.lower().split(" ", 1)
            command = parts[0]
            args_str = parts[1] if len(parts) > 1 else ""

            if command == "greet" or command == "hello":
                name_arg = args_str.strip() if args_str else None
                await self._do_greet(name_arg, parent_message_id=last_message.id)
            elif command == "agentinfo":
                await self._do_agentinfo(parent_message_id=last_message.id)
            elif command == "help":
                await self._do_help(parent_message_id=last_message.id)
            elif command == "use_tool_time": # Example command to trigger a tool
                await self._do_use_tool_time(parent_message_id=last_message.id)
            else:
                await self._publish_text_message(
                    content=f"'{raw_text}' is not a recognized command for the Main Agent. Try 'help'.",
                    role="assistant",
                    parent_message_id=last_message.id
                )
        else:
            logger.debug(f"MainDefaultAgent '{self.slug}' received message snapshot, but no user message to process or content is not string.")

        # Once processed, this agent considers its part of the run finished for this input.
        # More complex agents might have multiple steps.
        if self._current_run_id:
            finished_event = ag_ui_events.RunFinishedEvent(type=ag_ui_events.EventType.RUN_FINISHED, thread_id=self.slug, run_id=self._current_run_id)
            await self.event_bus.publish(_get_ag_ui_topic(ag_ui_events.EventType.STEP_FINISHED), finished_event.model_dump(mode="json"))
            self._current_run_id = None # Reset for the next run
            # Unsubscribe from MessagesSnapshotEvent until the next RunStartedEvent
            await self.event_bus.unsubscribe(_get_ag_ui_topic(ag_ui_events.EventType.MESSAGES_SNAPSHOT), self._handle_message_snapshot_adapter)
            logger.info(f"MainDefaultAgent '{self.slug}' finished processing run {self._current_run_id} and unsubscribed from MessagesSnapshotEvent.")


    async def _do_greet(self, name_arg: Optional[str], parent_message_id: str):
        name_to_greet = name_arg if name_arg else self.default_greet_name
        await self._publish_text_message(
            content=f"Hello, {name_to_greet}, from the {self.slug} Agent!",
            role="assistant",
            parent_message_id=parent_message_id
        )

    async def _do_agentinfo(self, parent_message_id: str):
        my_resolved_config: Optional[AgentConfig] = self.app_services.raw_app_config.get('resolved_agents', {}).get(self.slug)
        info_lines = [f"--- Agent: {self.slug} ---"]
        if my_resolved_config:
            info_lines.append(f"Description: {my_resolved_config.description}")
            # ... (add other info as needed)
        info_lines.append(f"Init Args Received: {self.init_args}")
        await self._publish_text_message("\n".join(info_lines), role="assistant", parent_message_id=parent_message_id)

    async def _do_help(self, parent_message_id: str):
        help_text = f"""--- {self.slug} Agent Help ---
Available inputs:
  greet [name]         - Greets you or the specified name. (Alias: hello)
  agentinfo            - Shows information about this agent.
  use_tool_time        - Example: Calls the 'time_tool' to get current time.
  help                 - Shows this help message.
Global commands (start with /) are handled by the application core."""
        await self._publish_text_message(help_text, role="assistant", parent_message_id=parent_message_id)

    async def _do_use_tool_time(self, parent_message_id: str):
        """Example of initiating a tool call."""
        tool_name = "time_tool" # Assuming 'time_tool' is registered globally
        tool_call_id = str(uuid.uuid4())
        assistant_message_id = str(uuid.uuid4())

        # 1. Construct AssistantMessage with ToolCall
        tool_call = ag_ui_types.ToolCall(
            id=tool_call_id,
            type="function", # Currently only "function" is supported by ag_ui_types.ToolCall
            function=ag_ui_types.FunctionCall(
                name=tool_name,
                arguments=json.dumps({}) # Time tool might not need arguments
            )
        )
        assistant_message_with_tool_call = ag_ui_types.AssistantMessage(
            id=assistant_message_id,
            role="assistant",
            content=f"Okay, I will use the '{tool_name}' to get the current time.",
            tool_calls=[tool_call]
        )
        self._message_history.append(assistant_message_with_tool_call)

        # 2. Publish events for the AssistantMessage (text part)
        text_start_event = ag_ui_events.TextMessageStartEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_START, message_id=assistant_message_id, role="assistant")
        await self.event_bus.publish(_get_ag_ui_topic(text_start_event.type), text_start_event.model_dump(mode="json"))
        if assistant_message_with_tool_call.content:
            text_content_event = ag_ui_events.TextMessageContentEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_CONTENT, message_id=assistant_message_id, delta=assistant_message_with_tool_call.content)
            await self.event_bus.publish(_get_ag_ui_topic(text_content_event.type), text_content_event.model_dump(mode="json"))
        text_end_event = ag_ui_events.TextMessageEndEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_END, message_id=assistant_message_id)
        await self.event_bus.publish(_get_ag_ui_topic(text_end_event.type), text_end_event.model_dump(mode="json"))
        
        # 3. Publish events for the ToolCall itself
        tool_call_start_event = ag_ui_events.ToolCallStartEvent(
            type=ag_ui_events.EventType.TOOL_CALL_START,
            tool_call_id=tool_call.id,
            tool_name=tool_call.function.name, # type: ignore
            parent_message_id=assistant_message_id
        )
        await self.event_bus.publish(_get_ag_ui_topic(tool_call_start_event.type), tool_call_start_event.model_dump(mode="json"))
        
        # Stream arguments (even if empty JSON string for this tool)
        tool_call_args_event = ag_ui_events.ToolCallArgsEvent(type=ag_ui_events.EventType.TOOL_CALL_ARGS, tool_call_id=tool_call.id, delta=tool_call.function.arguments) # type: ignore
        await self.event_bus.publish(_get_ag_ui_topic(tool_call_args_event.type), tool_call_args_event.model_dump(mode="json"))
        
        tool_call_end_event = ag_ui_events.ToolCallEndEvent(type=ag_ui_events.EventType.TOOL_CALL_END, tool_call_id=tool_call.id)
        await self.event_bus.publish(_get_ag_ui_topic(tool_call_end_event.type), tool_call_end_event.model_dump(mode="json"))
        
        logger.info(f"MainAgent initiated tool call for '{tool_name}' (ID: {tool_call_id}), part of AssistantMessage (ID: {assistant_message_id}).")
        # The actual execution is now expected to be handled by ToolAgent via InternalExecuteToolRequest
        # or by app_core listening to ToolCallEndEvent and then publishing InternalExecuteToolRequest.

    # Required PocketFlow AsyncNode methods
    async def activate(self) -> None:
        """
        Called by AgentResolver. Sets up subscriptions for agent lifecycle.
        Actual message processing subscriptions happen on RunStartedEvent.
        """
        # Subscribing to RunStartedEvent to know when to expect messages for a new interaction
        await self.event_bus.subscribe(_get_ag_ui_topic(ag_ui_events.EventType.RUN_STARTED), self._handle_run_started_adapter)
        logger.info(f"MainDefaultAgent '{self.slug}' activate() called. Subscribed to RunStartedEvent.")
        # The internal AgentLifecycleEvent subscription is already done in __init__

    async def run(self, input_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        logger.debug(f"MainDefaultAgent '{self.slug}' run method called. Agent is event-driven via activate().")
        return {"status": f"{self.slug} is event-driven."}

    async def _process(self, item: Any = None, flow_state: Optional[Dict[str, Any]] = None) -> Any:
        logger.debug(f"MainDefaultAgent '{self.slug}' _process called. Logic is in event handlers.")
        return None