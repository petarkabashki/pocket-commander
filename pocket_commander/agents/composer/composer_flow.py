#%%
# pocket_commander/agents/composer/composer_flow.py
import uuid
from pocket_commander.zeromq_eventbus_poc import ZeroMQEventBus
from pocket_commander.ag_ui.events import (
    EventType,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
)
from pocket_commander.ag_ui.types import Role


class ComposerAgentFlow:
    def __init__(self, agent_config: dict, event_bus: ZeroMQEventBus):
        self.agent_config = agent_config
        self.event_bus = event_bus
        # self.logger = self.terminal_app.console # Logger would be set up differently if needed

        # Publish initialization message
        # This requires an async context to be called,
        # so this message might be better sent from an async setup method
        # or the caller after instantiation. For now, we'll assume it's handled
        # by making the instantiation context async or by a dedicated start method.
        # For simplicity in this refactor, we'll make a helper and call it.
        # However, __init__ itself cannot be async.
        # This implies that the initialization message should be sent by an async method.
        # Let's add an async method for initial message sending.

    async def send_initialization_message(self):
        init_message_text = f"Composer Agent Flow initialized. Config: {self.agent_config.get('description')}"
        message_id = str(uuid.uuid4())
        
        start_event = TextMessageStartEvent(
            message_id=message_id,
            role=Role.ASSISTANT, # Or Role.SYSTEM depending on convention
            type=EventType.TEXT_MESSAGE_START
        )
        await self.event_bus.publish(
            f"ag_ui.{EventType.TEXT_MESSAGE_START.value}",
            start_event.model_dump(mode="json")
        )

        content_event = TextMessageContentEvent(
            message_id=message_id,
            delta=init_message_text,
            type=EventType.TEXT_MESSAGE_CONTENT
        )
        await self.event_bus.publish(
            f"ag_ui.{EventType.TEXT_MESSAGE_CONTENT.value}",
            content_event.model_dump(mode="json")
        )

        end_event = TextMessageEndEvent(
            message_id=message_id,
            type=EventType.TEXT_MESSAGE_END
        )
        await self.event_bus.publish(
            f"ag_ui.{EventType.TEXT_MESSAGE_END.value}",
            end_event.model_dump(mode="json")
        )

    async def _publish_text_message(self, text: str, role: Role = Role.ASSISTANT):
        message_id = str(uuid.uuid4())
        start_event = TextMessageStartEvent(
            message_id=message_id,
            role=role,
            type=EventType.TEXT_MESSAGE_START
        )
        await self.event_bus.publish(
            f"ag_ui.{EventType.TEXT_MESSAGE_START.value}",
            start_event.model_dump(mode="json")
        )

        content_event = TextMessageContentEvent(
            message_id=message_id,
            delta=text,
            type=EventType.TEXT_MESSAGE_CONTENT
        )
        await self.event_bus.publish(
            f"ag_ui.{EventType.TEXT_MESSAGE_CONTENT.value}",
            content_event.model_dump(mode="json")
        )

        end_event = TextMessageEndEvent(
            message_id=message_id,
            type=EventType.TEXT_MESSAGE_END
        )
        await self.event_bus.publish(
            f"ag_ui.{EventType.TEXT_MESSAGE_END.value}",
            end_event.model_dump(mode="json")
        )

    async def handle_input(self, user_input: str):
        """
        Handles input for the composer agent.
        For this simple example, it just echoes the input.
        """
        echo_response = f"Composer Agent Echo: {user_input}"
        await self._publish_text_message(echo_response)
        
        # Example of using a specific LLM profile if needed later
        # llm_profile_name = self.agent_config.get("llm_profile", "default")
        # llm_message = f"LLM Profile for Composer Agent: {llm_profile_name}"
        # await self._publish_text_message(llm_message, role=Role.SYSTEM) # Example for system type message

def create_composer_flow(agent_config: dict, event_bus: ZeroMQEventBus) -> ComposerAgentFlow:
    """
    Factory function to create an instance of the ComposerAgentFlow.
    """
    flow = ComposerAgentFlow(agent_config, event_bus)
    # It's better if the caller handles calling send_initialization_message
    # in an async context, e.g., after creating the flow and starting the event loop.
    # asyncio.create_task(flow.send_initialization_message()) # This would be one way if called from async
    return flow