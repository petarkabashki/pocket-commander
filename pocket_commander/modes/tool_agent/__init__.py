# pocket_commander/modes/tool_agent/__init__.py
from .tool_agent_mode_logic import create_tool_agent_mode_logic

# The old get_flow function is no longer needed with the new architecture.
# If direct instantiation or other specific exports are needed for testing
# or other purposes, they can be added here. For the main application flow,
# app_core.py will dynamically import and use create_tool_agent_mode_logic.