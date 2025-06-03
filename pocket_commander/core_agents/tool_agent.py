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
from pocket_commander.ag_ui import types as ag_ui_types # Not directly used for event construction, but for context
from pocket_commander.ag_ui import events as ag_ui_events
from pocket_commander.events import AgentLifecycleEvent, InternalExecuteToolRequest # Keep internal AgentLifecycleEvent

class ToolAgent(AsyncNode):
    """
    An agent specialized for executing tools based on InternalExecuteToolRequest events.
    It translates tool execution results into ag_ui.types.ToolMessage and publishes
    corresponding ag_ui.events using ZeroMQEventBus.
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

    async def _handle_internal_execute_tool_request(self, topic: str, event_data: dict) -> None:
        event = InternalExecuteToolRequest.model_validate(event_data)
        
        if not self.is_active:
            self.logger.debug(f"ToolAgent '{self.slug}' is not active, ignoring InternalExecuteToolRequest for tool '{event.tool_name}'.")
            return

        self.logger.info(f"Received InternalExecuteToolRequest (topic: {topic}) for tool '{event.tool_name}' (ID: {event.tool_call_id})")

        tool_result_content: str
        tool_message_id = str(uuid.uuid4()) # For the TextMessage stream representing the tool's output
        error_occurred = False

        # 1. Publish ToolCallStartEvent
        tool_call_start_event = ag_ui_events.ToolCallStartEvent(
            tool_call_id=event.tool_call_id,
            tool_call_name=event.tool_name,
            parent_message_id=event.parent_message_id # Assuming InternalExecuteToolRequest has this
        )
        await self.app_services.event_bus.publish(
            topic="ag_ui.tool_call.start",
            event_data=tool_call_start_event.model_dump(mode='json')
        )

        # 2. Publish ToolCallArgsEvent
        tool_call_args_event = ag_ui_events.ToolCallArgsEvent(
            tool_call_id=event.tool_call_id,
            delta=event.arguments_json if event.arguments_json else "{}"
        )
        await self.app_services.event_bus.publish(
            topic="ag_ui.tool_call.args",
            event_data=tool_call_args_event.model_dump(mode='json')
        )

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
            
            if hasattr(tool, 'execute_async') and callable(tool.execute_async):
                execution_result = await tool.execute_async(**arguments_dict)
            elif hasattr(tool, 'execute') and callable(tool.execute):
                execution_result = tool.execute(**arguments_dict) # type: ignore
            elif callable(tool):
                execution_result = await tool(**arguments_dict) if asyncio.iscoroutinefunction(tool) else tool(**arguments_dict)
            else:
                raise TypeError(f"Tool '{event.tool_name}' is not callable and lacks an 'execute' or 'execute_async' method.")

            tool_result_content = str(execution_result) 
            self.logger.info(f"Tool '{event.tool_name}' executed successfully. Result: {tool_result_content[:100]}...")

        except Exception as e:
            error_occurred = True
            self.logger.error(f"Error executing tool '{event.tool_name}': {e}", exc_info=True)
            tool_result_content = f"Error executing tool {event.tool_name}: {e}"
            
            # Publish RunErrorEvent
            run_error_event = ag_ui_events.RunErrorEvent(
                message=f"Error during execution of tool '{event.tool_name}' (ID: {event.tool_call_id}): {e}",
                code="TOOL_EXECUTION_ERROR"
            )
            await self.app_services.event_bus.publish(
                topic="ag_ui.run.error",
                event_data=run_error_event.model_dump(mode='json')
            )
        
        # 3. Publish TextMessage stream for the tool's output (result or error)
        # This represents the content of the ag_ui.types.ToolMessage
        text_msg_start_event = ag_ui_events.TextMessageStartEvent(
            message_id=tool_message_id, 
            role="tool", 
            tool_call_id=event.tool_call_id
        )
        await self.app_services.event_bus.publish(
            topic="ag_ui.text_message.start",
            event_data=text_msg_start_event.model_dump(mode='json')
        )
        
        if tool_result_content: 
            text_msg_content_event = ag_ui_events.TextMessageContentEvent(
                message_id=tool_message_id, 
                delta=tool_result_content
            )
            await self.app_services.event_bus.publish(
                topic="ag_ui.text_message.content",
                event_data=text_msg_content_event.model_dump(mode='json')
            )
            
        text_msg_end_event = ag_ui_events.TextMessageEndEvent(message_id=tool_message_id)
        await self.app_services.event_bus.publish(
            topic="ag_ui.text_message.end",
            event_data=text_msg_end_event.model_dump(mode='json')
        )
        self.logger.debug(f"Published TextMessage events for ToolMessage ID {tool_message_id} (Tool Call ID: {event.tool_call_id})")

        # 4. Publish ToolCallEndEvent
        tool_call_end_event = ag_ui_events.ToolCallEndEvent(tool_call_id=event.tool_call_id)
        await self.app_services.event_bus.publish(
            topic="ag_ui.tool_call.end",
            event_data=tool_call_end_event.model_dump(mode='json')
        )
        self.logger.debug(f"Published ToolCallEndEvent for Tool Call ID: {event.tool_call_id}")


    async def _handle_agent_lifecycle(self, topic: str, event_data: dict) -> None:
        event = AgentLifecycleEvent.model_validate(event_data)
        
        if event.agent_name != self.slug:
            return

        if event.lifecycle_type == "activating":
            if not self.is_active:
                self.is_active = True
                await self.app_services.event_bus.subscribe(
                    topic_pattern=InternalExecuteToolRequest.__name__, 
                    handler_coroutine=self._handle_internal_execute_tool_request
                )
                self.logger.info(f"ToolAgent '{self.slug}' activated and subscribed to InternalExecuteToolRequest topic '{InternalExecuteToolRequest.__name__}'.")
                
                activation_message_id = str(uuid.uuid4())
                start_event = ag_ui_events.TextMessageStartEvent(message_id=activation_message_id, role="system")
                await self.app_services.event_bus.publish(
                    topic="ag_ui.text_message.start", 
                    event_data=start_event.model_dump(mode='json')
                )
                content_event = ag_ui_events.TextMessageContentEvent(message_id=activation_message_id, delta=f"ToolAgent '{self.slug}' activated.")
                await self.app_services.event_bus.publish(
                    topic="ag_ui.text_message.content", 
                    event_data=content_event.model_dump(mode='json')
                )
                end_event = ag_ui_events.TextMessageEndEvent(message_id=activation_message_id)
                await self.app_services.event_bus.publish(
                    topic="ag_ui.text_message.end", 
                    event_data=end_event.model_dump(mode='json')
                )
            else:
                self.logger.debug(f"ToolAgent '{self.slug}' received 'activating' lifecycle event but was already active.")

        elif event.lifecycle_type == "deactivating":
            if self.is_active:
                self.is_active = False
                await self.app_services.event_bus.unsubscribe(
                    topic_pattern=InternalExecuteToolRequest.__name__, 
                    handler_coroutine=self._handle_internal_execute_tool_request
                )
                self.logger.info(f"ToolAgent '{self.slug}' deactivated and unsubscribed from InternalExecuteToolRequest topic '{InternalExecuteToolRequest.__name__}'.")
                
                deactivation_message_id = str(uuid.uuid4())
                start_event = ag_ui_events.TextMessageStartEvent(message_id=deactivation_message_id, role="system")
                await self.app_services.event_bus.publish(
                    topic="ag_ui.text_message.start", 
                    event_data=start_event.model_dump(mode='json')
                )
                content_event = ag_ui_events.TextMessageContentEvent(message_id=deactivation_message_id, delta=f"ToolAgent '{self.slug}' deactivated.")
                await self.app_services.event_bus.publish(
                    topic="ag_ui.text_message.content", 
                    event_data=content_event.model_dump(mode='json')
                )
                end_event = ag_ui_events.TextMessageEndEvent(message_id=deactivation_message_id)
                await self.app_services.event_bus.publish(
                    topic="ag_ui.text_message.end", 
                    event_data=end_event.model_dump(mode='json')
                )
            else:
                self.logger.debug(f"ToolAgent '{self.slug}' received 'deactivating' lifecycle event but was already inactive.")


    async def activate(self) -> None:
        """Activates the agent, primarily subscribing to lifecycle events."""
        await self.app_services.event_bus.subscribe(
            topic_pattern=AgentLifecycleEvent.__name__, 
            handler_coroutine=self._handle_agent_lifecycle
        )
        self.logger.info(f"ToolAgent '{self.slug}' subscribed to AgentLifecycleEvent topic '{AgentLifecycleEvent.__name__}'. Awaiting activation signal.")

    async def run(self, input_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Main execution logic for the node. For ToolAgent, this is primarily event-driven.
        The 'activate' method sets up event subscriptions.
        """
        self.logger.debug(f"Run method called for ToolAgent '{self.slug}'. Agent is event-driven via activate().")
        return None

    async def _process(self, item: Any = None, flow_state: Optional[Dict[str, Any]] = None) -> Any:
        """
        Core processing logic. For ToolAgent, actual work is in event handlers.
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