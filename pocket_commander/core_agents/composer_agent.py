#%%
# pocket_commander/core_agents/composer_agent.py
import asyncio
import logging
from typing import Dict, Any, Optional

from pocket_commander.pocketflow.base import AsyncNode
from pocket_commander.types import AppServices
from pocket_commander.event_bus import AsyncEventBus
from pocket_commander.events import AppInputEvent, AgentOutputEvent, AgentLifecycleEvent

logger = logging.getLogger(__name__)

class ComposerAgent(AsyncNode):
    """
    Agent for composing complex prompts or documents.
    Interacts via the event bus.
    """

    def __init__(self, app_services: AppServices, **init_args: Any):
        super().__init__()  # PocketFlow.AsyncNode init
        self.app_services = app_services
        self.event_bus: AsyncEventBus = app_services.event_bus
        self.init_args = init_args
        
        self.slug: str = init_args.get("slug", "composer")
        self.llm_profile: Optional[str] = init_args.get("llm_profile")
        self.style_guide: Optional[str] = init_args.get("style_guide")
        
        self._is_active = False  # Track activation state
        
        logger.info(f"ComposerAgent '{self.slug}' initialized with "
                    f"llm_profile='{self.llm_profile}', style_guide='{self.style_guide}'. "
                    f"Full init_args: {init_args}")

    async def _subscribe_to_events(self):
        """Subscribes to necessary events. Called upon activation."""
        if self.event_bus:
            await self.event_bus.subscribe(AppInputEvent, self.handle_app_input) # type: ignore
            await self.event_bus.subscribe(AgentLifecycleEvent, self.handle_lifecycle_event) # type: ignore
            logger.info(f"ComposerAgent '{self.slug}' subscribed to AppInputEvent and AgentLifecycleEvent.")
        else:
            logger.error(f"ComposerAgent '{self.slug}': Event bus not available for subscriptions.")

    async def handle_lifecycle_event(self, event: AgentLifecycleEvent):
        if event.agent_name == self.slug:
            if event.lifecycle_type == "activating" and not self._is_active:
                await self.on_agent_activate()
            elif event.lifecycle_type == "deactivating" and self._is_active:
                await self.on_agent_deactivate()

    async def on_agent_activate(self):
        """Logic to run when this agent becomes active."""
        await self._subscribe_to_events()
        self._is_active = True
        logger.info(f"ComposerAgent '{self.slug}' activated.")
        await self.event_bus.publish(
            AgentOutputEvent(
                message=f"Composer Agent '{self.slug}' activated. Ready to compose.",
                style="bold green"
            )
        )

    async def on_agent_deactivate(self):
        """Logic to run when this agent is being deactivated."""
        self._is_active = False
        logger.info(f"ComposerAgent '{self.slug}' deactivated.")
        # Consider unsubscription if event_bus supports it and it's necessary

    async def handle_app_input(self, event: AppInputEvent):
        """Handles raw input directed to this agent."""
        if not self._is_active:  # Only process if active
            return

        raw_text = event.raw_text.strip()
        logger.debug(f"ComposerAgent '{self.slug}' received input: '{raw_text}'")

        # For now, simply echo the input, similar to the old composer_flow.py
        # Future: Implement actual composition logic, potentially using self.llm_profile and self.style_guide
        if raw_text.lower() == "help":
            await self._do_help()
        else:
            response_message = f"Composer agent '{self.slug}' received: {raw_text}"
            await self.event_bus.publish(
                AgentOutputEvent(
                    message=response_message,
                    style="italic cyan"
                )
            )

    async def _do_help(self):
        help_text = f"""--- {self.slug} Agent Help ---
The Composer Agent is responsible for composing complex prompts or documents.
Currently, it will echo any input received.
Configuration:
  LLM Profile: {self.llm_profile}
  Style Guide: {self.style_guide}

Future commands will be defined here.
"""
        await self.event_bus.publish(AgentOutputEvent(message=help_text, style=None))

    # Required PocketFlow AsyncNode methods
    async def prep_async(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug(f"ComposerAgent '{self.slug}' prep_async called.")
        # No specific prep needed for this event-driven agent yet
        return shared

    async def exec_async(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug(f"ComposerAgent '{self.slug}' exec_async called.")
        # Core logic is event-driven via handle_app_input
        return {"status": f"{self.slug} is event-driven; exec_async is a placeholder."}

    async def post_async(self, shared: Dict[str, Any], prep_res: Dict[str, Any], exec_res: Dict[str, Any]) -> Optional[str]:
        logger.debug(f"ComposerAgent '{self.slug}' post_async called.")
        # No specific post-processing needed for this event-driven agent yet
        return None