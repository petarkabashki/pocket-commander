from abc import ABC, abstractmethod
from typing import Any, Optional
import uuid # For generating message IDs

from pocket_commander.types import AppServices
from pocket_commander.event_bus import ZeroMQEventBus
from pocket_commander.ag_ui import events as ag_ui_events
# from pocket_commander.ag_ui.types import Message # Not directly used now
from pocket_commander.events import AppInputEvent # Ensure this is the newly defined one

class AbstractAgUIClient(ABC):
    def __init__(self, app_services: AppServices, client_id: str = "default_ui_client"):
        self.app_services: AppServices = app_services
        self._event_bus: ZeroMQEventBus = app_services.event_bus
        self.client_id: str = client_id

    @property
    def event_bus(self) -> ZeroMQEventBus:
        return self._event_bus

    @abstractmethod
    async def initialize(self) -> None:
        """Initializes the client, subscribes to necessary events."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Starts the client's main interaction loop."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stops the client and cleans up resources."""
        pass

    @abstractmethod
    async def handle_ag_ui_event(self, event: ag_ui_events.Event) -> None:
        """
        Processes and renders an ag_ui event from the agent/system.
        This method will likely be called by specific event handlers
        registered with the event bus by the concrete client.
        """
        pass

    async def send_app_input(self, raw_input: str) -> None:
        """Sends user input to the application core/agents."""
        event = AppInputEvent(
            input_text=raw_input,
            source_ui_client_id=self.client_id
        )
        await self.event_bus.publish(event)
        # Also publish the user's input as ag_ui message events for history
        await self._publish_user_message_as_ag_ui_events(raw_input)

    async def _publish_user_message_as_ag_ui_events(self, user_input: str) -> None:
        """
        Helper to publish user input as a series of ag_ui text events
        (TextMessageStart, TextMessageContent, TextMessageEnd) with role 'user'.
        """
        message_id = str(uuid.uuid4())
        
        start_event = ag_ui_events.TextMessageStartEvent(
            type=ag_ui_events.EventType.TEXT_MESSAGE_START,
            message_id=message_id,
            role="user" # type: ignore # Pydantic literal validation handles this
        )
        await self.event_bus.publish(start_event)

        if user_input: # Ensure delta is not empty for TextMessageContentEvent
            content_event = ag_ui_events.TextMessageContentEvent(
                type=ag_ui_events.EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=user_input
            )
            await self.event_bus.publish(content_event)

        end_event = ag_ui_events.TextMessageEndEvent(
            type=ag_ui_events.EventType.TEXT_MESSAGE_END,
            message_id=message_id
        )
        await self.event_bus.publish(end_event)

    @abstractmethod
    async def request_dedicated_input(self, prompt_message: str, is_sensitive: bool = False) -> str:
        """Requests a single line of dedicated input from the user."""
        pass