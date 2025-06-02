#%%
# pocket_commander/agents/main/main_agent_logic.py
import asyncio
import logging
from typing import Dict, List, Callable, Awaitable, Any, Tuple, Optional

from pocket_commander.commands.definition import CommandDefinition, ParameterDefinition
from pocket_commander.commands.io import AbstractCommandInput, AbstractOutputHandler
from pocket_commander.commands.core import CommandContext
from pocket_commander.commands.parser import parse_arguments, ArgumentParsingError
from pocket_commander.types import AppServices

logger = logging.getLogger(__name__)

# --- Command Functions for Main Agent ---

async def _cmd_greet(ctx: CommandContext):
    """Greets the user or a specified name."""
    name_arg = ctx.parsed_args.get("name", None)
    
    agent_config = ctx.app_services['raw_app_config'].get('agents', {}).get(ctx.agent_name, {})
    default_greet_name = agent_config.get("default_greet_name", "User from Main Agent")

    if not name_arg:
        name_arg = default_greet_name
        
    await ctx.output.send_message(f"Hello, {name_arg} from Main Agent!", style="bold magenta")
    await ctx.output.send_data({"recipient": name_arg, "message": "Hello from Main Agent"}, format_hint="json")

async def _cmd_agentinfo(ctx: CommandContext):
    """Shows information about the current agent's configuration."""
    agent_config = ctx.app_services['raw_app_config'].get('agents', {}).get(ctx.agent_name, {})
    await ctx.output.send_message(f"--- {ctx.agent_name} Agent Configuration ---", style="bold blue")
    await ctx.output.send_data(agent_config, format_hint="json")

async def _cmd_help(ctx: CommandContext, command_defs: List[CommandDefinition]):
    """Shows help for Main Agent commands."""
    await ctx.output.send_message(f"--- {ctx.agent_name} Agent Commands ---", style="bold cyan")
    if not command_defs:
        await ctx.output.send_message("No commands available in this agent.", style="italic")
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

async def _main_agent_non_command_processor(
    raw_input_str: str,
    command_input: AbstractCommandInput,
    app_services: AppServices,
    agent_name: str
):
    """Handles input that isn't a recognized command in main agent."""
    logger.debug(f"Main agent non-command input: {raw_input_str}")
    output_handler = app_services['output_handler']
    await output_handler.send_message(
        f"Main Agent received: '{raw_input_str}'. This is not a known command. Type 'help'.",
        style="italic yellow"
    )

# --- Agent Composition Function ---

AgentInputHandlerFunc = Callable[[str, AbstractCommandInput, AppServices], Awaitable[None]]
AgentLogicComponents = Tuple[AgentInputHandlerFunc, List[CommandDefinition], Optional[Callable[[AppServices, str], Awaitable[None]]], Optional[Callable[[AppServices, str], Awaitable[None]]]]

def create_main_agent_logic(
    agent_config: Dict[str, Any], # Specific config for this agent instance
    app_services: AppServices   # Global application services
) -> AgentLogicComponents:
    """
    Composition function for the Main Agent.

    Returns a tuple containing:
    1.  agent_input_handler_func: The primary input handler for this agent.
    2.  command_definitions: A list of CommandDefinition objects for this agent.
    3.  on_enter_hook (Optional): An async function called when the agent is entered.
    4.  on_exit_hook (Optional): An async function called when the agent is exited.
    """
    MODE_NAME = agent_config.get("name", "main")

    # Define CommandDefinitions
    main_agent_commands: List[CommandDefinition] = [
        CommandDefinition(
            name="greet",
            command_function=_cmd_greet,
            description="Greets the user or a specified name.",
            parameters=[
                ParameterDefinition(name="name", param_type=str, description="The name to greet.", required=False)
            ],
            aliases=["hello"],
            category="MainAgent"
        ),
        CommandDefinition(
            name="agentinfo",
            command_function=_cmd_agentinfo,
            description="Shows information about the current agent's configuration.",
            category="MainAgent"
        ),
        # The help command needs access to the list of command definitions
        # We'll pass it via a partial or closure within the input handler
    ]
    
    # Special handling for help command to pass its own command list
    async def _cmd_help_with_context(ctx: CommandContext):
        await _cmd_help(ctx, main_agent_commands)

    main_agent_commands.append(
        CommandDefinition(
            name="help",
            command_function=_cmd_help_with_context, # Use the wrapped version
            description="Shows help for Main Agent commands.",
            category="MainAgent"
        )
    )
    
    # Create a command map for quick lookup
    command_map: Dict[str, CommandDefinition] = {}
    for cmd_def in main_agent_commands:
        command_map[cmd_def.name] = cmd_def
        for alias in cmd_def.aliases:
            command_map[alias] = cmd_def

    async def main_agent_input_handler(
        raw_input_str: str,
        command_input: AbstractCommandInput, # Provided by the top-level app handler
        # app_services_for_agent: AppServices # Already available in closure
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
                    agent_name=MODE_NAME,
                    loop=asyncio.get_running_loop(),
                    parsed_args=parsed_args
                )
                await cmd_to_run.command_function(ctx)
            except ArgumentParsingError as ape:
                logger.error(f"Argument parsing error for command '{cmd_word}': {ape}", exc_info=False)
                await output_handler.send_error(f"Error: {ape}", details=f"Usage: {cmd_word} " + " ".join([f"<{p.name}>" if p.required else f"[{p.name}]" for p in cmd_to_run.parameters]))
            except Exception as e:
                logger.error(f"Error executing command '{cmd_word}' in {MODE_NAME} agent: {e}", exc_info=True)
                await output_handler.send_error(f"An unexpected error occurred in command '{cmd_word}'.", details=str(e))
        else:
            # Not a known command for this agent, call the non-command processor
            await _main_agent_non_command_processor(raw_input_str, command_input, app_services, MODE_NAME)

    async def on_enter_hook(current_app_services: AppServices, agent_name_entered: str):
        logger.info(f"Entering {agent_name_entered} Agent (via main_agent_logic).")
        await current_app_services['output_handler'].send_message(
            f"Welcome to {agent_name_entered} Agent! Type 'help' for agent commands or '/help' for global commands.",
            style="bold blue"
        )

    async def on_exit_hook(current_app_services: AppServices, agent_name_exited: str):
        logger.info(f"Exiting {agent_name_exited} Agent (via main_agent_logic).")
        # Perform any cleanup specific to this agent if needed in the future

    return main_agent_input_handler, main_agent_commands, on_enter_hook, on_exit_hook