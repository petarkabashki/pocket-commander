import yaml
import logging
import os
from typing import Dict, Any, List, Type, Optional

from pocket_commander.pocketflow.base import BaseNode # Ensure BaseNode is defined
from pydantic import BaseModel, Field # Added BaseModel and Field

from pocket_commander.tools.registry import ToolRegistry
from pocket_commander.tools.definition import ToolParameterDefinition
from pocket_commander.types import AgentConfig
from pocket_commander.agent_resolver import AgentResolver

logger = logging.getLogger(__name__)

# Mapping from YAML type strings to Python types
YAML_TO_PYTHON_TYPE_MAP: Dict[str, Type[Any]] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}

# Pydantic Models for Configuration
class ZeroMQEventBusConfig(BaseModel):
    broker_publisher_frontend_address: str
    broker_subscriber_frontend_address: str
    broker_xsub_bind_address: Optional[str] = None
    broker_xpub_bind_address: Optional[str] = None

class LoggingConfig(BaseModel):
    level: str = "INFO"
    file_path: Optional[str] = "pocket_commander.log"
    file_mode: str = "a"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    levels: Optional[Dict[str, str]] = None

class ApplicationSettings(BaseModel):
    default_agent: Optional[str] = "main"
    # Add other application-specific settings here

class LLMProfile(BaseModel):
    provider: Optional[str] = None
    api_key_name: Optional[str] = None
    model: Optional[str] = None
    api_base: Optional[str] = None
    inherits: Optional[str] = None
    # Allow any other fields for flexibility
    class Config:
        extra = "allow"

class AppConfig(BaseModel):
    llm_profiles: Dict[str, LLMProfile] = Field(default_factory=dict)
    application: Optional[ApplicationSettings] = None
    agent_discovery_folders: Optional[List[str]] = None
    logging: Optional[LoggingConfig] = None
    agents: Dict[str, Any] = Field(default_factory=dict) # Raw agent config from YAML
    resolved_agents: Dict[str, AgentConfig] = Field(default_factory=dict) # Processed AgentConfig objects
    mcp_tools: Optional[List[Dict[str, Any]]] = None # Raw MCP tool config from YAML
    zeromq_event_bus: Optional[ZeroMQEventBusConfig] = None

    class Config:
        extra = "ignore" # Ignore extra fields from YAML at the top level if not defined in AppConfig


def get_python_type_from_yaml_str(type_str: str) -> Type[Any]:
    """Converts a YAML type string to a Python type."""
    return YAML_TO_PYTHON_TYPE_MAP.get(type_str.lower(), str)

def load_and_resolve_app_config(config_path: str = "pocket_commander.conf.yaml") -> Optional[AppConfig]:
    """
    Loads the main application configuration from the specified YAML file,
    resolves agent configurations, and returns an AppConfig Pydantic model.
    """
    try:
        project_root = os.getcwd()

        with open(config_path, 'r') as f:
            raw_config_data = yaml.safe_load(f)
        if not isinstance(raw_config_data, dict):
            logger.error(f"Configuration file {config_path} did not load as a dictionary.")
            return None

        # Initialize AppConfig with raw data, Pydantic will handle parsing for known fields
        # For fields like 'agents' and 'mcp_tools', we store the raw data and process 'agents' later.
        AppConfig.model_rebuild() # Ensure all forward refs are resolved
        app_config = AppConfig(**raw_config_data)

        # Resolve agents
        agent_resolver = AgentResolver()
        parsed_agent_configs: Dict[str, AgentConfig] = {}
        agents_yaml_section = app_config.agents # Use the raw agents data from AppConfig

        if not isinstance(agents_yaml_section, dict):
            logger.error("'agents' section in configuration must be a dictionary. Skipping agent parsing.")
        else:
            discovery_folders_cfg = app_config.agent_discovery_folders
            for agent_slug, agent_yaml_details in agents_yaml_section.items():
                if not isinstance(agent_yaml_details, dict):
                    logger.error(f"Configuration for agent '{agent_slug}' is not a dictionary. Skipping.")
                    continue
                
                logger.debug(f"Attempting to resolve agent '{agent_slug}' with details: {agent_yaml_details}")
                resolved_config = agent_resolver.resolve_agent_config(
                    slug=agent_slug,
                    agent_yaml_config=agent_yaml_details,
                    project_root=project_root,
                    discovery_folders=discovery_folders_cfg
                )
                if resolved_config:
                    parsed_agent_configs[agent_slug] = resolved_config
                else:
                    logger.warning(f"Failed to resolve agent configuration for slug '{agent_slug}'. It will not be available.")
        
        app_config.resolved_agents = parsed_agent_configs # Store resolved agents in the AppConfig instance
        logger.info(f"Successfully loaded and resolved {len(parsed_agent_configs)} agent(s).")
        
        return app_config

    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_path}")
        return None
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration file {config_path}: {e}")
        return None
    except Exception as e: # Catch Pydantic validation errors too
        logger.error(f"An unexpected error occurred while loading/resolving config from {config_path}: {e}", exc_info=True)
        return None


def load_and_register_mcp_tools_from_config(app_config: Optional[AppConfig], registry: ToolRegistry):
    """
    Loads MCP tool configurations from the AppConfig object and registers them.
    Args:
        app_config: The loaded AppConfig Pydantic model.
                     If None, the function will log an error and return.
        registry: The ToolRegistry instance to register tools into.
    """
    if app_config is None:
        logger.error("Cannot load MCP tools because application configuration data is None.")
        return

    mcp_tools_config = app_config.mcp_tools # Get raw MCP tools from AppConfig
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
        if parameters_config:
            for param_conf in parameters_config:
                if not isinstance(param_conf, dict):
                    logger.warning(f"Skipping invalid parameter configuration (not a dictionary) for tool {tool_name}: {param_conf}")
                    continue
                
                param_name = param_conf.get("name")
                param_desc = param_conf.get("description")
                param_type_str = param_conf.get("type", "string")
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
                        type_str=param_type_str.lower(),
                        is_required=param_is_required,
                        default_value=param_default_value
                    )
                )
        
        try:
            registry.register_mcp_tool(
                mcp_server_name=server_name,
                mcp_tool_name=tool_name,
                mcp_tool_description=description,
                mcp_tool_parameters=parsed_parameters,
                allow_override=True
            )
        except Exception as e:
            logger.error(f"Error registering MCP tool '{tool_name}' from server '{server_name}': {e}", exc_info=True)

    logger.info("Finished processing MCP tool configurations.")

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    
    logger.info("Testing application configuration loading and agent parsing...")
    app_config_instance = load_and_resolve_app_config()
    
    if app_config_instance:
        logger.info("Application configuration loaded successfully.")
        
        if app_config_instance.zeromq_event_bus:
            logger.info("ZeroMQ Event Bus Configuration:")
            logger.info(f"  Broker Publisher Frontend: {app_config_instance.zeromq_event_bus.broker_publisher_frontend_address}")
            logger.info(f"  Broker Subscriber Frontend: {app_config_instance.zeromq_event_bus.broker_subscriber_frontend_address}")
            if app_config_instance.zeromq_event_bus.broker_xsub_bind_address:
                 logger.info(f"  Broker XSUB Bind: {app_config_instance.zeromq_event_bus.broker_xsub_bind_address}")
            if app_config_instance.zeromq_event_bus.broker_xpub_bind_address:
                 logger.info(f"  Broker XPUB Bind: {app_config_instance.zeromq_event_bus.broker_xpub_bind_address}")
        else:
            logger.info("No ZeroMQ Event Bus configuration found.")

        if app_config_instance.logging:
            logger.info(f"Logging Config: Level {app_config_instance.logging.level}")

        resolved_agents_map = app_config_instance.resolved_agents
        if resolved_agents_map:
            logger.info(f"Found {len(resolved_agents_map)} resolved agent configuration(s):")
            for slug, agent_conf_obj in resolved_agents_map.items():
                logger.info(f"  Agent Slug: {slug}")
                logger.info(f"    Description: {agent_conf_obj.description}")
                # ... more detailed logging if needed ...
        else:
            logger.info("No agents resolved or 'agents' section was empty/invalid in config.")

        from pocket_commander.tools.registry import ToolRegistry as TestToolRegistry 
        test_registry = TestToolRegistry()
        logger.info("\nTesting MCP tool loading from AppConfig into a test_registry...")
        load_and_register_mcp_tools_from_config(app_config_instance, test_registry)
        
        logger.info("\nRegistered tools in test_registry after loading:")
        if not test_registry.list_tools():
            logger.info("  No tools registered in test_registry.")
        for tool_def in test_registry.list_tools():
            logger.info(f"  - Name: {tool_def.name}, Description: {tool_def.description}, Type: {'MCP' if tool_def.is_mcp_tool else 'Native'}")
            if tool_def.is_mcp_tool:
                logger.info(f"    MCP Server: {tool_def.mcp_server_name}, MCP Tool: {tool_def.mcp_tool_name}")
    else:
        logger.error("Failed to load application configuration. Cannot proceed with further tests.")