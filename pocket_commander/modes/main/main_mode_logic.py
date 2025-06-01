#%%
# pocket_commander/modes/main/main_mode_logic.py
import asyncio
import logging
from typing import Dict, List, Callable, Awaitable, Any, Tuple, Optional

from pocket_commander.commands.definition import CommandDefinition, ParameterDefinition
from pocket_commander.commands.io import AbstractCommandInput, AbstractOutputHandler
from pocket_commander.commands.core import CommandContext
from pocket_commander.commands.parser import parse_arguments, ArgumentParsingError
from pocket_commander.types import AppServices

logger = logging.getLogger(__name__)

# --- Command Functions for Main Mode ---

async def _cmd_greet(ctx: CommandContext):
    """Greets the user or a specified name."""
    name_arg = ctx.parsed_args.get("name", None)
    
    mode_config = ctx.app_services['raw_app_config'].get('modes', {}).get(ctx.mode_name, {})
    default_greet_name = mode_config.get("default_greet_name", "User from Main Mode")

    if not name_arg:
        name_arg = default_greet_name
        
    await ctx.output.send_message(f"Hello, {name_arg} from Main Mode!", style="bold magenta")
    await ctx.output.send_data({"recipient": name_arg, "message": "Hello from Main Mode"}, format_hint="json")

async def _cmd_modeinfo(ctx: CommandContext):
    """Shows information about the current mode's configuration."""
    mode_config = ctx.app_services['raw_app_config'].get('modes', {}).get(ctx.mode_name, {})
    await ctx.output.send_message(f"--- {ctx.mode_name} Mode Configuration ---", style="bold blue")
    await ctx.output.send_data(mode_config, format_hint="json")

async def _cmd_help(ctx: CommandContext, command_defs: List[CommandDefinition]):
    """Shows help for Main Mode commands."""
    await ctx.output.send_message(f"--- {ctx.mode_name} Mode Commands ---", style="bold cyan")
    if not command_defs:
        await ctx.output.send_message("No commands available in this mode.", style="italic")
        return

    help_lines = []
    for cmd_def in command_defs:
        desc = cmd_def.description or "No description"
        params_str = ""
        if cmd_def.parameters:
            params_list = []
            for p_def in cmd_def.parameters:
                p_str = p_def.name
                if not p_def.required:
                    p_str = f"[{p_str}]"
                params_list.append(p_str)
            params_str = " " + " ".join(params_list)
        
        aliases_str = f"(Aliases: {', '.join(cmd_def.aliases)})" if cmd_def.aliases else ""
        help_lines.append(f"  {cmd_def.name}{params_str:<25} - {desc} {aliases_str}")
    
    await ctx.output.send_message("\n".join(help_lines))

# --- Non-Command Input Processor ---

async def _main_mode_non_command_processor(
    raw_input_str: str,
    command_input: AbstractCommandInput,
    app_services: AppServices,
    mode_name: str
):
    """Handles input that isn't a recognized command in main mode."""
    logger.debug(f"Main mode non-command input: {raw_input_str}")
    output_handler = app_services['output_handler']
    await output_handler.send_message(
        f"Main Mode received: '{raw_input_str}'. This is not a known command. Type 'help'.",
        style="italic yellow"
    )

# --- Mode Composition Function ---

ModeInputHandlerFunc = Callable[[str, AbstractCommandInput, AppServices], Awaitable[None]]
ModeLogicComponents = Tuple[ModeInputHandlerFunc, List[CommandDefinition], Optional[Callable[[AppServices, str], Awaitable[None]]], Optional[Callable[[AppServices, str], Awaitable[None]]]]

def create_main_mode_logic(
    mode_config: Dict[str, Any], # Specific config for this mode instance
    app_services: AppServices   # Global application services
) -> ModeLogicComponents:
    """
    Composition function for the Main Mode.

    Returns a tuple containing:
    1.  mode_input_handler_func: The primary input handler for this mode.
    2.  command_definitions: A list of CommandDefinition objects for this mode.
    3.  on_enter_hook (Optional): An async function called when the mode is entered.
    4.  on_exit_hook (Optional): An async function called when the mode is exited.
    """
    MODE_NAME = mode_config.get("name", "main")

    # Define CommandDefinitions
    main_mode_commands: List[CommandDefinition] = [
        CommandDefinition(
            name="greet",
            command_function=_cmd_greet,
            description="Greets the user or a specified name.",
            parameters=[
                ParameterDefinition(name="name", param_type=str, description="The name to greet.", required=False)
            ],
            aliases=["hello"],
            category="MainMode"
        ),
        CommandDefinition(
            name="modeinfo",
            command_function=_cmd_modeinfo,
            description="Shows information about the current mode's configuration.",
            category="MainMode"
        ),
        # The help command needs access to the list of command definitions
        # We'll pass it via a partial or closure within the input handler
    ]
    
    # Special handling for help command to pass its own command list
    async def _cmd_help_with_context(ctx: CommandContext):
        await _cmd_help(ctx, main_mode_commands)

    main_mode_commands.append(
        CommandDefinition(
            name="help",
            command_function=_cmd_help_with_context, # Use the wrapped version
            description="Shows help for Main Mode commands.",
            category="MainMode"
        )
    )
    
    # Create a command map for quick lookup
    command_map: Dict[str, CommandDefinition] = {}
    for cmd_def in main_mode_commands:
        command_map[cmd_def.name] = cmd_def
        for alias in cmd_def.aliases:
            command_map[alias] = cmd_def

    async def main_mode_input_handler(
        raw_input_str: str,
        command_input: AbstractCommandInput, # Provided by the top-level app handler
        # app_services_for_mode: AppServices # Already available in closure
    ):
        cmd_word = command_input.get_command_word()
        output_handler = app_services['output_handler'] # from closure

        if cmd_word and cmd_word in command_map:
            cmd_to_run = command_map[cmd_word]
            try:
                parsed_args = await parse_arguments(command_input, cmd_to_run.parameters)
                
                ctx = CommandContext(
                    input=command_input,
                    output=output_handler,
                    prompt_func=app_services['prompt_func'],
                    app_services=app_services,
                    mode_name=MODE_NAME,
                    loop=asyncio.get_running_loop(),
                    parsed_args=parsed_args
                )
                await cmd_to_run.command_function(ctx)
            except ArgumentParsingError as ape:
                logger.error(f"Argument parsing error for command '{cmd_word}': {ape}", exc_info=False)
                await output_handler.send_error(f"Error: {ape}", details=f"Usage: {cmd_word} " + " ".join([f"<{p.name}>" if p.required else f"[{p.name}]" for p in cmd_to_run.parameters]))
            except Exception as e:
                logger.error(f"Error executing command '{cmd_word}' in {MODE_NAME} mode: {e}", exc_info=True)
                await output_handler.send_error(f"An unexpected error occurred in command '{cmd_word}'.", details=str(e))
        else:
            # Not a known command for this mode, call the non-command processor
            await _main_mode_non_command_processor(raw_input_str, command_input, app_services, MODE_NAME)

    async def on_enter_hook(current_app_services: AppServices, mode_name_entered: str):
        logger.info(f"Entering {mode_name_entered} Mode (via main_mode_logic).")
        await current_app_services['output_handler'].send_message(
            f"Welcome to {mode_name_entered} Mode! Type 'help' for mode commands or '/help' for global commands.",
            style="bold blue"
        )

    async def on_exit_hook(current_app_services: AppServices, mode_name_exited: str):
        logger.info(f"Exiting {mode_name_exited} Mode (via main_mode_logic).")
        # Perform any cleanup specific to this mode if needed in the future

    return main_mode_input_handler, main_mode_commands, on_enter_hook, on_exit_hook