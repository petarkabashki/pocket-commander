from typing import Literal, Optional
import uuid
from pydantic import Field

from pocket_commander.event_bus import BaseEvent

# Re-export all events from ag_ui.events for convenience.
# This makes pocket_commander.events the central place to import events from,
# whether they are ag_ui events or custom internal ones.
from pocket_commander.ag_ui.events import (
    EventType,
    BaseEvent as AgUiBaseEvent, # Alias to avoid conflict with local BaseEvent
    CustomEvent,
    Event as AgUiEventUnion, # The main Annotated Union of all ag_ui events
    MessagesSnapshotEvent,
    RawEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)


# --- Internal Application-Specific Events ---

class AppInputEvent(BaseEvent):
    """
    Event published by a UI client when the user submits input
    intended for the application or an agent.
    """
    input_text: str
    source_ui_client_id: Optional[str] = None # e.g., "terminal", "web_ui_session_xyz"
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class AgentLifecycleEvent(BaseEvent):
    """
    Event published by app_core when an agent's lifecycle state changes.
    This is an internal event for application logic, distinct from ag_ui run/step events.
    """
    agent_name: str  # The slug of the agent
    lifecycle_type: Literal["activating", "activated", "deactivating", "deactivated"]


class InternalExecuteToolRequest(BaseEvent):
    """
    Internal event to request the execution of a specific tool.
    """
    tool_call_id: str
    tool_name: str
    arguments_json: str
    parent_message_id: Optional[str] = None # Made Optional to align with ag_ui.ToolCallStartEvent


class RequestPromptEvent(BaseEvent):
    """
    Event published to request dedicated input from the user via a UI client.
    """
    prompt_message: str
    is_sensitive: bool = False  # e.g., for password input
    response_event_type: str # Expected event type for the response
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class PromptResponseEvent(BaseEvent):
    """
    Event published by a UI client in response to a RequestPromptEvent.
    """
    response_event_type: str # Should match the one in RequestPromptEvent
    correlation_id: str
    response_text: str


# Ensure all relevant events are easily accessible via pocket_commander.events
__all__ = [
    # pocket_commander.event_bus
    "BaseEvent",
    # pocket_commander.ag_ui.events
    "EventType",
    "AgUiBaseEvent",
    "CustomEvent",
    "AgUiEventUnion",
    "MessagesSnapshotEvent",
    "RawEvent",
    "RunErrorEvent",
    "RunFinishedEvent",
    "RunStartedEvent",
    "StateDeltaEvent",
    "StateSnapshotEvent",
    "StepFinishedEvent",
    "StepStartedEvent",
    "TextMessageContentEvent",
    "TextMessageEndEvent",
    "TextMessageStartEvent",
    "ToolCallArgsEvent",
    "ToolCallEndEvent",
    "ToolCallStartEvent",
    # Internal events
    "AppInputEvent",
    "InternalExecuteToolRequest",
    "AgentLifecycleEvent",
    "RequestPromptEvent", # Added
    "PromptResponseEvent", # Added
]