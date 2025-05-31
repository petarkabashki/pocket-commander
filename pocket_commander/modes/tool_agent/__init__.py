# pocket_commander/modes/tool_agent/__init__.py
from .tool_agent_flow import create_tool_agent_mode

def get_flow(mode_config, terminal_app_instance):
    """
    Returns an instance of the flow for the 'Tool Agent' mode.
    This is called by the terminal_interface to load the mode.
    """
    return create_tool_agent_mode(mode_config, terminal_app_instance)