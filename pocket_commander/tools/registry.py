import inspect
import importlib
import pkgutil
import os
from typing import Dict, List, Optional, Callable, Any, Union

from pocket_commander.tools.definition import ToolDefinition, ToolParameterDefinition
from pocket_commander.tools.mcp_utils import create_mcp_tool_definition

class ToolRegistry:
    """
    Central class responsible for storing, managing, discovering,
    and providing access to registered ToolDefinition objects.
    """
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}  # name -> ToolDefinition

    def register_tool_definition(self, tool_def: ToolDefinition, allow_override: bool = False):
        """
        Registers a ToolDefinition.
        Handles conflicts based on allow_override.
        """
        if not isinstance(tool_def, ToolDefinition):
            print(f"Error: Attempted to register an object that is not a ToolDefinition: {tool_def}")
            # Or raise TypeError
            return

        if not allow_override and tool_def.name in self._tools:
            print(f"Warning: Tool '{tool_def.name}' already registered. Skipping duplicate registration.")
            return
        self._tools[tool_def.name] = tool_def
        # print(f"Tool '{tool_def.name}' registered.") # Can be verbose, consider logging

    def register_tool_func(self, tool_func: Callable[..., Any], allow_override: bool = False):
        """
        Registers a tool function that has been decorated (i.e., has _tool_definition).
        """
        if hasattr(tool_func, '_tool_definition'):
            tool_def = getattr(tool_func, '_tool_definition')
            if isinstance(tool_def, ToolDefinition):
                self.register_tool_definition(tool_def, allow_override=allow_override)
            else:
                print(f"Warning: Function '{tool_func.__name__}' has '_tool_definition' attribute, but it's not a ToolDefinition instance.")
        else:
            print(f"Warning: Function '{tool_func.__name__}' is not a decorated tool or its metadata is missing. Cannot register.")

    def scan_and_register_tools(self, package_path: str, base_module_path: str = ""):
        """
        Scans a package for modules and registers tools found within.
        Tools are expected to be decorated and have a '_tool_definition' attribute.

        Args:
            package_path: Filesystem path to the package directory.
            base_module_path: Dotted module path corresponding to the package_path
                              (e.g., "pocket_commander.tools.plugins").
        """
        print(f"Scanning for tools in package: {package_path} (module base: {base_module_path})")
        for (_, module_name, is_pkg) in pkgutil.walk_packages([package_path]):
            if base_module_path:
                full_module_name = f"{base_module_path}.{module_name}"
            else:
                # This assumes package_path is directly in a location findable by importlib
                # For robust scanning, ensure package_path aligns with Python's import system
                # or adjust how full_module_name is constructed.
                full_module_name = module_name

            try:
                module = importlib.import_module(full_module_name)
                for name, obj in inspect.getmembers(module):
                    if inspect.isfunction(obj) and hasattr(obj, '_tool_definition'):
                        tool_def = getattr(obj, '_tool_definition')
                        if isinstance(tool_def, ToolDefinition):
                            # Scanned tools are registered with lower precedence (no override)
                            self.register_tool_definition(tool_def, allow_override=False)
            except ModuleNotFoundError:
                print(f"Warning: Module {full_module_name} not found during scan. Ensure it's in PYTHONPATH if it's a top-level module name.")
            except Exception as e:
                print(f"Error importing or scanning module {full_module_name}: {e}")

    def register_mcp_tool(
        self,
        mcp_server_name: str,
        mcp_tool_name: str,
        mcp_tool_description: str,
        mcp_tool_parameters: List[ToolParameterDefinition],
        allow_override: bool = False
    ):
        """
        Creates a ToolDefinition for an MCP tool and registers it.

        Args:
            mcp_server_name: The name of the MCP server.
            mcp_tool_name: The name of the tool on the MCP server.
            mcp_tool_description: Description of the MCP tool.
            mcp_tool_parameters: List of ToolParameterDefinition for the MCP tool.
            allow_override: Whether to allow overriding an existing tool with the same name.
        """
        tool_def = create_mcp_tool_definition(
            mcp_server_name=mcp_server_name,
            mcp_tool_name=mcp_tool_name,
            mcp_tool_description=mcp_tool_description,
            mcp_tool_parameters=mcp_tool_parameters
        )
        self.register_tool_definition(tool_def, allow_override=allow_override)
        print(f"MCP Tool '{tool_def.name}' (from {mcp_server_name}/{mcp_tool_name}) registered.")

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Retrieves a tool by its name."""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        """Returns a list of all registered tool definitions."""
        return list(self._tools.values())

    def get_all_tools_metadata_for_llm(self) -> List[Dict[str, Any]]:
        """
        Formats all tool definitions into a list of dictionaries suitable for LLM
        function calling (e.g., OpenAI's format).
        """
        llm_tools = []
        for tool_def in self._tools.values():
            properties_for_llm = {}
            required_params = []
            for p_def in tool_def.parameters:
                param_details: Dict[str, Any] = {
                    "type": p_def.type_str,
                    "description": p_def.description,
                }
                # Add enum if type_str is "string" and param_type is a Union of literals, or similar
                # This requires more sophisticated type inspection (e.g. typing.get_args for Literal)
                # For now, default_value is just for information, not directly translated to JSON schema default by OpenAI
                # if p_def.default_value is not None:
                #    param_details["default"] = p_def.default_value # OpenAI doesn't use 'default' in this way

                properties_for_llm[p_def.name] = param_details
                if p_def.is_required:
                    required_params.append(p_def.name)
            
            llm_tools.append({
                "type": "function",  # Standard for OpenAI function calling
                "function": {
                    "name": tool_def.name,
                    "description": tool_def.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties_for_llm,
                        "required": required_params,
                    },
                }
            })
        return llm_tools

# Global instance of the ToolRegistry.
# Tools can be registered to this instance from anywhere in the application,
# typically at import time by the @tool decorator.
global_tool_registry = ToolRegistry()