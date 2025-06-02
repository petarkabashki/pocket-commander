# pocket_commander/tools/__init__.py

# Expose the global tool registry for easy access
from .registry import global_tool_registry, ToolRegistry

# Expose the @tool decorator
from .decorators import tool

# Expose the core definitions
from .definition import ToolDefinition, ToolParameterDefinition

# Import modules containing tools decorated with @tool
# This ensures that the @tool decorator runs at import time and registers the tools
# with the global_tool_registry.
# from . import tools # tools.py no longer contains tool definitions
# from . import web_tools # Assuming web_tools.py will contain @tool decorated functions
from . import weather_tool # For get_current_weather
from . import stock_tool # For get_stock_price
from . import fetch_tool # For fetch

# Optionally, you could also initiate scanning of plugin directories here if desired,
# though it might be better to do that explicitly at application startup.
# For example:
# import os
# PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "plugins")
# if os.path.exists(PLUGIN_DIR):
#     global_tool_registry.scan_and_register_tools(
#         package_path=PLUGIN_DIR,
#         base_module_path="pocket_commander.tools.plugins"
#     )
# MCP Tools are now loaded from pocket_commander.conf.yaml by config_loader.py
# The load_and_register_mcp_tools_from_config() function is called in main.py.

__all__ = [
    "global_tool_registry",
    "ToolRegistry",
    "tool",
    "ToolDefinition",
    "ToolParameterDefinition",
    # "tools", # No need to export the modules themselves usually
    # "web_tools"
    # "weather_tool"
    # "stock_tool"
    # "search_tool"
]