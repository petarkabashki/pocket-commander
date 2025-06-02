#%%
# pocket_commander/app_core.py
import asyncio
import importlib # Still needed by AgentResolver if not directly here
import logging
from typing import Dict, List, Callable, Awaitable, Any, Optional, Tuple

from pocket_commander.commands.definition import CommandDefinition, ParameterDefinition
from pocket_commander.commands.io import AbstractCommandInput
from pocket_commander.commands.core import CommandContext
from pocket_commander.commands.parser import parse_arguments, ArgumentParsingError
from pocket_commander.types import AppServices, AgentConfig # AgentConfig added
from pocket_commander.commands.builtin_commands import get_builtin_commands
from pocket_commander.tools.registry import create_agent_tool_registry # Added
# Assuming AgentResolver will be used by config_loader, not directly here for now.
# If app_core needs to resolve on the fly (e.g. for dynamic agent loading not from config),
# then AgentResolver would be imported here. For now, assume config_loader provides resolved AgentConfig.
from pocket_commander.events import ( # Added
    AppInputEvent,
    AgentOutputEvent, # Though app_core publishes, it might subscribe for some meta reasons or TIF does
    AgentLifecycleEvent,
    SystemMessageEvent,
    SystemMessageType,
    # RequestPromptEvent, # Agents publish this, TIF subscribes
    # PromptResponseEvent # TIF publishes this, Agents subscribe
)


logger = logging.getLogger(__name__)

# Old type aliases for AgentLogicComponents are removed as the interaction model changes.
# AgentInputHandlerFunc = Callable[[str, AbstractCommandInput, AppServices], Awaitable[None]]
# OnEnterExitHook = Optional[Callable[[AppServices, str], Awaitable[None]]]
# AgentLogicComponents = Tuple[AgentInputHandlerFunc, List[CommandDefinition], OnEnterExitHook, OnEnterExitHook]


async def create_application_core(
    initial_app_services: AppServices
) -> Callable[[str, AbstractCommandInput], Awaitable[Any]]:
    """
    Creates the core application logic and returns a top-level input handler.
    This function sets up global commands, agent management (via events),
    and the primary input processing loop for the application.
    """

    application_state: Dict[str, Any] = {
        "app_services": initial_app_services,
        "global_commands": {}, # Dict[str, CommandDefinition]
        "active_agent_name": None,
        "active_agent_instance": None, # Stores the instantiated Node/Flow agent object
        # "available_agents" will be populated by config_loader with Dict[str, AgentConfig]
        "available_agents": initial_app_services.raw_app_config.get('resolved_agents', {}), # Placeholder name
    }
    # Ensure AppServices has the event_bus initialized by main.py before this point
    event_bus = initial_app_services.event_bus
    if not event_bus:
        # This should not happen if main.py initializes AppServices correctly
        raise ValueError("Event bus not initialized in AppServices.")

    # This hack should be removed once TIF uses events or a better state mechanism
    initial_app_services._application_state_DO_NOT_USE_DIRECTLY = application_state
    
    output_handler = initial_app_services.output_handler # For direct messages from app_core
    prompt_func = initial_app_services.prompt_func # For global command prompts if any

    # --- AgentSwitching Logic ---
    async def _switch_to_agent(agent_slug_to_activate: str) -> bool:
        """
        Attempts to switch to the specified agent using an event-driven approach.
        Returns True on success, False on failure.
        """
        nonlocal application_state
        app_services = application_state["app_services"]
        # event_bus is already available from the outer scope

        current_active_agent_slug = application_state.get("active_agent_name")

        if agent_slug_to_activate == current_active_agent_slug:
            # AgentOutputEvent should be used by TIF, but app_core can send simple status
            await event_bus.publish(SystemMessageEvent(message=f"Already in '{agent_slug_to_activate}' agent.", style="italic", message_type=SystemMessageType.INFO, details=None))
            return True

        # Retrieve the resolved AgentConfig object
        # This assumes config_loader.py has populated initial_app_services.raw_app_config['resolved_agents']
        # with a Dict[str, AgentConfig]
        agent_config_obj: Optional[AgentConfig] = application_state["available_agents"].get(agent_slug_to_activate)
        
        if not agent_config_obj:
            await event_bus.publish(SystemMessageEvent(message=f"Agent '{agent_slug_to_activate}' not found or not configured.", message_type=SystemMessageType.ERROR, style="error", details=None))
            logger.error(f"Agent config for '{agent_slug_to_activate}' not found in resolved_agents.")
            return False

        # 1. Deactivate previous agent (if any)
        if current_active_agent_slug:
            logger.info(f"Deactivating agent: {current_active_agent_slug}")
            await event_bus.publish(
                AgentLifecycleEvent(agent_name=current_active_agent_slug, lifecycle_type="deactivating")
            )
            # Consider if we need to await a "deactivated" event or add a small delay.
            # For now, proceed. The old agent instance will be replaced.
            application_state["active_agent_instance"] = None 
            # The old agent should clean up its own subscriptions upon receiving "deactivating".

        # 2. Instantiate and Setup New Agent
        try:
            logger.info(f"Attempting to activate agent: {agent_slug_to_activate} from path {agent_config_obj.path}")
            
            current_init_args = agent_config_obj.init_args.copy() if agent_config_obj.init_args else {}

            # Tool Registry Setup for the agent
            tool_names_config = current_init_args.pop("tool_names", None) # Convention for tool list
            if tool_names_config is not None: # None means all global, [] means no tools
                 agent_specific_tool_registry = create_agent_tool_registry(
                    agent_slug=agent_slug_to_activate,
                    agent_tools_config=tool_names_config,
                    global_registry=app_services.global_tool_registry
                )
                 # Agent's __init__ or composition_function needs to expect 'agent_tool_registry'
                 current_init_args["agent_tool_registry"] = agent_specific_tool_registry
            else: # Agent gets all global tools by default if "tool_names" is not in init_args
                current_init_args["agent_tool_registry"] = app_services.global_tool_registry


            agent_instance: Optional[Any] = None # Should be BaseNode compatible
            if agent_config_obj.target_composition_function:
                logger.debug(f"Instantiating agent '{agent_slug_to_activate}' using composition function: {agent_config_obj.target_composition_function.__name__}")
                # Ensure the composition function is async if it needs to be
                if asyncio.iscoroutinefunction(agent_config_obj.target_composition_function):
                    agent_instance = await agent_config_obj.target_composition_function(
                        app_services, current_init_args
                    )
                else:
                    agent_instance = agent_config_obj.target_composition_function(
                        app_services, current_init_args
                    )
            elif agent_config_obj.target_class:
                logger.debug(f"Instantiating agent '{agent_slug_to_activate}' using class: {agent_config_obj.target_class.__name__}")
                # Agent class __init__ must accept app_services and then **init_args
                agent_instance = agent_config_obj.target_class(
                    app_services=app_services, **current_init_args
                )
            
            if not agent_instance: # Or check if not isinstance(agent_instance, BaseNode)
                raise ValueError("Agent target (class/function) did not yield a valid agent instance.")

            application_state["active_agent_instance"] = agent_instance
            application_state["active_agent_name"] = agent_slug_to_activate
            
            logger.info(f"Agent '{agent_slug_to_activate}' instance created. Publishing 'activating' event.")
            
            # 3. Publish "activating" event for the new agent
            # The agent is responsible for subscribing to this in its __init__ or a setup method
            # to perform its on-enter logic and subscribe to AppInputEvent etc.
            await event_bus.publish(
                AgentLifecycleEvent(agent_name=agent_slug_to_activate, lifecycle_type="activating")
            )
            # We assume the agent handles "activating" synchronously or its async setup is awaited
            # If agent needs to signal back "activated", a more complex handshake is needed.
            # For now, app_core considers it active after publishing "activating".
            
            # Output a generic message; specific welcome messages should come from the agent via AgentOutputEvent
            await event_bus.publish(SystemMessageEvent(message=f"Switched to '{agent_slug_to_activate}' agent.", style="bold green", message_type=SystemMessageType.SUCCESS, details=None))

        except Exception as e:
            logger.error(f"Error switching to or initializing agent '{agent_slug_to_activate}': {e}", exc_info=True)
            await event_bus.publish(SystemMessageEvent(message=f"Error initializing agent '{agent_slug_to_activate}'. Check logs.", message_type=SystemMessageType.ERROR, style="error", details=None))
            # Revert to no active agent
            application_state["active_agent_name"] = None
            application_state["active_agent_instance"] = None
            # If there was a previous agent, we might try to revert, but that's complex.
            # For now, just go to a no-agent state.
            return False
        
        return True

    # --- Global Command Functions ---
    async def _cmd_global_exit(ctx: CommandContext):
        await event_bus.publish(SystemMessageEvent(message="Exiting Pocket Commander...", style="bold yellow", message_type=SystemMessageType.INFO, details=None))
        raise SystemExit("User requested exit via /exit command.") 

    async def _cmd_global_help(ctx: CommandContext):
        await event_bus.publish(SystemMessageEvent(message="--- Global Commands ---", style="bold cyan", message_type=SystemMessageType.INFO, details=None))
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
        await event_bus.publish(SystemMessageEvent(message="\n".join(global_cmds_help), message_type=SystemMessageType.RAW, details=None, style=None))
        await event_bus.publish(SystemMessageEvent(message="Type 'help' directly to the active agent for its specific commands/usage.", style="italic", message_type=SystemMessageType.INFO, details=None)) # Updated help message

    async def _cmd_global_agents(ctx: CommandContext):
        await event_bus.publish(SystemMessageEvent(message="--- Available Agents ---", style="bold cyan", message_type=SystemMessageType.INFO, details=None))
        # available_agents now stores AgentConfig objects
        if not application_state["available_agents"]:
            await event_bus.publish(SystemMessageEvent(message="No agents configured.", style="italic", message_type=SystemMessageType.INFO, details=None))
            return
        for agent_slug, agent_conf_obj in application_state["available_agents"].items():
            desc = agent_conf_obj.description or "No description available."
            is_active = " (active)" if agent_slug == application_state["active_agent_name"] else ""
            await event_bus.publish(SystemMessageEvent(message=f"  {agent_slug:<15} - {desc}{is_active}", message_type=SystemMessageType.RAW, details=None, style=None))

    async def _cmd_global_agent_switch(ctx: CommandContext):
        target_agent_slug = ctx.parsed_args.get("agent_name")
        if not target_agent_slug:
            await event_bus.publish(SystemMessageEvent(message="No agent name provided.", message_type=SystemMessageType.ERROR, style="error", details="Usage: /agent <agent_name>"))
            return
        await _switch_to_agent(target_agent_slug)

    # --- Define Global Commands ---
    global_command_definitions: List[CommandDefinition] = [
        *get_builtin_commands(),
        CommandDefinition(name="exit", command_function=_cmd_global_exit, description="Exits Pocket Commander.", aliases=["quit", "q"], category="Global"),
        CommandDefinition(name="help", command_function=_cmd_global_help, description="Shows this help message for global commands.", aliases=["?"], category="Global"),
        CommandDefinition(name="agents", command_function=_cmd_global_agents, description="Lists available agents.", category="Global"),
        CommandDefinition(
            name="agent",
            command_function=_cmd_global_agent_switch,
            description="Switches to a specified agent.",
            parameters=[ParameterDefinition(name="agent_name", param_type=str, description="The name of the agent to switch to.")],
            category="Global"
        ),
    ]

    for cmd_def in global_command_definitions:
        application_state["global_commands"][cmd_def.name] = cmd_def
        for alias in cmd_def.aliases:
            application_state["global_commands"][alias] = cmd_def
    
    # --- Load Initial Agent---
    # This assumes config_loader.py has populated initial_app_services.raw_app_config['resolved_agents']
    # And that 'available_agents' in application_state is correctly pointing to it or a copy.
    # For safety, let's re-assign here if config_loader changes initial_app_services post-init of AppServices.
    # This will be refined when config_loader is updated.
    # For now, assume 'available_agents' in application_state is correctly populated by config_loader.
    # application_state["available_agents"] = initial_app_services.raw_app_config.get('resolved_agents', {})

    default_agent_slug = initial_app_services.raw_app_config.get('application', {}).get('default_agent', None)
    if default_agent_slug:
        logger.info(f"Attempting to load default agent. Default slug from config: '{default_agent_slug}'")
        logger.info(f"Available agents at this point: {list(application_state['available_agents'].keys()) if application_state.get('available_agents') else 'None or Empty'}")
        # Ensure available_agents is populated before switching
        if not application_state["available_agents"]:
             logger.warning("No agents resolved/loaded, cannot switch to default agent yet. Config loader needs to run first.")
        else:
            await _switch_to_agent(default_agent_slug)
    else:
        logger.info("No default agent specified. Starting without an active agent.")
        await event_bus.publish(SystemMessageEvent(message="No default agent loaded. Use '/agents' to see available agents and '/agent <name>' to activate one.", style="yellow", message_type=SystemMessageType.WARNING, details=None))


    # --- Top-Level Application Input Handler ---
    async def top_level_app_input_handler(raw_input_str: str, command_input: AbstractCommandInput):
        nonlocal application_state
        app_services = application_state["app_services"]
        # event_bus is already available from the outer scope

        potential_cmd_word_full = command_input.get_command_word() 
        
        if potential_cmd_word_full and potential_cmd_word_full.startswith("/"):
            global_cmd_word = potential_cmd_word_full[1:]
            
            if global_cmd_word in application_state["global_commands"]:
                cmd_to_run = application_state["global_commands"][global_cmd_word]
                try:
                    # Ensure CommandDefinition.handler is used, not .command_function
                    parsed_args = await parse_arguments(command_input, cmd_to_run.parameters)
                    ctx = CommandContext(
                        input=command_input,
                        output=output_handler,
                        prompt_func=prompt_func, # Added: prompt_func is available in this scope
                        app_services=app_services,
                        agent_name=None, # Explicitly None for global commands
                        loop=asyncio.get_running_loop(), # Added
                        parsed_args=parsed_args
                    )
                    await cmd_to_run.command_function(ctx) # Use .handler
                except ArgumentParsingError as ape:
                    logger.error(f"Argument parsing error for global command '{global_cmd_word}': {ape}", exc_info=False)
                    await event_bus.publish(SystemMessageEvent(message=f"Error: {ape}", message_type=SystemMessageType.ERROR, style="error", details=f"Usage: /{global_cmd_word} " + " ".join([f"<{p.name}>" if p.required else f"[{p.name}]" for p in cmd_to_run.parameters])))
                except SystemExit:
                    raise
                except Exception as e:
                    logger.error(f"Error executing global command '{global_cmd_word}': {e}", exc_info=True)
                    await event_bus.publish(SystemMessageEvent(message=f"An unexpected error occurred in global command '{global_cmd_word}'.", details=str(e), message_type=SystemMessageType.ERROR, style=None))
                return 

        # If not a global command, publish an AppInputEvent for the active agent
        active_agent_slug = application_state.get("active_agent_name")
        if active_agent_slug:
            logger.debug(f"Publishing AppInputEvent for agent '{active_agent_slug}': {raw_input_str}")
            await event_bus.publish(
                AppInputEvent(raw_text=raw_input_str, command_input=command_input)
            )
        elif not (potential_cmd_word_full and potential_cmd_word_full.startswith("/")): 
            await event_bus.publish(SystemMessageEvent(message=f"No active agent to handle input: '{raw_input_str}'. Use '/agent <name>' to activate an agent.", style="yellow", message_type=SystemMessageType.WARNING, details=None))
            
    return top_level_app_input_handler