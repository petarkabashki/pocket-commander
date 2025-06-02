# This file makes 'pocket_commander/agents/main' a Python package.
# It exports the agent's composition function as per Plan v8.3.

from .main_agent_logic import create_main_agent_logic

# The create_main_agent_logic function is imported from main_agent_logic.py.
# Its signature is: 
# create_main_agent_logic(agent_config: Dict[str, Any], app_services: AppServices) 
#     -> Tuple[AgentInputHandlerFunc, List[CommandDefinition], Optional[OnEnterHook], Optional[OnExitHook]]
#
# This __init__.py re-exports it for dynamic discovery by the application core.

__all__ = ['create_main_agent_logic']