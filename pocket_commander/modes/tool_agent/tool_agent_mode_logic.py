# pocket_commander/modes/tool_agent/tool_agent_mode_logic.py
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

logger = logging.getLogger(__name__)

# Adapted from the original tool_flow.py
def _create_tool_agent_pocket_flow(app_services: AppServices, mode_config: Dict[str, Any]):
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
    app_services: AppServices, 
    mode_config: Dict[str, Any],
    agent_pocket_flow: AsyncFlow
):
    user_input = context.raw_input_str

    shared_data_template = {
        "query": None,
        "context": mode_config.get("initial_context", ""), 
        "messages": [],
        "final_answer": None,
        "tool_result": None,
    }
    current_shared_data = copy.deepcopy(shared_data_template)
    current_shared_data["query"] = user_input 

    flow_manager = AsyncFlowManager(agent_pocket_flow)
    
    try:
        await flow_manager.run(current_shared_data) 
    except Exception as e:
        logger.error(f"Error in Tool Agent Mode flow: {e}", exc_info=True)
        await app_services['output_handler'].send_error( # Added await here too
            "An error occurred while processing your request in Tool Agent mode."
        )

# Mode Composition Function for Tool Agent Mode
def create_tool_agent_mode_logic(
    app_services: AppServices, 
    mode_config: Dict[str, Any]
) -> Tuple[Callable[[CommandContext], Awaitable[None]], List[CommandDefinition], Callable[[AppServices, str], Awaitable[None]], None]: # Adjusted return type hint
    """
    Creates the logic for the Tool Agent mode.
    Returns a non-command input handler, a list of command definitions, an on_enter hook, and an on_exit hook (None for now).
    """
    logger.info(f"Initializing Tool Agent Mode logic structure. Config: {mode_config.get('description', 'Interactive tool-enabled agent.')}")

    agent_pocket_flow = _create_tool_agent_pocket_flow(app_services, mode_config)

    async def non_command_handler(context: CommandContext):
        await _tool_agent_input_handler(context, app_services, mode_config, agent_pocket_flow)

    commands: List[CommandDefinition] = []

    async def _on_tool_agent_enter(app_svcs: AppServices, mode_name: str):
        logger.info(f"Entering Tool Agent Mode: {mode_name}")
        await app_svcs['output_handler'].send_message(
            f"Tool Agent Mode initialized. {mode_config.get('description', 'Use natural language to interact with the agent.')}",
            style="dim"
        )
    
    return non_command_handler, commands, _on_tool_agent_enter, None # Return on_enter hook