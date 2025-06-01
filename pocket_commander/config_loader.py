import yaml
import logging
from typing import Dict, Any, List, Type

from pocket_commander.tools.registry import global_tool_registry
from pocket_commander.tools.definition import ToolParameterDefinition

logger = logging.getLogger(__name__)

# Mapping from YAML type strings to Python types
YAML_TO_PYTHON_TYPE_MAP: Dict[str, Type[Any]] = {
    "string": str,
    "integer": int,
    "number": float,  # JSON schema "number" can be float or int, defaulting to float
    "boolean": bool,
    "array": list,    # For simplicity, not handling item types within arrays from YAML yet
    "object": dict,   # For simplicity, not handling specific object schemas from YAML yet
}

def get_python_type_from_yaml_str(type_str: str) -> Type[Any]:
    """Converts a YAML type string to a Python type."""
    return YAML_TO_PYTHON_TYPE_MAP.get(type_str.lower(), str) # Default to str if unknown

def load_and_register_mcp_tools_from_config(config_path: str = "pocket_commander.conf.yaml"):
    """
    Loads MCP tool configurations from the specified YAML file and registers them.
    """
    try:
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_path}")
        return
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration file {config_path}: {e}")
        return
    except Exception as e:
        logger.error(f"An unexpected error occurred while reading {config_path}: {e}")
        return

    mcp_tools_config = config_data.get("mcp_tools")
    if not mcp_tools_config:
        logger.info("No 'mcp_tools' section found in configuration or it's empty.")
        return

    if not isinstance(mcp_tools_config, list):
        logger.error("'mcp_tools' section in configuration must be a list.")
        return

    logger.info(f"Found {len(mcp_tools_config)} MCP tool(s) in configuration. Attempting to register.")

    for tool_config in mcp_tools_config:
        if not isinstance(tool_config, dict):
            logger.warning(f"Skipping invalid MCP tool configuration item (not a dictionary): {tool_config}")
            continue

        server_name = tool_config.get("server_name")
        tool_name = tool_config.get("tool_name")
        description = tool_config.get("description")
        parameters_config = tool_config.get("parameters")

        if not all([server_name, tool_name, description]):
            logger.warning(
                f"Skipping MCP tool due to missing 'server_name', 'tool_name', or 'description': {tool_config}"
            )
            continue
        
        if not isinstance(parameters_config, list) and parameters_config is not None:
            logger.warning(
                f"Skipping MCP tool '{tool_name}' on server '{server_name}' due to invalid 'parameters' format (must be a list or null)."
            )
            continue

        parsed_parameters: List[ToolParameterDefinition] = []
        if parameters_config: # parameters_config can be None or empty list
            for param_conf in parameters_config:
                if not isinstance(param_conf, dict):
                    logger.warning(f"Skipping invalid parameter configuration (not a dictionary) for tool {tool_name}: {param_conf}")
                    continue
                
                param_name = param_conf.get("name")
                param_desc = param_conf.get("description")
                param_type_str = param_conf.get("type", "string") # Default to string if not specified
                param_is_required = param_conf.get("required", False)
                param_default_value = param_conf.get("default")

                if not param_name or not param_desc:
                    logger.warning(
                        f"Skipping parameter for tool '{tool_name}' due to missing 'name' or 'description': {param_conf}"
                    )
                    continue
                
                actual_param_type = get_python_type_from_yaml_str(param_type_str)

                parsed_parameters.append(
                    ToolParameterDefinition(
                        name=param_name,
                        description=param_desc,
                        param_type=actual_param_type,
                        type_str=param_type_str.lower(), # Store the original YAML type string
                        is_required=param_is_required,
                        default_value=param_default_value
                    )
                )
        
        try:
            global_tool_registry.register_mcp_tool(
                mcp_server_name=server_name,
                mcp_tool_name=tool_name,
                mcp_tool_description=description,
                mcp_tool_parameters=parsed_parameters,
                allow_override=True # Allow overriding if config is reloaded, or for dev
            )
            # Logger message is already in register_mcp_tool
        except Exception as e:
            logger.error(f"Error registering MCP tool '{tool_name}' from server '{server_name}': {e}", exc_info=True)

    logger.info("Finished processing MCP tool configurations.")

if __name__ == '__main__':
    # Basic test for the loader
    logging.basicConfig(level=logging.INFO)
    logger.info("Testing MCP tool loading from pocket_commander.conf.yaml...")
    # Create a dummy conf for testing if it doesn't exist or to ensure specific content
    # For a real test, you'd mock open() or use a temporary file.
    # This assumes pocket_commander.conf.yaml is in the current directory or accessible.
    load_and_register_mcp_tools_from_config()
    
    logger.info("Registered tools in global_tool_registry after loading:")
    if not global_tool_registry.list_tools():
        logger.info("  No tools registered.")
    for tool_def in global_tool_registry.list_tools():
        logger.info(f"  - Name: {tool_def.name}, Description: {tool_def.description}")
        for param in tool_def.parameters:
            logger.info(f"    - Param: {param.name} ({param.type_str}), Required: {param.is_required}, Default: {param.default_value}")