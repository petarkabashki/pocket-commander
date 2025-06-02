#%%
# pocket_commander/core_agents/tool_agent.py
import asyncio
import json
import logging
import uuid
from typing import List, Dict, Any, Optional

from pocket_commander.pocketflow.base import AsyncNode
from pocket_commander.types import AppServices
from pocket_commander.tools.registry import ToolRegistry
from pocket_commander.ag_ui import types as ag_ui_types
from pocket_commander.ag_ui import events as ag_ui_events
from pocket_commander.events import AgentLifecycleEvent, InternalExecuteToolRequest # Keep internal AgentLifecycleEvent

class ToolAgent(AsyncNode):
    """
    An agent specialized for executing tools based on InternalExecuteToolRequest events.
    It translates tool execution results into ag_ui.types.ToolMessage and publishes
    corresponding ag_ui.events.
    """

    def __init__(self, app_services: AppServices, **init_args: Any):
        super().__init__()
        self.app_services = app_services
        self.slug: str = init_args.get("slug", "tool-agent")
        self.logger = logging.getLogger(f"pocket_commander.agents.{self.slug}")
        
        # ToolAgent uses the global tool registry from AppServices
        self.global_tool_registry: ToolRegistry = self.app_services.global_tool_registry
        
        self.is_active = False
        self.logger.info(f"ToolAgent '{self.slug}' initialized.")

    async def _handle_internal_execute_tool_request(self, event: InternalExecuteToolRequest) -> None:
        if not self.is_active:
            self.logger.debug(f"ToolAgent '{self.slug}' is not active, ignoring InternalExecuteToolRequest for tool '{event.tool_name}'.")
            return

        self.logger.info(f"Received InternalExecuteToolRequest for tool '{event.tool_name}' (ID: {event.tool_call_id})")

        tool_result_content: str
        tool_message_id = str(uuid.uuid4())

        try:
            tool = self.global_tool_registry.get_tool(event.tool_name)
            if not tool:
                raise ValueError(f"Tool '{event.tool_name}' not found in the global registry.")

            arguments_dict: Dict[str, Any] = {}
            if event.arguments_json:
                try:
                    arguments_dict = json.loads(event.arguments_json)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Failed to parse arguments JSON for tool '{event.tool_name}': {e}")
            
            self.logger.debug(f"Executing tool '{event.tool_name}' with arguments: {arguments_dict}")
            
            # Assuming tools have an 'execute' method or are callable
            # The actual execution might need to be async if tools are I/O bound
            # For now, direct call for simplicity, adapt if tools are async
            if hasattr(tool, 'execute_async') and callable(tool.execute_async):
                execution_result = await tool.execute_async(**arguments_dict)
            elif hasattr(tool, 'execute') and callable(tool.execute):
                execution_result = tool.execute(**arguments_dict) # type: ignore
            else:
                # Fallback for callable tools (e.g. functions registered directly)
                # This might need adjustment based on how tools are actually structured/registered
                if callable(tool):
                    execution_result = await tool(**arguments_dict) if asyncio.iscoroutinefunction(tool) else tool(**arguments_dict)
                else:
                    raise TypeError(f"Tool '{event.tool_name}' is not callable and lacks an 'execute' or 'execute_async' method.")


            tool_result_content = str(execution_result) # Ensure result is string
            self.logger.info(f"Tool '{event.tool_name}' executed successfully. Result: {tool_result_content[:100]}...")

        except Exception as e:
            self.logger.error(f"Error executing tool '{event.tool_name}': {e}", exc_info=True)
            tool_result_content = f"Error executing tool {event.tool_name}: {e}"
        
        # Construct ag_ui.types.ToolMessage (though we don't directly send this object,
        # its structure guides the events we publish)
        # tool_message = ag_ui_types.ToolMessage(
        #     id=tool_message_id,
        #     role="tool",
        #     tool_call_id=event.tool_call_id,
        #     content=tool_result_content,
        #     # name=event.tool_name # ag_ui.types.ToolMessage does not have a 'name' field directly
        # )

        # Publish events to stream the ToolMessage
        await self.app_services.event_bus.publish(
            ag_ui_events.TextMessageStartEvent(message_id=tool_message_id, role="tool", tool_call_id=event.tool_call_id)
        )
        # For simplicity, sending content in one chunk. Could be chunked if very large.
        if tool_result_content: # Only send content event if there is content
            await self.app_services.event_bus.publish(
                ag_ui_events.TextMessageContentEvent(message_id=tool_message_id, delta=tool_result_content)
            )
        await self.app_services.event_bus.publish(
            ag_ui_events.TextMessageEndEvent(message_id=tool_message_id)
        )
        self.logger.debug(f"Published TextMessage events for ToolMessage ID {tool_message_id} (Tool Call ID: {event.tool_call_id})")


    async def _handle_agent_lifecycle(self, event: AgentLifecycleEvent) -> None:
        if event.agent_name != self.slug:
            return

        if event.lifecycle_type == "activating":
            if not self.is_active:
                self.is_active = True
                self.app_services.event_bus.subscribe(InternalExecuteToolRequest, self._handle_internal_execute_tool_request)
                self.logger.info(f"ToolAgent '{self.slug}' activated and subscribed to InternalExecuteToolRequest.")
                
                # Optionally, publish a system message indicating activation
                activation_message_id = str(uuid.uuid4())
                await self.app_services.event_bus.publish(
                    ag_ui_events.TextMessageStartEvent(message_id=activation_message_id, role="system")
                )
                await self.app_services.event_bus.publish(
                    ag_ui_events.TextMessageContentEvent(message_id=activation_message_id, delta=f"ToolAgent '{self.slug}' activated.")
                )
                await self.app_services.event_bus.publish(
                    ag_ui_events.TextMessageEndEvent(message_id=activation_message_id)
                )
            else:
                self.logger.debug(f"ToolAgent '{self.slug}' received 'activating' lifecycle event but was already active.")

        elif event.lifecycle_type == "deactivating":
            if self.is_active:
                self.is_active = False
                self.app_services.event_bus.unsubscribe(InternalExecuteToolRequest, self._handle_internal_execute_tool_request)
                self.logger.info(f"ToolAgent '{self.slug}' deactivated and unsubscribed from InternalExecuteToolRequest.")
                # Optionally, publish a deactivation message
                deactivation_message_id = str(uuid.uuid4())
                await self.app_services.event_bus.publish(
                    ag_ui_events.TextMessageStartEvent(message_id=deactivation_message_id, role="system")
                )
                await self.app_services.event_bus.publish(
                    ag_ui_events.TextMessageContentEvent(message_id=deactivation_message_id, delta=f"ToolAgent '{self.slug}' deactivated.")
                )
                await self.app_services.event_bus.publish(
                    ag_ui_events.TextMessageEndEvent(message_id=deactivation_message_id)
                )
            else:
                self.logger.debug(f"ToolAgent '{self.slug}' received 'deactivating' lifecycle event but was already inactive.")


    async def activate(self) -> None:
        """Activates the agent, primarily subscribing to lifecycle events."""
        self.app_services.event_bus.subscribe(AgentLifecycleEvent, self._handle_agent_lifecycle)
        self.logger.info(f"ToolAgent '{self.slug}' subscribed to AgentLifecycleEvent. Awaiting activation signal.")

    async def run(self, input_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Main execution logic for the node. For ToolAgent, this is primarily event-driven.
        The 'activate' method sets up event subscriptions.
        """
        self.logger.debug(f"Run method called for ToolAgent '{self.slug}'. Agent is event-driven via activate().")
        # Ensure activate has been called if this node is part of a flow that auto-runs
        # However, standard activation is via app_core publishing AgentLifecycleEvent
        return None

    async def _process(self, item: Any = None, flow_state: Optional[Dict[str, Any]] = None) -> Any:
        """
        Core processing logic. For ToolAgent, actual work is in event handlers.
        This method might be called if the node is used in a PocketFlow sequence directly,
        but its primary operation is event-based.
        """
        self.logger.debug(f"_process called for ToolAgent '{self.slug}', but logic is in event handlers.")
        return None

# Example of how to register this agent in pocket_commander.conf.yaml:
# agents:
#   - slug: "tool_executor" # Or just "tool_agent"
#     path: "pocket_commander.core_agents.tool_agent"
#     class_name: "ToolAgent"
#     description: "Handles execution of tools requested by other agents."
#     init_args: {} # No specific init_args needed beyond AppServices for this version