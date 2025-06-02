from typing import Optional, List, Literal, Any # Added Any for AbstractCommandInput placeholder if needed
from pydantic import BaseModel, Field # Added Field

from pocket_commander.event_bus import BaseEvent
# Assuming AbstractCommandInput is defined and importable from here:
from pocket_commander.commands.io import AbstractCommandInput
# CommandDefinition might not be needed directly in events if we are not sending them via events anymore.
# If an event needed to carry command definitions, it would be imported from pocket_commander.commands.definition

class AppInputEvent(BaseEvent):
    """
    Event published when the application receives input intended for an agent.
    """
    raw_text: str
    # The command_input provides more structured access to the input,
    # like command word, arguments string, etc.
    command_input: AbstractCommandInput

    class Config:
        arbitrary_types_allowed = True # For AbstractCommandInput if it's a Protocol


class AgentOutputEvent(BaseEvent):
    """
    Event published by an agent when it wants to send a message to the UI/user.
    """
    message: str
    style: Optional[str] = None # e.g., "error", "warning", "success", or rich markup


class AgentLifecycleEvent(BaseEvent):
    """
    Event published by app_core when an agent's lifecycle state changes.
    """
    agent_name: str # The slug of the agent
    lifecycle_type: Literal["activating", "activated", "deactivating", "deactivated"]
    # 'activating' is before on_enter, 'activated' is after on_enter
    # 'deactivating' is before on_exit, 'deactivated' is after on_exit


class RequestPromptEvent(BaseEvent):
    """
    Event published by an agent when it needs dedicated, single-line input from the user.
    """
    prompt_message: str # The message to display to the user for the prompt
    is_sensitive: bool = False # e.g., for password inputs, to hide typing
    
    # Used by the prompting mechanism to know what event type to publish back with the answer.
    # This allows the original requester to listen for a specific response.
    response_event_type: str 
    correlation_id: str # To match request with response


class PromptResponseEvent(BaseEvent):
    """
    Event published by the input mechanism in response to a RequestPromptEvent.
    """
    response_event_type: str # Should match the response_event_type from RequestPromptEvent
    correlation_id: str # Should match the correlation_id from RequestPromptEvent
    response_text: str   # The text input provided by the user

# Example of another potential event, if needed in future:
from enum import Enum
# from dataclasses import dataclass # Removed dataclass import

class SystemMessageType(Enum):
    INFO = "info"
    ERROR = "error"
    WARNING = "warning"
    SUCCESS = "success" # Added for more specific styling
    RAW = "raw" # For messages that should be printed as-is, without prefixes like "Error:"

# @dataclass # Removed @dataclass decorator
class SystemMessageEvent(BaseEvent): # Inherits from BaseEvent (Pydantic BaseModel)
    """
    Event published by core application components (like app_core or main)
    to display messages to the terminal.
    """
    message: str
    message_type: SystemMessageType = Field(default=SystemMessageType.INFO)
    details: Optional[str] = Field(default=None) # For error details, similar to send_error
    style: Optional[str] = Field(default=None) # Allow direct Rich style override if needed

# class AgentErrorEvent(BaseEvent):
#     """Event published by an agent when an unrecoverable error occurs within it."""
#     agent_name: str
#     error_message: str
#     details: Optional[str] = None