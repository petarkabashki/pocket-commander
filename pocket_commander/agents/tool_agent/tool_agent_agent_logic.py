# pocket_commander/agents/tool_agent/tool_agent_agent_logic.py
import asyncio
import copy
import logging
import json
import uuid
import functools
from typing import Any, Dict, Tuple, List, Callable, Awaitable, Optional

from ...pocketflow import AsyncFlow, AsyncFlowManager
from ...nodes.initial_query_node import InitialQueryNode
from ...nodes.tool_enabled_llm_node import ToolEnabledLLMNode
from ...nodes.print_final_answer_node import PrintFinalAnswerNode
from ...commands.core import CommandContext
from ...commands.definition import CommandDefinition
from ...types import AppServices  # Assumed to be updated with event_bus and tool_registry
from ...commands.io import AbstractCommandInput

# Event Bus and Event related imports
from ...zeromq_eventbus_poc import ZeroMQEventBus
from ...events import (
    InternalExecuteToolRequest,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallEndEvent,  # ag_ui event
    EventType,
    AG_UI_EVENT_PREFIX,
    # ToolCallResultEvent, ToolCallErrorEvent are NOT defined as Pydantic models in events.py
    # This implementation will use dicts for them as per interpretation of the prompt.
)
from ...ag_ui.types import Role
from ...tools.registry import ToolRegistry # For type hint, assuming it's in app_services

logger = logging.getLogger(__name__)

def _create_tool_agent_pocket_flow(app_services: AppServices, agent_config: Dict[str, Any]):
    # Ensure event_bus is in app_services, otherwise this will fail.
    event_bus: ZeroMQEventBus = app_services['event_bus']

    initial_query = InitialQueryNode()
    # ToolEnabledLLMNode and PrintFinalAnswerNode are expected to be modified
    # to accept event_bus instead of output_handler for their publishing needs.
    llm_agent = ToolEnabledLLMNode(
        event_bus=event_bus,  # Pass event_bus
        max_retries=agent_config.get("max_retries", 2),
        wait=agent_config.get("retry_wait", 1)
    )
    
    final_answer_printer = PrintFinalAnswerNode(
        event_bus=event_bus,  # Pass event_bus
        # prints_directly=True # This flag's relevance changes with event_bus.
                               # Node should publish events instead of printing.
    )

    initial_query >> llm_agent
    llm_agent - "llm_decide_next" >> llm_agent
    llm_agent - "answer_provided" >> final_answer_printer
    llm_agent - "error" >> final_answer_printer

    return AsyncFlow(start=initial_query)

async def _tool_agent_input_handler(
    context: CommandContext,
    app_services_closure: AppServices,
    agent_config_closure: Dict[str, Any],
    agent_pocket_flow_closure: AsyncFlow
):
    user_input = context.input._raw_input_str
    event_bus: ZeroMQEventBus = app_services_closure['event_bus']

    shared_data_template = {
        "query": None,
        "context": agent_config_closure.get("initial_context", ""), 
        "messages": [],
        "final_answer": None,
        "tool_result": None,
    }
    current_shared_data = copy.deepcopy(shared_data_template)
    current_shared_data["query"] = user_input 

    flow_manager = AsyncFlowManager(agent_pocket_flow_closure)
    
    try:
        await flow_manager.run(current_shared_data) 
    except Exception as e:
        logger.error(f"Error in Tool Agent's PocketFlow execution: {e}", exc_info=True)
        error_message = "An error occurred while processing your request in the Tool Agent."
        # RunErrorEvent requires: message: str, code: Optional[str]
        # It inherits event_id, timestamp, topic from BaseEvent -> InternalBaseEvent
        run_error_event = RunErrorEvent(message=error_message, code="TOOL_AGENT_POCKETFLOW_FAILURE")
        await event_bus.publish(
            topic=f"{AG_UI_EVENT_PREFIX}.{EventType.RUN_ERROR.value}",
            event_data=run_error_event.model_dump(mode="json")
        )

async def _handle_internal_execute_tool_request(
    event: InternalExecuteToolRequest,
    app_services: AppServices
):
    logger.info(f"ToolAgentLogic handling InternalExecuteToolRequest for tool: {event.tool_name} (ID: {event.tool_call_id})")
    event_bus: ZeroMQEventBus = app_services['event_bus']
    tool_registry: Optional[ToolRegistry] = app_services.get('tool_registry')

    if not tool_registry:
        logger.error("ToolRegistry not found in app_services for ToolAgentLogic's tool execution.")
        # Publish conceptual ToolCallErrorEvent
        error_payload = {
            "type": "ToolCallErrorEvent", # Conceptual, not a defined Pydantic model in events.py
            "tool_call_id": event.tool_call_id,
            "error_message": "ToolRegistry not available for tool execution.",
            "parent_message_id": event.parent_message_id,
        }
        await event_bus.publish(
            topic=f"tool_agent.tool_execution.error.{event.tool_call_id}", 
            event_data=error_payload
        )
        return

    tool_def = tool_registry.get_tool(event.tool_name)
    if not tool_def:
        logger.error(f"Tool '{event.tool_name}' not found in registry by ToolAgentLogic.")
        error_payload = {
            "type": "ToolCallErrorEvent",
            "tool_call_id": event.tool_call_id,
            "error_message": f"Tool '{event.tool_name}' not found in registry.",
            "parent_message_id": event.parent_message_id,
        }
        await event_bus.publish(
            topic=f"tool_agent.tool_execution.error.{event.tool_call_id}",
            event_data=error_payload
        )
        return

    try:
        tool_args_dict = json.loads(event.arguments_json)
        
        if asyncio.iscoroutinefunction(tool_def.func):
            tool_output = await tool_def.func(**tool_args_dict)
        else:
            loop = asyncio.get_running_loop()
            tool_output = await loop.run_in_executor(None, functools.partial(tool_def.func, **tool_args_dict))


        logger.info(f"Tool '{event.tool_name}' (ID: {event.tool_call_id}) executed successfully by ToolAgentLogic.")

        # Publish conceptual ToolCallResultEvent
        result_payload = {
            "type": "ToolCallResultEvent", # Conceptual
            "tool_call_id": event.tool_call_id,
            "result_json": json.dumps(tool_output), 
            "parent_message_id": event.parent_message_id,
        }
        await event_bus.publish(
            topic=f"tool_agent.tool_execution.result.{event.tool_call_id}",
            event_data=result_payload
        )

        # Publish ag_ui.ToolCallEndEvent as per prompt's event list for ToolAgent
        ag_ui_tool_end_event = ToolCallEndEvent(tool_call_id=event.tool_call_id)
        await event_bus.publish(
            topic=f"{AG_UI_EVENT_PREFIX}.{EventType.TOOL_CALL_END.value}",
            event_data=ag_ui_tool_end_event.model_dump(mode="json")
        )

    except json.JSONDecodeError as je:
        logger.error(f"Failed to decode arguments_json for tool '{event.tool_name}' (ID: {event.tool_call_id}): {je}", exc_info=True)
        error_payload = {
            "type": "ToolCallErrorEvent",
            "tool_call_id": event.tool_call_id,
            "error_message": f"Invalid arguments format for tool '{event.tool_name}': {je}",
            "parent_message_id": event.parent_message_id,
        }
        await event_bus.publish(
            topic=f"tool_agent.tool_execution.error.{event.tool_call_id}",
            event_data=error_payload
        )
    except Exception as e:
        logger.error(f"Error executing tool '{event.tool_name}' (ID: {event.tool_call_id}) via ToolAgentLogic: {e}", exc_info=True)
        error_payload = {
            "type": "ToolCallErrorEvent",
            "tool_call_id": event.tool_call_id,
            "error_message": f"Execution error in tool '{event.tool_name}': {str(e)}",
            "parent_message_id": event.parent_message_id,
        }
        await event_bus.publish(
            topic=f"tool_agent.tool_execution.error.{event.tool_call_id}",
            event_data=error_payload
        )

async def _adapted_internal_execute_tool_request_handler(
    topic: str, 
    data: dict, 
    app_services: AppServices 
):
    try:
        logger.debug(f"ToolAgentLogic adapter received data for InternalExecuteToolRequest: {data} on topic {topic}")
        event_model = InternalExecuteToolRequest(**data)
        await _handle_internal_execute_tool_request(event_model, app_services)
    except Exception as e:
        logger.error(f"Error in ToolAgentLogic's adapter for InternalExecuteToolRequest from topic '{topic}': {e}. Data: {data}", exc_info=True)
        event_bus: ZeroMQEventBus = app_services['event_bus']
        tool_call_id = data.get("tool_call_id", "unknown_tc_id_adapter_failure")
        error_payload = {
            "type": "ToolCallErrorEvent",
            "tool_call_id": tool_call_id,
            "error_message": f"Adapter failure for InternalExecuteToolRequest: {str(e)}",
            "parent_message_id": data.get("parent_message_id"),
        }
        await event_bus.publish(
            topic=f"tool_agent.tool_execution.error.{tool_call_id}",
            event_data=error_payload
        )

def create_tool_agent_agent_logic(
    app_services: AppServices, 
    agent_config: Dict[str, Any]
) -> Tuple[
    Optional[Callable[[str, AbstractCommandInput], Awaitable[None]]], 
    List[CommandDefinition], 
    Optional[Callable[[AppServices, str], Awaitable[None]]], 
    Optional[Callable[[AppServices, str], Awaitable[None]]]
]:
    logger.info(f"Initializing Tool Agent Agent logic with ZeroMQEventBus support. Config: {agent_config.get('name', 'tool-agent')}")
    
    event_bus: ZeroMQEventBus = app_services['event_bus']
    agent_pocket_flow_instance = _create_tool_agent_pocket_flow(app_services, agent_config)
    
    # Prepare the adapted handler with app_services partially applied
    adapted_handler_with_services = functools.partial(
        _adapted_internal_execute_tool_request_handler, 
        app_services=app_services
    )
    
    # The actual subscription should be managed by agent lifecycle (e.g., on_activate)
    # For now, this function sets up the potential for subscription.
    # The agent's config or an orchestrator would call something like:
    # agent_subscription_id = await event_bus.subscribe(
    # topic_pattern=InternalExecuteToolRequest.__name__,
    # handler_coroutine=adapted_handler_with_services
    # )
    # And store agent_subscription_id for later unsubscription.
    logger.info(
        f"ToolAgentLogic for '{agent_config.get('name', 'tool-agent')}' is configured. "
        f"It will subscribe to '{InternalExecuteToolRequest.__name__}' upon activation."
    )

    async def non_command_handler(raw_input_str: str, cmd_input: AbstractCommandInput):
        # This handler processes general user input when ToolAgent is active.
        ctx = CommandContext(
            input=cmd_input,
            output=None,  # Output is via event_bus published by nodes/handlers
            prompt_func=None, # Prompts would also be event-driven
            app_services=app_services,
            agent_name=agent_config.get('name', 'tool-agent'),
            loop=asyncio.get_running_loop(),
            parsed_args={},
        )
        await _tool_agent_input_handler(
            ctx, 
            app_services_closure=app_services, 
            agent_config_closure=agent_config, 
            agent_pocket_flow_closure=agent_pocket_flow_instance
        )

    commands: List[CommandDefinition] = []

    async def _on_tool_agent_enter(app_svcs_hook: AppServices, agent_name_hook_arg: str):
        logger.info(f"Entering Tool Agent: {agent_name_hook_arg}")
        hook_event_bus: ZeroMQEventBus = app_svcs_hook['event_bus']
        
        greeting_message = agent_config.get(
            'entry_message', 
            f"Tool Agent initialized. {agent_config.get('description', 'Use natural language to interact.')}"
        )
        message_id = str(uuid.uuid4())
        
        start_event = TextMessageStartEvent(message_id=message_id, role=Role.ASSISTANT)
        await hook_event_bus.publish(
            topic=f"{AG_UI_EVENT_PREFIX}.{EventType.TEXT_MESSAGE_START.value}",
            event_data=start_event.model_dump(mode="json")
        )
        
        content_event = TextMessageContentEvent(message_id=message_id, delta=greeting_message)
        await hook_event_bus.publish(
            topic=f"{AG_UI_EVENT_PREFIX}.{EventType.TEXT_MESSAGE_CONTENT.value}",
            event_data=content_event.model_dump(mode="json")
        )
        
        end_event = TextMessageEndEvent(message_id=message_id)
        await hook_event_bus.publish(
            topic=f"{AG_UI_EVENT_PREFIX}.{EventType.TEXT_MESSAGE_END.value}",
            event_data=end_event.model_dump(mode="json")
        )
    
    return non_command_handler, commands, _on_tool_agent_enter, None # No on_exit_hook for now