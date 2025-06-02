#%%
# pocket_commander/core_agents/tool_agent.py
from typing import List, Dict, Any, Optional
import logging # Added import

from pocket_commander.pocketflow.base import AsyncNode
from pocket_commander.types import AppServices
from pocket_commander.events import (
    AppInputEvent,
    AgentOutputEvent,
    AgentLifecycleEvent,
)
from pocket_commander.tools.registry import ToolRegistry
# Removed: from pocket_commander.utils.logging_utils import log_agent_event

class ToolAgent(AsyncNode):
    """
    An agent specialized for tool use, configured with a specific set of tools.
    """

    def __init__(self, app_services: AppServices, **init_args: Any):
        super().__init__()
        self.app_services = app_services
        self.slug: str = init_args.get("slug", "tool-agent")
        # Initialize logger after slug is defined
        self.logger = logging.getLogger(f"pocket_commander.agents.{self.slug}")
        self.llm_profile: Optional[str] = init_args.get("llm_profile")
        self.tool_names: List[str] = init_args.get("tool_names", [])
        
        self.agent_tool_registry = ToolRegistry() 
        if self.tool_names:
            self.logger.info(f"Configured with tools: {self.tool_names}")


        self.is_active = False

    async def _handle_app_input(self, event: AppInputEvent) -> None:
        if not self.is_active or event.target_agent_slug != self.slug:
            return

        self.logger.debug(f"Received AppInputEvent: {event.user_input}")
        user_input = event.user_input.strip()

        if user_input in self.tool_names:
            output_message = f"Attempting to use tool: {user_input}"
            self.logger.info(output_message)
            await self.app_services.event_bus.publish(
                AgentOutputEvent(message=output_message)
            )
        else:
            available_tools_str = ", ".join(self.tool_names) if self.tool_names else "No tools configured."
            help_message = (
                f"Unknown command: '{user_input}'. "
                f"Available tools for {self.slug}: {available_tools_str}"
            )
            self.logger.info(f"Sending help message: {help_message}")
            await self.app_services.event_bus.publish(
                AgentOutputEvent(message=help_message)
            )

    async def _handle_agent_lifecycle(self, event: AgentLifecycleEvent) -> None:
        if event.agent_name != self.slug:
            return

        if event.lifecycle_type == "activating":
            self.is_active = True
            self.app_services.event_bus.subscribe(AppInputEvent, self._handle_app_input)
            
            available_tools_str = ", ".join(self.tool_names) if self.tool_names else "No tools available."
            welcome_message = f"ToolAgent '{self.slug}' activated. Available tools: {available_tools_str}"
            self.logger.info(welcome_message)
            await self.app_services.event_bus.publish(
                AgentOutputEvent(message=welcome_message)
            )
        elif event.lifecycle_type == "deactivating":
            self.is_active = False
            self.app_services.event_bus.unsubscribe(AppInputEvent, self._handle_app_input)
            self.logger.info(f"ToolAgent '{self.slug}' deactivated.")
            # Optionally, publish a deactivation message
            # await self.app_services.event_bus.publish(
            #     AgentOutputEvent(message=f"ToolAgent '{self.slug}' deactivated.")
            # )

    async def activate(self) -> None:
        """Activates the agent, primarily subscribing to lifecycle events."""
        self.app_services.event_bus.subscribe(AgentLifecycleEvent, self._handle_agent_lifecycle)
        self.logger.info("ToolAgent initialized and subscribed to AgentLifecycleEvent.")

    async def run(self, input_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Main execution logic for the node. For ToolAgent, this might not be directly called
        if it's purely event-driven.
        """
        self.logger.debug("Run method called, but ToolAgent is primarily event-driven.")
        return None

    async def _process(self, input_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Core processing logic. For ToolAgent, input processing is handled via events.
        """
        self.logger.debug("_process called, but logic is in event handlers.")
        return None