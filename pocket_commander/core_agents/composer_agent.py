#%%
# pocket_commander/core_agents/composer_agent.py
import asyncio
import logging
import uuid # For message IDs
from typing import Dict, Any, Optional

from pocket_commander.pocketflow.base import AsyncNode
from pocket_commander.types import AppServices
from pocket_commander.zeromq_event_bus import ZeroMQEventBus # AI! Change to ZeroMQEventBus from pocket_commander.event_bus
# Updated event imports
from pocket_commander.events import AgentLifecycleEvent # AI! AppInputEvent removed as it's not directly used for subscription
from pocket_commander.ag_ui import events as ag_ui_events
from pocket_commander.ag_ui import types as ag_ui_types

logger = logging.getLogger(__name__)

class ComposerAgent(AsyncNode):
    """
    Agent for composing complex prompts or documents.
    Interacts via the event bus using ag_ui events.
    """

    def __init__(self, app_services: AppServices, **init_args: Any):
        super().__init__()
        self.app_services = app_services
        self.event_bus: ZeroMQEventBus = app_services.event_bus
        self.init_args = init_args
        
        self.slug: str = init_args.get("slug", "composer")
        self.llm_profile: Optional[str] = init_args.get("llm_profile")
        self.style_guide: Optional[str] = init_args.get("style_guide")
        
        self._is_active = False
        self._current_run_id: Optional[str] = None # To associate messages with a run
        self._message_history: list[ag_ui_types.Message] = []


        logger.info(f"ComposerAgent '{self.slug}' initialized with "
                    f"llm_profile='{self.llm_profile}', style_guide='{self.style_guide}'. "
                    f"Full init_args: {init_args}")

    async def _publish_text_message(self, content: str, role: ag_ui_types.Role = "assistant", parent_message_id: Optional[str] = None) -> str:
        """Helper to publish a complete text message sequence using ag_ui.events."""
        message_id = str(uuid.uuid4())
        
        # Create the message object for internal history (optional, but good practice)
        # common_message_args = {"id": message_id, "role": role, "content": content}
        # if role == "assistant":
        #     new_message = ag_ui_types.AssistantMessage(**common_message_args)
        # elif role == "user": # Should not happen from agent publishing
        #     new_message = ag_ui_types.UserMessage(**common_message_args)
        # else: # system, developer etc.
        #     new_message = ag_ui_types.BaseMessage(**common_message_args) # Or more specific if needed
        # self._message_history.append(new_message)

        start_event = ag_ui_events.TextMessageStartEvent(message_id=message_id, role=role, parent_message_id=parent_message_id) # AI! Add parent_message_id
        await self.event_bus.publish(topic="ag_ui.text_message.start", event_data=start_event.model_dump(mode='json'))
        
        if content:
            content_event = ag_ui_events.TextMessageContentEvent(message_id=message_id, delta=content)
            await self.event_bus.publish(topic="ag_ui.text_message.content", event_data=content_event.model_dump(mode='json'))
        
        end_event = ag_ui_events.TextMessageEndEvent(message_id=message_id)
        await self.event_bus.publish(topic="ag_ui.text_message.end", event_data=end_event.model_dump(mode='json'))
        
        logger.debug(f"ComposerAgent '{self.slug}' published '{role}' message (ID: {message_id}): {content[:50]}...")
        return message_id

    async def _subscribe_to_events(self):
        """Subscribes to necessary events. Called upon activation."""
        if self.event_bus:
            # ComposerAgent now expects RunStartedEvent and MessagesSnapshotEvent like MainDefaultAgent
            await self.event_bus.subscribe(topic_pattern="ag_ui.run.started", handler_coroutine=self.handle_run_started)
            await self.event_bus.subscribe(topic_pattern="AgentLifecycleEvent", handler_coroutine=self.handle_lifecycle_event)
            logger.info(f"ComposerAgent '{self.slug}' subscribed to 'ag_ui.run.started' and 'AgentLifecycleEvent'.")
        else:
            logger.error(f"ComposerAgent '{self.slug}': Event bus not available for subscriptions.")

    async def handle_lifecycle_event(self, topic: str, event_data: dict): # AI! Add topic: str, event_data: dict
        event = AgentLifecycleEvent.model_validate(event_data) # AI! Reconstruct event
        if event.agent_name == self.slug:
            if event.lifecycle_type == "activating" and not self._is_active:
                await self.on_agent_activate()
            elif event.lifecycle_type == "deactivating" and self._is_active:
                await self.on_agent_deactivate()

    async def on_agent_activate(self):
        """Logic to run when this agent becomes active."""
        await self._subscribe_to_events() # Subscriptions moved here
        self._is_active = True
        logger.info(f"ComposerAgent '{self.slug}' activated.")
        await self._publish_text_message(
            content=f"Composer Agent '{self.slug}' activated. Ready to compose."
        )

    async def on_agent_deactivate(self):
        """Logic to run when this agent is being deactivated."""
        self._is_active = False
        if self._current_run_id:
            finish_event = ag_ui_events.RunFinishedEvent(thread_id=self.slug, run_id=self._current_run_id) # AI! thread_id is slug
            await self.event_bus.publish(topic="ag_ui.run.finished", event_data=finish_event.model_dump(mode='json'))
            self._current_run_id = None
        
        if self.event_bus:
            # AI! Update unsubscriptions to use topic strings
            await self.event_bus.unsubscribe(topic_pattern="ag_ui.run.started", handler_coroutine=self.handle_run_started)
            await self.event_bus.unsubscribe(topic_pattern="ag_ui.messages.snapshot", handler_coroutine=self.handle_message_snapshot)
        logger.info(f"ComposerAgent '{self.slug}' deactivated and unsubscribed from run/message events.")

    async def handle_run_started(self, topic: str, event_data: dict): # AI! Add topic: str, event_data: dict
        event = ag_ui_events.RunStartedEvent.model_validate(event_data) # AI! Reconstruct event
        if not self._is_active:
            return
        # AI! Filter by thread_id if it's meant for this agent instance or a general broadcast
        if event.thread_id != self.slug and event.thread_id is not None: # Assuming None thread_id is broadcast or handled by another mechanism
             logger.debug(f"ComposerAgent '{self.slug}' ignoring RunStartedEvent for thread_id '{event.thread_id}'")
             return

        self._current_run_id = event.run_id
        self._message_history = []
        logger.info(f"ComposerAgent '{self.slug}' received RunStartedEvent (ID: {event.run_id}, Thread: {event.thread_id}). Subscribing to MessagesSnapshotEvent.")
        await self.event_bus.subscribe(topic_pattern="ag_ui.messages.snapshot", handler_coroutine=self.handle_message_snapshot)

    async def handle_message_snapshot(self, topic: str, event_data: dict): # AI! Add topic: str, event_data: dict
        """Handles snapshot of messages, typically containing user input."""
        event = ag_ui_events.MessagesSnapshotEvent.model_validate(event_data) # AI! Reconstruct event
        if not self._is_active or not self._current_run_id:
            return
        
        # AI! Filter by thread_id if it's meant for this agent instance
        if event.thread_id != self.slug:
            logger.debug(f"ComposerAgent '{self.slug}' ignoring MessagesSnapshotEvent for thread_id '{event.thread_id}'")
            return

        self._message_history.extend(event.messages)
        last_message = event.messages[-1] if event.messages else None

        if last_message and last_message.role == "user" and isinstance(last_message.content, str):
            raw_text = last_message.content.strip()
            logger.debug(f"ComposerAgent '{self.slug}' received input: '{raw_text}' for run_id: {self._current_run_id}")

            if raw_text.lower() == "help":
                await self._do_help(parent_message_id=last_message.id)
            else:
                response_message = f"Composer agent '{self.slug}' received: {raw_text}"
                await self._publish_text_message(content=response_message, parent_message_id=last_message.id)
        
        if self._current_run_id: # AI! Check current_run_id before publishing RunFinishedEvent
            finish_event = ag_ui_events.RunFinishedEvent(thread_id=self.slug, run_id=self._current_run_id) # AI! thread_id is slug
            await self.event_bus.publish(topic="ag_ui.run.finished", event_data=finish_event.model_dump(mode='json'))
            await self.event_bus.unsubscribe(topic_pattern="ag_ui.messages.snapshot", handler_coroutine=self.handle_message_snapshot)
            logger.info(f"ComposerAgent '{self.slug}' finished run {self._current_run_id} and unsubscribed from MessagesSnapshotEvent.")
            self._current_run_id = None


    async def _do_help(self, parent_message_id: Optional[str] = None):
        help_text = f"""--- {self.slug} Agent Help ---
The Composer Agent is responsible for composing complex prompts or documents.
Currently, it will echo any input received.
Configuration:
  LLM Profile: {self.llm_profile}
  Style Guide: {self.style_guide}

Global commands (start with /) are handled by the application core.
"""
        await self._publish_text_message(content=help_text, parent_message_id=parent_message_id)

    # Required PocketFlow AsyncNode methods
    async def activate(self) -> None: # PocketFlow's activate, distinct from on_agent_activate
        """Called by AgentResolver. Sets up subscriptions for agent lifecycle."""
        # The internal AgentLifecycleEvent subscription is now done in __init__ or on_agent_activate
        # For PocketFlow, this activate is for the node itself.
        # We'll ensure event subscriptions are ready.
        if not self._is_active: # If not already activated by lifecycle event
             # AI! Ensure AgentLifecycleEvent subscription is made if not already active
             # This might be redundant if on_agent_activate is always called first by an external AgentLifecycleEvent
             # However, keeping it ensures the node can be activated independently by PocketFlow if needed.
             await self.event_bus.subscribe(topic_pattern="AgentLifecycleEvent", handler_coroutine=self.handle_lifecycle_event)
        logger.info(f"ComposerAgent '{self.slug}' (PocketFlow) activate() called.")


    async def run(self, input_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        logger.debug(f"ComposerAgent '{self.slug}' run method called. Agent is event-driven.")
        return {"status": f"{self.slug} is event-driven."}

    async def _process(self, item: Any = None, flow_state: Optional[Dict[str, Any]] = None) -> Any:
        logger.debug(f"ComposerAgent '{self.slug}' _process called. Logic is in event handlers.")
        return None