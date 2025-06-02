#%%
# pocket_commander/app_core.py
import asyncio
import logging
import uuid # For generating IDs
from typing import Dict, List, Callable, Awaitable, Any, Optional

from pocket_commander.commands.definition import CommandDefinition, ParameterDefinition
from pocket_commander.commands.io import AbstractCommandInput 
from pocket_commander.commands.terminal_io import StringCommandInput # For parsing global command args
from pocket_commander.commands.core import CommandContext
from pocket_commander.commands.parser import parse_arguments, ArgumentParsingError
from pocket_commander.types import AppServices, AgentConfig
from pocket_commander.commands.builtin_commands import get_builtin_commands
from pocket_commander.tools.registry import create_agent_tool_registry

# Import new event and type system
from pocket_commander.events import (
    AppInputEvent, # New event for UI input
    AgentLifecycleEvent,
    InternalExecuteToolRequest,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    MessagesSnapshotEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
)
from pocket_commander.ag_ui import types as ag_ui_types
from pocket_commander.ag_ui import events as ag_ui_events
# Removed TerminalInteractionFlow, importing TerminalAgUIClient
# from pocket_commander.flows.terminal_interaction_flow import TerminalInteractionFlow # This will be removed

logger = logging.getLogger(__name__)


class AppCore:
    """
    Manages the core application logic, agent lifecycle, global commands,
    and orchestrates event flows based on ag_ui principles.
    """
    def __init__(self, initial_app_services: AppServices):
        self.app_services: AppServices = initial_app_services
        self.event_bus = initial_app_services.event_bus
        if not self.event_bus:
            raise ValueError("Event bus not initialized in AppServices.")

        self.application_state: Dict[str, Any] = {
            "global_commands": {}, # Dict[str, CommandDefinition]
            "active_agent_name": None,
            "active_agent_instance": None,
            "available_agents": initial_app_services.raw_app_config.get('resolved_agents', {}),
            "pending_tool_call_starts": {}, # Dict[str, ToolCallStartEvent]
            "pending_tool_call_args": {},   # Dict[str, str]
        }
        # Provide access to application_state for AppStateAwareCompleter if needed (via app_services)
        self.app_services._application_state_DO_NOT_USE_DIRECTLY = self.application_state
        self.ui_client: Optional[Any] = None # Will be TerminalAgUIClient instance

    # --- Public methods for AppServices ---
    def get_current_agent_slug(self) -> Optional[str]:
        """Returns the slug of the currently active agent."""
        return self.application_state.get("active_agent_name")

    def get_available_agents(self) -> List[str]:
        """Returns a list of slugs for all available agents."""
        return list(self.application_state["available_agents"].keys())

    async def request_agent_switch(self, agent_slug: str) -> bool:
        """Requests to switch to the specified agent."""
        return await self._switch_to_agent(agent_slug)
    # --- End Public methods for AppServices ---

    async def _publish_system_text_message(self, content: str):
        message_id = str(uuid.uuid4())
        await self.event_bus.publish(TextMessageStartEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_START, message_id=message_id, role="system"))
        if content:
            await self.event_bus.publish(TextMessageContentEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=content))
        await self.event_bus.publish(TextMessageEndEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_END, message_id=message_id))
        logger.info(f"System message (ID: {message_id}): {content}")

    # --- Event Handlers for Tool Call Orchestration ---
    async def _handle_tool_call_start(self, event: ToolCallStartEvent):
        logger.debug(f"AppCore: Received ToolCallStartEvent for ID {event.tool_call_id}, Name: {event.tool_name}")
        self.application_state["pending_tool_call_starts"][event.tool_call_id] = event
        self.application_state["pending_tool_call_args"][event.tool_call_id] = ""

    async def _handle_tool_call_args(self, event: ToolCallArgsEvent):
        logger.debug(f"AppCore: Received ToolCallArgsEvent for ID {event.tool_call_id}, Delta: {event.delta[:50]}...")
        if event.tool_call_id in self.application_state["pending_tool_call_args"]:
            self.application_state["pending_tool_call_args"][event.tool_call_id] += event.delta
        else:
            logger.warning(f"AppCore: Received ToolCallArgsEvent for unknown tool_call_id {event.tool_call_id}")

    async def _handle_tool_call_end(self, event: ToolCallEndEvent):
        logger.debug(f"AppCore: Received ToolCallEndEvent for ID {event.tool_call_id}")
        
        start_event = self.application_state["pending_tool_call_starts"].pop(event.tool_call_id, None)
        accumulated_args = self.application_state["pending_tool_call_args"].pop(event.tool_call_id, None)

        if not start_event or accumulated_args is None:
            logger.error(f"AppCore: Could not find start/args for ToolCallEndEvent ID {event.tool_call_id}.")
            return

        await self.event_bus.publish(
            InternalExecuteToolRequest(
                tool_call_id=event.tool_call_id,
                tool_name=start_event.tool_name,
                arguments_json=accumulated_args,
                parent_message_id=start_event.parent_message_id # type: ignore
            )
        )
        logger.info(f"AppCore: Published InternalExecuteToolRequest for tool '{start_event.tool_name}' (Call ID: {event.tool_call_id})")

    # --- AgentSwitching Logic ---
    async def _switch_to_agent(self, agent_slug_to_activate: str) -> bool:
        current_active_agent_slug = self.application_state.get("active_agent_name")

        if agent_slug_to_activate == current_active_agent_slug:
            await self._publish_system_text_message(f"Already in '{agent_slug_to_activate}' agent.")
            return True

        agent_config_obj: Optional[AgentConfig] = self.application_state["available_agents"].get(agent_slug_to_activate)
        
        if not agent_config_obj:
            await self._publish_system_text_message(f"Agent '{agent_slug_to_activate}' not found.")
            return False

        if current_active_agent_slug:
            logger.info(f"Deactivating agent: {current_active_agent_slug}")
            await self.event_bus.publish(
                AgentLifecycleEvent(agent_name=current_active_agent_slug, lifecycle_type="deactivating")
            )
            # TODO: Call agent's deactivate method if it exists
            self.application_state["active_agent_instance"] = None 

        try:
            logger.info(f"Activating agent: {agent_slug_to_activate} from path {agent_config_obj.path}")
            current_init_args = agent_config_obj.init_args.copy() if agent_config_obj.init_args else {}
            
            tool_names_config = current_init_args.pop("tool_names", None)
            if tool_names_config is not None:
                 agent_specific_tool_registry = create_agent_tool_registry(
                    agent_slug=agent_slug_to_activate,
                    agent_tools_config=tool_names_config,
                    global_registry=self.app_services.global_tool_registry
                )
                 current_init_args["agent_tool_registry"] = agent_specific_tool_registry
            else:
                current_init_args["agent_tool_registry"] = self.app_services.global_tool_registry

            agent_instance: Optional[Any] = None
            if agent_config_obj.target_composition_function:
                if asyncio.iscoroutinefunction(agent_config_obj.target_composition_function):
                    agent_instance = await agent_config_obj.target_composition_function(self.app_services, current_init_args)
                else:
                    agent_instance = agent_config_obj.target_composition_function(self.app_services, current_init_args)
            elif agent_config_obj.target_class:
                agent_instance = agent_config_obj.target_class(app_services=self.app_services, **current_init_args)
            
            if not agent_instance:
                raise ValueError("Agent target did not yield valid instance.")

            self.application_state["active_agent_instance"] = agent_instance
            self.application_state["active_agent_name"] = agent_slug_to_activate
            
            if hasattr(agent_instance, 'activate') and callable(agent_instance.activate): # type: ignore
                await agent_instance.activate() # type: ignore
            else:
                logger.warning(f"Agent '{agent_slug_to_activate}' has no 'activate' method.")

            logger.info(f"Agent '{agent_slug_to_activate}' instance created. Publishing 'activating' lifecycle event.")
            await self.event_bus.publish(
                AgentLifecycleEvent(agent_name=agent_slug_to_activate, lifecycle_type="activating")
            )
            await self._publish_system_text_message(f"Switched to '{agent_slug_to_activate}' agent.")
        except Exception as e:
            logger.error(f"Error switching/initializing agent '{agent_slug_to_activate}': {e}", exc_info=True)
            await self._publish_system_text_message(f"Error initializing agent '{agent_slug_to_activate}'.")
            self.application_state["active_agent_name"] = None
            self.application_state["active_agent_instance"] = None
            return False
        return True

    # --- Global Command Functions ---
    async def _cmd_global_exit(self, ctx: CommandContext):
        await self._publish_system_text_message("Exiting Pocket Commander...")
        raise SystemExit("User requested exit via /exit command.") 

    async def _cmd_global_help(self, ctx: CommandContext):
        await self._publish_system_text_message("--- Global Commands ---")
        global_cmds_help = []
        for name, cmd_def in self.application_state["global_commands"].items():
            if name == cmd_def.name: # Avoid listing aliases multiple times
                desc = cmd_def.description or "No description"
                params_str = ""
                if cmd_def.parameters:
                    params_list = [f"<{p.name}>" if p.required else f"[{p.name}]" for p in cmd_def.parameters]
                    params_str = " " + " ".join(params_list)
                aliases_str = f" (Aliases: {', '.join(cmd_def.aliases)})" if cmd_def.aliases else ""
                global_cmds_help.append(f"  /{name}{params_str:<25} - {desc}{aliases_str}")
        if global_cmds_help:
            await self._publish_system_text_message("\n".join(global_cmds_help))
        await self._publish_system_text_message("Type 'help' to the active agent for its usage.")

    async def _cmd_global_agents(self, ctx: CommandContext):
        await self._publish_system_text_message("--- Available Agents ---")
        if not self.application_state["available_agents"]:
            await self._publish_system_text_message("No agents configured.")
            return
        agent_lines = []
        for agent_slug, agent_conf_obj in self.application_state["available_agents"].items():
            desc = agent_conf_obj.description or "No description."
            is_active = " (active)" if agent_slug == self.application_state["active_agent_name"] else ""
            agent_lines.append(f"  {agent_slug:<15} - {desc}{is_active}")
        if agent_lines:
            await self._publish_system_text_message("\n".join(agent_lines))

    async def _cmd_global_agent_switch(self, ctx: CommandContext):
        target_agent_slug = getattr(ctx, 'parsed_args', {}).get("agent_name")
        if not target_agent_slug:
            await self._publish_system_text_message("Usage: /agent <agent_name>")
            return
        await self._switch_to_agent(target_agent_slug)

    def _register_global_commands(self):
        global_command_definitions: List[CommandDefinition] = [
            *get_builtin_commands(),
            CommandDefinition(name="exit", handler=self._cmd_global_exit, description="Exits Pocket Commander.", aliases=["quit", "q"], category="Global"),
            CommandDefinition(name="help", handler=self._cmd_global_help, description="Shows global commands help.", aliases=["?"], category="Global"),
            CommandDefinition(name="agents", handler=self._cmd_global_agents, description="Lists available agents.", category="Global"),
            CommandDefinition(
                name="agent",
                handler=self._cmd_global_agent_switch,
                description="Switches to a specified agent.",
                parameters=[ParameterDefinition(name="agent_name", param_type=str, description="The agent's name.")],
                category="Global"
            ),
        ]
        for cmd_def in global_command_definitions:
            self.application_state["global_commands"][cmd_def.name] = cmd_def
            for alias in cmd_def.aliases:
                self.application_state["global_commands"][alias] = cmd_def
    
    async def initialize_core(self):
        """Initializes the AppCore, subscribes to events, and sets up global commands."""
        # Subscribe to tool call events for orchestration
        await self.event_bus.subscribe(ToolCallStartEvent, self._handle_tool_call_start)
        await self.event_bus.subscribe(ToolCallArgsEvent, self._handle_tool_call_args)
        await self.event_bus.subscribe(ToolCallEndEvent, self._handle_tool_call_end)
        logger.info("AppCore subscribed to ToolCall Start/Args/End events.")

        # Subscribe to AppInputEvent from UI Clients
        await self.event_bus.subscribe(AppInputEvent, self._handle_app_input)
        logger.info("AppCore subscribed to AppInputEvent.")

        self._register_global_commands()

        # Load Initial Agent
        default_agent_slug = self.app_services.raw_app_config.get('application', {}).get('default_agent', None)
        if default_agent_slug:
            if not self.application_state["available_agents"]:
                 logger.warning("No agents loaded, cannot switch to default agent.")
            else:
                await self._switch_to_agent(default_agent_slug)
        else:
            logger.info("No default agent specified.")
            await self._publish_system_text_message("No default agent. Use '/agents' and '/agent <name>'.")

    # --- New AppInputEvent Handler ---
    async def _handle_app_input(self, event: AppInputEvent):
        raw_input_str = event.input_text.strip()
        logger.debug(f"AppCore received AppInputEvent from '{event.source_ui_client_id}': '{raw_input_str}'")

        potential_cmd_word_full = raw_input_str.split(" ", 1)[0]

        if potential_cmd_word_full.startswith("/"):
            global_cmd_word = potential_cmd_word_full[1:]
            
            if global_cmd_word in self.application_state["global_commands"]:
                cmd_to_run = self.application_state["global_commands"][global_cmd_word]
                args_string = raw_input_str.partition(" ")[2] # Get the rest of the string as args
                
                # For global commands, use StringCommandInput for parsing
                temp_cmd_input = StringCommandInput(args_string)
                
                try:
                    parsed_args = await parse_arguments(temp_cmd_input, cmd_to_run.parameters)
                    
                    # Create CommandContext. For global commands, output_handler is less relevant
                    # as they now publish events. AbstractCommandInput is also less relevant here.
                    # We pass a dummy or None if the handler doesn't strictly need it.
                    # However, _cmd_global_exit might use it if it prompts.
                    # For now, creating a basic context.
                    prompt_function = getattr(self.app_services.output_handler, 'prompt_for_input', lambda prompt, sensitive: asyncio.sleep(0, result="dummy_prompt"))

                    ctx = CommandContext(
                        input=temp_cmd_input,
                        output=self.app_services.output_handler, # Legacy, should be phased out
                        prompt_func=prompt_function,
                        app_services=self.app_services,
                        agent_name="global", # Global commands don't have a specific agent context
                        loop=asyncio.get_event_loop(),
                        parsed_args=parsed_args
                    )

                    await cmd_to_run.handler(ctx)
                except ArgumentParsingError as ape:
                    logger.error(f"Arg parsing error for global cmd '{global_cmd_word}': {ape}", exc_info=False)
                    usage = " ".join([f"<{p.name}>" if p.required else f"[{p.name}]" for p in cmd_to_run.parameters])
                    await self._publish_system_text_message(f"Error: {ape}. Usage: /{global_cmd_word} {usage}")
                except SystemExit:
                    raise # Propagate SystemExit to stop the application
                except Exception as e:
                    logger.error(f"Error executing global cmd '{global_cmd_word}': {e}", exc_info=True)
                    await self._publish_system_text_message(f"Error in global command '{global_cmd_word}'.")
                return 

        # If not a global command, treat as input for the active agent
        active_agent_slug = self.application_state.get("active_agent_name")
        if active_agent_slug:
            run_id = str(uuid.uuid4())
            # Use agent_slug as thread_id for simplicity, or a more persistent ID if available
            thread_id = active_agent_slug 
            
            logger.info(f"Publishing RunStartedEvent for agent '{active_agent_slug}', Run ID: {run_id}, Input: {raw_input_str[:50]}...")
            await self.event_bus.publish(RunStartedEvent(type=ag_ui_events.EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id))
            
            user_message_id = str(uuid.uuid4())
            # Ensure content is not empty if raw_input_str is just whitespace
            content_to_send = raw_input_str if raw_input_str else "" 
            user_message = ag_ui_types.UserMessage(
                id=user_message_id,
                role="user",
                content=content_to_send 
            )
            
            await self.event_bus.publish(MessagesSnapshotEvent(type=ag_ui_events.EventType.MESSAGES_SNAPSHOT, messages=[user_message]))
            logger.info(f"Published MessagesSnapshotEvent with UserMessage (ID: {user_message_id}) for Run ID: {run_id}")
        elif not (potential_cmd_word_full.startswith("/")): 
            await self._publish_system_text_message(f"No active agent for input: '{raw_input_str}'. Use '/agent <name>'.")


async def create_application_core(initial_app_services: AppServices) -> AppCore:
    """
    Creates and initializes the core application logic.
    """
    app_core_instance = AppCore(initial_app_services)
    await app_core_instance.initialize_core()
    return app_core_instance