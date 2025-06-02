#%%
# pocket_commander/commands/builtin_commands.py
import logging # Added for /loglevel command
from pocket_commander.commands.core import CommandContext
from pocket_commander.tools.registry import global_tool_registry
from pocket_commander.commands.definition import CommandDefinition, ParameterDefinition
from typing import List, Any, Awaitable, Callable, Optional # Added Optional

# Standard logger for this module
logger = logging.getLogger(__name__)

async def list_tools_command(ctx: CommandContext) -> None:
    """
    Lists all available tools registered in the system.
    """
    tool_definitions = global_tool_registry.list_tools()
    if not tool_definitions:
        await ctx.output.send_message("No tools are currently registered.")
        return

    tool_names = [td.name for td in tool_definitions]
    tool_list_str = "\n".join(f"- {name}" for name in sorted(tool_names))
    await ctx.output.send_message("Available tools:\n" + tool_list_str)

async def tool_details_command(ctx: CommandContext) -> None:
    """
    Displays detailed information about a specific tool.
    """
    tool_name = ctx.parsed_args.get("tool_name")
    if not tool_name:
        await ctx.output.send_error("Tool name not provided.")
        return

    tool_def = global_tool_registry.get_tool(tool_name)
    if not tool_def:
        await ctx.output.send_error(f"Tool not found: {tool_name}")
        return

    details_parts = []
    details_parts.append(f"Tool: {tool_def.name}")
    details_parts.append(f"Description: {tool_def.description}")

    if tool_def.parameters:
        details_parts.append("Parameters:")
        for param in tool_def.parameters:
            param_info = f"  - {param.name} ({param.type_str}): {param.description}"
            if not param.is_required:
                param_info += f" [Optional, Default: {param.default_value}]"
            else:
                param_info += " [Required]"
            details_parts.append(param_info)
    else:
        details_parts.append("Parameters: None")

    await ctx.output.send_message("\n".join(details_parts))

async def _cmd_global_loglevel(ctx: CommandContext) -> None:
    """
    Gets or sets the global log level for the Python logging system.
    """
    new_level_str: Optional[str] = ctx.parsed_args.get("level")
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    if new_level_str is None:
        # No argument provided, display current level
        current_level = ctx.app_services.get('current_log_level', 'UNKNOWN')
        await ctx.output.send_message(f"Current log level: {current_level}")
        return

    new_level_str_upper = new_level_str.upper()
    if new_level_str_upper not in valid_levels:
        await ctx.output.send_error(
            f"Invalid log level '{new_level_str}'. "
            f"Valid options are: {', '.join(valid_levels)}"
        )
        return

    try:
        # Convert string level to logging module's integer constant
        numeric_level = getattr(logging, new_level_str_upper)
        
        # Update the root logger's level
        logging.getLogger().setLevel(numeric_level)
        
        # Update AppServices
        # Ensure 'current_log_level' can be updated; AppServices is a TypedDict
        # If AppServices is passed as a mutable dict (common pattern), this works.
        ctx.app_services['current_log_level'] = new_level_str_upper
        
        await ctx.output.send_message(f"Log level set to {new_level_str_upper}")
        logger.info(f"Global log level changed to {new_level_str_upper} by /loglevel command.")

    except AttributeError:
        # Should not happen if valid_levels check is correct
        await ctx.output.send_error(f"Internal error: Could not find logging level '{new_level_str_upper}'.")
        logger.error(f"Internal error in /loglevel: getattr(logging, '{new_level_str_upper}') failed.")
    except Exception as e:
        await ctx.output.send_error(f"An unexpected error occurred while setting log level: {e}")
        logger.error(f"Unexpected error in /loglevel setting level to {new_level_str_upper}: {e}", exc_info=True)


# Command Definitions

LIST_TOOLS_COMMAND_DEF = CommandDefinition(
    name="tools",
    handler=list_tools_command,
    description="Lists all registered tools.",
    parameters=[],
    aliases=["list_tools"],
    category="System"
)

TOOL_DETAILS_COMMAND_DEF = CommandDefinition(
    name="tool-details",
    handler=tool_details_command,
    description="Displays detailed information about a specific tool.",
    parameters=[
        ParameterDefinition(name="tool_name", param_type=str, description="The name of the tool to inspect.", is_required=True)
    ],
    aliases=["td", "tool_info"],
    category="System"
)

LOGLEVEL_COMMAND_DEF = CommandDefinition(
    name="loglevel",
    handler=_cmd_global_loglevel,
    description="Gets or sets the global log level.",
    parameters=[
        ParameterDefinition(
            name="level",
            param_type=str, # Type hint for the parameter
            description="The desired log level (DEBUG, INFO, WARNING, ERROR, CRITICAL). If omitted, shows current level.",
            required=False # Make the parameter optional
        )
    ],
    category="Global" # As per design doc
)

def get_builtin_commands() -> List[CommandDefinition]:
    """Returns a list of all built-in command definitions."""
    return [
        LIST_TOOLS_COMMAND_DEF,
        TOOL_DETAILS_COMMAND_DEF,
        LOGLEVEL_COMMAND_DEF, # Added new command
        # Other built-in commands can be added here in the future
    ]