#%%
# pocket_commander/app_core.py
import asyncio
import importlib
import logging
from typing import Dict, List, Callable, Awaitable, Any, Optional, Tuple

from pocket_commander.commands.definition import CommandDefinition, ParameterDefinition
from pocket_commander.commands.io import AbstractCommandInput # AbstractOutputHandler, PromptFunc are in AppServices
from pocket_commander.commands.core import CommandContext
from pocket_commander.commands.parser import parse_arguments, ArgumentParsingError
from pocket_commander.types import AppServices

# Mode-specific logic components structure (imported for type hinting from a mode_logic file)
# from pocket_commander.modes.main.main_mode_logic import ModeInputHandlerFunc, ModeLogicComponents
# Using Any for now to avoid direct dependency on one mode for the generic type hint
ModeInputHandlerFunc = Callable[[str, AbstractCommandInput, AppServices], Awaitable[None]]
OnEnterExitHook = Optional[Callable[[AppServices, str], Awaitable[None]]]
ModeLogicComponents = Tuple[ModeInputHandlerFunc, List[CommandDefinition], OnEnterExitHook, OnEnterExitHook]


logger = logging.getLogger(__name__)

async def create_application_core(
    initial_app_services: AppServices
) -> Callable[[str, AbstractCommandInput], Awaitable[Any]]:
    """
    Creates the core application logic and returns a top-level input handler.

    This function sets up global commands, mode management, and the primary
    input processing loop for the application, all within a functional closure.
    """

    application_state: Dict[str, Any] = {
        "app_services": initial_app_services,
        "global_commands": {}, # Dict[str, CommandDefinition]
        "active_mode_name": None,
        "active_mode_handler": None, # ModeInputHandlerFunc
        "active_mode_commands": [],  # List[CommandDefinition]
        "active_mode_on_enter": None, # OnEnterExitHook
        "active_mode_on_exit": None,  # OnEnterExitHook
        "available_modes": initial_app_services['raw_app_config'].get('modes', {}),
    }
    initial_app_services['_application_state_DO_NOT_USE_DIRECTLY'] = application_state

    output_handler = initial_app_services['output_handler']
    prompt_func = initial_app_services['prompt_func']

    # --- Mode Switching Logic ---
    async def _switch_to_mode(mode_name: str) -> bool:
        """
        Attempts to switch to the specified mode.
        Returns True on success, False on failure.
        """
        nonlocal application_state # Ensure we're modifying the outer scope's state

        if mode_name == application_state["active_mode_name"]:
            await output_handler.send_message(f"Already in '{mode_name}' mode.", style="italic")
            return True

        target_mode_config = application_state["available_modes"].get(mode_name)
        if not target_mode_config:
            await output_handler.send_error(f"Mode '{mode_name}' not found or not configured.")
            return False

        module_path = target_mode_config.get("module")
        composition_function_name = target_mode_config.get("composition_function", f"create_{mode_name.replace('-', '_')}_mode_logic") # Convention

        if not module_path:
            await output_handler.send_error(f"Configuration for mode '{mode_name}' is missing the 'module' path.")
            return False

        try:
            mode_module = importlib.import_module(module_path)
            mode_composition_func = getattr(mode_module, composition_function_name)
        except ImportError:
            logger.error(f"Failed to import mode module: {module_path}", exc_info=True)
            await output_handler.send_error(f"Could not load module for mode '{mode_name}'.")
            return False
        except AttributeError:
            logger.error(f"Composition function '{composition_function_name}' not found in {module_path}", exc_info=True)
            await output_handler.send_error(f"Could not find composition function for mode '{mode_name}'.")
            return False
        except Exception as e:
            logger.error(f"Unexpected error loading mode '{mode_name}': {e}", exc_info=True)
            await output_handler.send_error(f"An unexpected error occurred while loading mode '{mode_name}'.")
            return False

        # Call previous mode's on_exit hook if it exists
        if application_state["active_mode_on_exit"] and application_state["active_mode_name"]:
            try:
                await application_state["active_mode_on_exit"](application_state["app_services"], application_state["active_mode_name"])
            except Exception as e:
                logger.error(f"Error in on_exit hook for mode {application_state['active_mode_name']}: {e}", exc_info=True)


        # Get new mode components
        try:
            # Pass the mode-specific config slice and the global app_services
            mode_handler, mode_commands, on_enter, on_exit = mode_composition_func(
                application_state["app_services"], # Pass AppServices first
                target_mode_config                 # Pass mode_config second
            )
        except Exception as e:
            logger.error(f"Error calling composition function for mode '{mode_name}': {e}", exc_info=True)
            await output_handler.send_error(f"Error initializing mode '{mode_name}'.")
            # Revert to no active mode or a default/previous safe mode might be needed here
            application_state["active_mode_name"] = None
            application_state["active_mode_handler"] = None
            application_state["active_mode_commands"] = []
            application_state["active_mode_on_enter"] = None
            application_state["active_mode_on_exit"] = None
            return False

        application_state["active_mode_name"] = mode_name
        application_state["active_mode_handler"] = mode_handler
        application_state["active_mode_commands"] = mode_commands
        application_state["active_mode_on_enter"] = on_enter
        application_state["active_mode_on_exit"] = on_exit
        
        logger.info(f"Switched to mode: {mode_name}")
        logger.debug(f"APP_CORE: application_state['active_mode_name'] set to: {application_state['active_mode_name']}")
        
        # Call new mode's on_enter hook if it exists
        if application_state["active_mode_on_enter"]:
            try:
                await application_state["active_mode_on_enter"](application_state["app_services"], mode_name)
            except Exception as e:
                logger.error(f"Error in on_enter hook for mode {mode_name}: {e}", exc_info=True)
                # Mode is technically active, but entry failed. Consider implications.
        else: # Default message if no on_enter hook
             await output_handler.send_message(f"Entered '{mode_name}' mode.", style="bold green")
        
        return True

    # --- Global Command Functions ---
    async def _cmd_global_exit(ctx: CommandContext):
        await output_handler.send_message("Exiting Pocket Commander...", style="bold yellow")
        # Graceful shutdown signal - actual exit handled by TerminalInteractionFlow or main loop
        raise SystemExit("User requested exit via /exit command.") 

    async def _cmd_global_help(ctx: CommandContext):
        await output_handler.send_message("--- Global Commands ---", style="bold cyan")
        global_cmds_help = []
        for name, cmd_def in application_state["global_commands"].items():
            if name == cmd_def.name: # Avoid listing aliases
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
                aliases_str = f" (Aliases: {', '.join(cmd_def.aliases)})" if cmd_def.aliases else ""
                global_cmds_help.append(f"  /{name}{params_str:<25} - {desc}{aliases_str}")
        await output_handler.send_message("\n".join(global_cmds_help))
        await output_handler.send_message("Use 'help' (without '/') for mode-specific commands if in a mode.", style="italic")

    async def _cmd_global_modes(ctx: CommandContext):
        await output_handler.send_message("--- Available Modes ---", style="bold cyan")
        if not application_state["available_modes"]:
            await output_handler.send_message("No modes configured.", style="italic")
            return
        for mode_name, mode_cfg in application_state["available_modes"].items():
            desc = mode_cfg.get('description', 'No description')
            is_active = " (active)" if mode_name == application_state["active_mode_name"] else ""
            await output_handler.send_message(f"  {mode_name:<15} - {desc}{is_active}")

    async def _cmd_global_mode_switch(ctx: CommandContext):
        target_mode = ctx.parsed_args.get("mode_name")
        if not target_mode:
            await output_handler.send_error("No mode name provided.", details="Usage: /mode <mode_name>")
            return
        await _switch_to_mode(target_mode)

    # --- Define Global Commands ---
    global_command_definitions: List[CommandDefinition] = [
        CommandDefinition(name="exit", command_function=_cmd_global_exit, description="Exits Pocket Commander.", aliases=["quit", "q"], category="Global"),
        CommandDefinition(name="help", command_function=_cmd_global_help, description="Shows this help message for global commands.", aliases=["?"], category="Global"),
        CommandDefinition(name="modes", command_function=_cmd_global_modes, description="Lists available modes.", category="Global"),
        CommandDefinition(
            name="mode",
            command_function=_cmd_global_mode_switch,
            description="Switches to a specified mode.",
            parameters=[ParameterDefinition(name="mode_name", param_type=str, description="The name of the mode to switch to.")],
            category="Global"
        ),
    ]

    for cmd_def in global_command_definitions:
        application_state["global_commands"][cmd_def.name] = cmd_def
        for alias in cmd_def.aliases:
            application_state["global_commands"][alias] = cmd_def
    
    # --- Load Initial Mode ---
    default_mode_name = initial_app_services['raw_app_config'].get('default_mode', None)
    if default_mode_name:
        logger.info(f"Attempting to load default mode: {default_mode_name}")
        await _switch_to_mode(default_mode_name)
    else:
        logger.info("No default mode specified. Starting without an active mode.")
        await output_handler.send_message("No default mode loaded. Use '/modes' to see available modes and '/mode <name>' to activate one.", style="yellow")


    # --- Top-Level Application Input Handler ---
    async def top_level_app_input_handler(raw_input_str: str, command_input: AbstractCommandInput):
        """
        The main input processor for the application.
        Handles global commands and dispatches to the active mode's handler.
        """
        nonlocal application_state # Ensure access to the up-to-date state
        
        # Global commands usually start with a specific prefix, e.g., '/'
        # The command_input.get_command_word() should ideally handle this.
        # For this example, let's assume command_input.get_command_word() returns it with the prefix if it's a global command.
        
        potential_cmd_word_full = command_input.get_command_word() # e.g. "/mode" or "greet"
        
        # Check for global commands first (assuming they start with '/')
        if potential_cmd_word_full and potential_cmd_word_full.startswith("/"):
            global_cmd_word = potential_cmd_word_full[1:] # Remove leading '/'
            
            if global_cmd_word in application_state["global_commands"]:
                cmd_to_run = application_state["global_commands"][global_cmd_word]
                try:
                    parsed_args = await parse_arguments(command_input, cmd_to_run.parameters)
                    ctx = CommandContext(
                        input=command_input,
                        output=output_handler,
                        prompt_func=prompt_func,
                        app_services=application_state["app_services"],
                        mode_name=None, # Global commands are not in a mode context
                        loop=asyncio.get_running_loop(),
                        parsed_args=parsed_args
                    )
                    await cmd_to_run.command_function(ctx)
                except ArgumentParsingError as ape:
                    logger.error(f"Argument parsing error for global command '{global_cmd_word}': {ape}", exc_info=False)
                    await output_handler.send_error(f"Error: {ape}", details=f"Usage: /{global_cmd_word} " + " ".join([f"<{p.name}>" if p.required else f"[{p.name}]" for p in cmd_to_run.parameters]))
                except SystemExit: # Allow SystemExit from /exit to propagate
                    raise
                except Exception as e:
                    logger.error(f"Error executing global command '{global_cmd_word}': {e}", exc_info=True)
                    await output_handler.send_error(f"An unexpected error occurred in global command '{global_cmd_word}'.", details=str(e))
                return # Global command processed

        # If not a global command, and an active mode handler exists, pass to it
        if application_state["active_mode_handler"]:
            try:
                # The mode handler is responsible for its own command parsing and execution
                await application_state["active_mode_handler"](
                    raw_input_str,
                    command_input,
                    # application_state["app_services"] # Mode handler gets app_services from its own closure
                )
            except Exception as e:
                # This is a fallback for unhandled errors within a mode's input handler itself
                logger.error(f"Unhandled error in active mode '{application_state['active_mode_name']}' handler: {e}", exc_info=True)
                await output_handler.send_error(
                    f"An critical error occurred within {application_state['active_mode_name']} mode.",
                    details="This may indicate a bug in the mode's input processing logic."
                )
        elif not (potential_cmd_word_full and potential_cmd_word_full.startswith("/")): # Not global, no active mode
            await output_handler.send_message(
                f"No active mode to handle input: '{raw_input_str}'. Use '/mode <name>' to activate a mode.",
                style="yellow"
            )
            
    return top_level_app_input_handler