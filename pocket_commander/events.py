from typing import Literal, Optional, Any
import uuid
# import time # No longer needed here, inherited via InternalBaseEvent
from pydantic import Field

# Import InternalBaseEvent from its new location
from pocket_commander.ag_ui.types import InternalBaseEvent, ConfiguredBaseModel # ConfiguredBaseModel might not be needed if InternalBaseEvent handles it

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
# InternalBaseEvent is now defined in pocket_commander.ag_ui.types

class AppInputEvent(InternalBaseEvent):
    """
    Event published by a UI client when the user submits input
    intended for the application or an agent.
    """
    TOPIC: str = "app.ui.input" # AI! ADD CLASS ATTRIBUTE FOR TOPIC
    input_text: str
    source_ui_client_id: Optional[str] = None # e.g., "terminal", "web_ui_session_xyz"


class AgentLifecycleEvent(InternalBaseEvent):
    """
    Event published by app_core when an agent's lifecycle state changes.
    This is an internal event for application logic, distinct from ag_ui run/step events.
    """
    agent_name: str  # The slug of the agent
    lifecycle_type: Literal["activating", "activated", "deactivating", "deactivated"]


class InternalExecuteToolRequest(InternalBaseEvent):
    """
    Internal event to request the execution of a specific tool.
    """
    tool_call_id: str
    tool_name: str
    arguments_json: str
    parent_message_id: Optional[str] = None


class RequestPromptEvent(InternalBaseEvent):
    """
    Event published to request dedicated input from the user via a UI client.
    """
    prompt_message: str
    is_sensitive: bool = False  # e.g., for password input
    response_event_type: str # Expected event type for the response
    # Using str for correlation_id as it's for matching, not necessarily a UUID object
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class PromptResponseEvent(InternalBaseEvent):
    """
    Event published by a UI client in response to a RequestPromptEvent.
    """
    response_event_type: str # Should match the one in RequestPromptEvent
    correlation_id: str
    response_text: str


# Ensure all relevant events are easily accessible via pocket_commander.events
__all__ = [
    # pocket_commander.ag_ui.types
    "InternalBaseEvent",
    # pocket_commander.ag_ui.events
    "EventType",
    "AgUiBaseEvent", # This is pocket_commander.ag_ui.events.BaseEvent
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
    # Internal events (now inheriting from InternalBaseEvent via ag_ui.types)
    "AppInputEvent",
    "InternalExecuteToolRequest",
    "AgentLifecycleEvent",
    "RequestPromptEvent",
    "PromptResponseEvent",
]