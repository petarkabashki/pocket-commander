# pocket_commander/agents/tool_agent/tool_agent_agent_logic.py
import asyncio
import copy
import logging
from typing import Any, Dict, Tuple, List, Callable, Awaitable

from ...pocketflow import AsyncFlow, AsyncFlowManager
from ...nodes.initial_query_node import InitialQueryNode
from ...nodes.tool_enabled_llm_node import ToolEnabledLLMNode
from ...nodes.print_final_answer_node import PrintFinalAnswerNode
from ...commands.core import CommandContext
from ...commands.definition import CommandDefinition
from ...types import AppServices
from ...commands.io import AbstractCommandInput # Added import

logger = logging.getLogger(__name__)

# Adapted from the original tool_flow.py
def _create_tool_agent_pocket_flow(app_services: AppServices, agent_config: Dict[str, Any]):
    initial_query = InitialQueryNode()
    llm_agent = ToolEnabledLLMNode(max_retries=2, wait=1)
    
    final_answer_printer = PrintFinalAnswerNode(
        output_handler=app_services['output_handler'], 
        prints_directly=True
    )

    initial_query >> llm_agent
    llm_agent - "llm_decide_next" >> llm_agent
    llm_agent - "answer_provided" >> final_answer_printer
    llm_agent - "error" >> final_answer_printer

    return AsyncFlow(start=initial_query)

async def _tool_agent_input_handler(
    context: CommandContext,
    # app_services, agent_config, and agent_pocket_flow are accessed from closure
    app_services_closure: AppServices,
    agent_config_closure: Dict[str, Any],
    agent_pocket_flow_closure: AsyncFlow
):
    user_input = context.input._raw_input_str

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
        logger.error(f"Error in Tool Agent Agent flow: {e}", exc_info=True)
        await app_services_closure['output_handler'].send_error(
            "An error occurred while processing your request in Tool Agent agent."
        )

# Agent Composition Function for Tool Agent Agent
def create_tool_agent_agent_logic(
    app_services: AppServices, 
    agent_config: Dict[str, Any]
) -> Tuple[Callable[[str, AbstractCommandInput], Awaitable[None]], List[CommandDefinition], Callable[[AppServices, str], Awaitable[None]], None]:
    """
    Creates the logic for the Tool Agent agent.
    Returns a non-command input handler, a list of command definitions, an on_enter hook, and an on_exit hook (None for now).
    """
    logger.info(f"Initializing Tool Agent Agent logic structure. Config: {agent_config.get('description', 'Interactive tool-enabled agent.')}")

    # These are now part of the closure for _tool_agent_input_handler and non_command_handler
    agent_pocket_flow_instance = _create_tool_agent_pocket_flow(app_services, agent_config)

    async def non_command_handler(raw_input_str: str, cmd_input: AbstractCommandInput):
        # Construct CommandContext here
        ctx = CommandContext(
            input=cmd_input,
            output=app_services['output_handler'],
            prompt_func=app_services['prompt_func'],
            app_services=app_services,
            agent_name=agent_config.get('name', 'tool-agent'), # Get agent name from config
            loop=asyncio.get_running_loop(),
            parsed_args={}, # No specific parsed args for raw input
            
        )
        await _tool_agent_input_handler(
            ctx, 
            app_services_closure=app_services, 
            agent_config_closure=agent_config, 
            agent_pocket_flow_closure=agent_pocket_flow_instance
        )

    commands: List[CommandDefinition] = []

    async def _on_tool_agent_enter(app_svcs: AppServices, agent_name_hook_arg: str): # Renamed agent_name to avoid clash
        logger.info(f"Entering Tool Agent Agent: {agent_name_hook_arg}")
        await app_svcs['output_handler'].send_message(
            f"Tool Agent Agent initialized. {agent_config.get('description', 'Use natural language to interact with the agent.')}",
            style="dim"
        )
    
    return non_command_handler, commands, _on_tool_agent_enter, None