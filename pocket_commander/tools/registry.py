import inspect
import importlib
import pkgutil
import os
import logging # Added
from typing import Dict, List, Optional, Callable, Any, Union

from pocket_commander.tools.definition import ToolDefinition, ToolParameterDefinition
from pocket_commander.tools.mcp_utils import create_mcp_tool_definition
# from pocket_commander.types import AgentConfig # Not directly needed here, but good for context

logger = logging.getLogger(__name__) # Added

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
            # Changed print to logger.error
            logger.error(f"Attempted to register an object that is not a ToolDefinition: {tool_def}")
            return

        if not allow_override and tool_def.name in self._tools:
            # Changed print to logger.warning
            logger.warning(f"Tool '{tool_def.name}' already registered. Skipping duplicate registration.")
            return
        self._tools[tool_def.name] = tool_def
        # logger.info(f"Tool '{tool_def.name}' registered.") # Can be verbose

    def register_tool_func(self, tool_func: Callable[..., Any], allow_override: bool = False):
        """
        Registers a tool function that has been decorated (i.e., has _tool_definition).
        """
        if hasattr(tool_func, '_tool_definition'):
            tool_def = getattr(tool_func, '_tool_definition')
            if isinstance(tool_def, ToolDefinition):
                self.register_tool_definition(tool_def, allow_override=allow_override)
            else:
                # Changed print to logger.warning
                logger.warning(f"Function '{tool_func.__name__}' has '_tool_definition' attribute, but it's not a ToolDefinition instance.")
        else:
            # Changed print to logger.warning
            logger.warning(f"Function '{tool_func.__name__}' is not a decorated tool or its metadata is missing. Cannot register.")

    def scan_and_register_tools(self, package_path: str, base_module_path: str = ""):
        """
        Scans a package for modules and registers tools found within.
        Tools are expected to be decorated and have a '_tool_definition' attribute.

        Args:
            package_path: Filesystem path to the package directory.
            base_module_path: Dotted module path corresponding to the package_path
                              (e.g., "pocket_commander.tools.plugins").
        """
        logger.info(f"Scanning for tools in package: {package_path} (module base: {base_module_path})")
        for (_, module_name, is_pkg) in pkgutil.walk_packages([package_path]):
            if base_module_path:
                full_module_name = f"{base_module_path}.{module_name}"
            else:
                full_module_name = module_name

            try:
                module = importlib.import_module(full_module_name)
                for name, obj in inspect.getmembers(module):
                    if inspect.isfunction(obj) and hasattr(obj, '_tool_definition'):
                        tool_def = getattr(obj, '_tool_definition')
                        if isinstance(tool_def, ToolDefinition):
                            self.register_tool_definition(tool_def, allow_override=False)
            except ModuleNotFoundError:
                # Changed print to logger.warning
                logger.warning(f"Module {full_module_name} not found during scan. Ensure it's in PYTHONPATH if it's a top-level module name.")
            except Exception as e:
                # Changed print to logger.error
                logger.error(f"Error importing or scanning module {full_module_name}: {e}", exc_info=True)

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
        """
        tool_def = create_mcp_tool_definition(
            mcp_server_name=mcp_server_name,
            mcp_tool_name=mcp_tool_name,
            mcp_tool_description=mcp_tool_description,
            mcp_tool_parameters=mcp_tool_parameters
        )
        self.register_tool_definition(tool_def, allow_override=allow_override)
        # Changed print to logger.info
        logger.info(f"MCP Tool '{tool_def.name}' (from {mcp_server_name}/{mcp_tool_name}) registered.")

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
                properties_for_llm[p_def.name] = param_details
                if p_def.is_required:
                    required_params.append(p_def.name)
            
            llm_tools.append({
                "type": "function",
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
global_tool_registry = ToolRegistry()


def create_agent_tool_registry(
    agent_slug: str,
    agent_tools_config: Optional[List[str]],
    global_registry: ToolRegistry
) -> ToolRegistry:
    """
    Creates a new ToolRegistry instance tailored for a specific agent.

    Args:
        agent_slug: The slug of the agent for logging purposes.
        agent_tools_config: A list of tool names specified for the agent.
                           - If None, all tools from global_registry are included.
                           - If an empty list, the returned registry is empty.
        global_registry: The global ToolRegistry containing all available tools.

    Returns:
        A new ToolRegistry instance for the agent.
    """
    agent_registry = ToolRegistry()

    if agent_tools_config is None:
        # Default behavior: Agent gets all global tools
        logger.info(f"Agent '{agent_slug}' has no specific tool configuration ('tools' key omitted). "
                    f"It will inherit all {len(global_registry.list_tools())} global tools.")
        for tool_def in global_registry.list_tools():
            agent_registry.register_tool_definition(tool_def)
        return agent_registry

    if not agent_tools_config: # Handles tools: []
        logger.info(f"Agent '{agent_slug}' is configured with an empty tool list ('tools: []'). "
                    f"It will have no tools.")
        return agent_registry

    # If agent_tools_config is a list of tool names
    logger.info(f"Agent '{agent_slug}' is configured with {len(agent_tools_config)} specific tool(s). "
                f"Attempting to populate its registry.")
    for tool_name in agent_tools_config:
        if not isinstance(tool_name, str):
            # This case should ideally be caught by config_loader.py,
            # but adding a safeguard here.
            logger.warning(f"Invalid tool name '{tool_name}' (type: {type(tool_name)}) found in 'tools' list "
                           f"for agent '{agent_slug}'. Tool names must be strings. Skipping.")
            continue

        tool_def = global_registry.get_tool(tool_name)
        if tool_def:
            agent_registry.register_tool_definition(tool_def)
            logger.debug(f"Added tool '{tool_name}' to agent '{agent_slug}' registry.")
        else:
            logger.warning(f"Tool '{tool_name}' specified for agent '{agent_slug}' not found "
                           f"in the global tool registry. Skipping this tool for the agent.")
    
    logger.info(f"Agent '{agent_slug}' registry created with {len(agent_registry.list_tools())} tool(s).")
    return agent_registry