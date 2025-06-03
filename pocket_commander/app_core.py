#%%
# pocket_commander/app_core.py
import inspect
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
    RunFinishedEvent, # Not currently published by app_core, but good to keep for consistency
    RunErrorEvent,   # Not currently published by app_core
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

# Import ZeroMQEventBus for type hinting, but AppCore will receive it
from pocket_commander.event_bus import ZeroMQEventBus # MODIFIED: For type hint
from pocket_commander.ag_ui.types import InternalBaseEvent # For _publish_event type hint
# from pocket_commander.config_loader import AppConfig # Not strictly needed here, but good for type context if AppServices was typed

logger = logging.getLogger(__name__)


from pocket_commander.ag_ui.client import AbstractAgUIClient # AI! Add import

class AppCore:
    ui_client: Optional[AbstractAgUIClient] = None # AI! Add ui_client attribute
    """
    Manages the core application logic, agent lifecycle, global commands,
    and orchestrates event flows based on ag_ui principles.
    Uses ZeroMQEventBus for event communication, provided via AppServices.
    """
    def __init__(self, initial_app_services: AppServices):
        self.app_services: AppServices = initial_app_services
        
        # MODIFIED: Event bus is now provided by main.py via AppServices
        if not initial_app_services.event_bus:
            # This should ideally not happen if main.py initializes it correctly
            logger.critical("EventBus not provided in AppServices during AppCore initialization!")
            # Fallback or raise error, for now, logging critical.
            # Depending on strictness, could raise an Exception.
            # For robustness in case of misconfiguration, a dummy bus could be used,
            # but the expectation is that main.py provides a live ZeroMQEventBus.
            raise ValueError("AppCore requires an EventBus instance in AppServices.")
        
        self.event_bus: ZeroMQEventBus = initial_app_services.event_bus # type: ignore

        self.application_state: Dict[str, Any] = {
            "global_commands": {}, # Dict[str, CommandDefinition]
            "active_agent_name": None,
            "active_agent_instance": None,
            "available_agents": getattr(initial_app_services.raw_app_config, 'resolved_agents', {}) if initial_app_services.raw_app_config else {},
            "pending_tool_call_starts": {}, # Dict[str, ToolCallStartEvent]
            "pending_tool_call_args": {},   # Dict[str, str]
        }
        self.app_services._application_state_DO_NOT_USE_DIRECTLY = self.application_state
        self.ui_client: Optional[Any] = None # Will be TerminalAgUIClient instance

    # --- Event Publishing Helper ---
    async def _publish_event(self, event_instance: InternalBaseEvent):
        """Helper to publish Pydantic events via ZeroMQEventBus.
        Uses specific hierarchical topics for ag_ui.events as per requirements.
        """
        topic: str
        
        # [MEMORY BANK: ACTIVE]
        if isinstance(event_instance, ag_ui_events.BaseEvent) and \
           hasattr(event_instance, 'type') and \
           isinstance(event_instance.type, ag_ui_events.EventType): # Check type attribute is EventType
            
            event_type_enum_member = event_instance.type # This is the ag_ui_events.EventType enum member
            
            # Specific topics as per task requirements for ag_ui.events published by AppCore
            specific_topic_map = {
                ag_ui_events.EventType.TEXT_MESSAGE_START: "ag_ui.text_message.start",
                ag_ui_events.EventType.TEXT_MESSAGE_CONTENT: "ag_ui.text_message.content",
                ag_ui_events.EventType.TEXT_MESSAGE_END: "ag_ui.text_message.end",
                ag_ui_events.EventType.RUN_STARTED: "ag_ui.run.started",
                ag_ui_events.EventType.MESSAGES_SNAPSHOT: "ag_ui.messages.snapshot",
                
                # Added as per Stage 4 requirements for AppCore publishing to UI
                ag_ui_events.EventType.TOOL_CALL_START: "ag_ui.tool_call.start",
                ag_ui_events.EventType.TOOL_CALL_ARGS: "ag_ui.tool_call.args",
                ag_ui_events.EventType.TOOL_CALL_END: "ag_ui.tool_call.end",
                ag_ui_events.EventType.RUN_ERROR: "ag_ui.run.error",
                ag_ui_events.EventType.STEP_STARTED: "ag_ui.step.started",
                ag_ui_events.EventType.STEP_FINISHED: "ag_ui.step.finished",
                ag_ui_events.EventType.REQUEST_PROMPT: "RequestPromptEvent", # Per spec, topic is "RequestPromptEvent"
            }
            
            if event_type_enum_member in specific_topic_map:
                topic = specific_topic_map[event_type_enum_member]
            else:
                # Generic hierarchical topic for other ag_ui.events not in the specific map
                # This converts ENUM_VALUE_NAME to ag_ui.enum.value.name
                generic_topic_suffix = event_type_enum_member.value.lower().replace('_', '.')
                topic = f"{ag_ui_events.AG_UI_EVENT_PREFIX}.{generic_topic_suffix}"
                logger.info(
                    f"Using generic hierarchical topic '{topic}' for ag_ui event type: {event_type_enum_member}. "
                    f"If a specific topic is required by protocol, add to specific_topic_map."
                )
        else:
            # For non-ag_ui_events (like InternalExecuteToolRequest) or events not matching the ag_ui.BaseEvent structure
            topic = type(event_instance).__name__ # Original fallback, e.g., "InternalExecuteToolRequest"
        
        event_data_dict = event_instance.model_dump(mode='json')
        await self.event_bus.publish(topic, event_data_dict)

    # --- Public methods for AppServices ---
    def get_current_agent_slug(self) -> Optional[str]:
        return self.application_state.get("active_agent_name")

    def get_available_agents(self) -> List[str]:
        return list(self.application_state["available_agents"].keys())

    async def request_agent_switch(self, agent_slug: str) -> bool:
        return await self._switch_to_agent(agent_slug)
    # --- End Public methods for AppServices ---

    async def _publish_system_text_message(self, content: str):
        message_id = str(uuid.uuid4())
        # [MEMORY BANK: ACTIVE]
        await self._publish_event(TextMessageStartEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_START, message_id=message_id, role="system"))
        if content:
            # [MEMORY BANK: ACTIVE]
            await self._publish_event(TextMessageContentEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=content))
        # [MEMORY BANK: ACTIVE]
        await self._publish_event(TextMessageEndEvent(type=ag_ui_events.EventType.TEXT_MESSAGE_END, message_id=message_id))
        logger.info(f"System message (ID: {message_id}): {content}")

    # --- ZMQ Event Handlers for Tool Call Orchestration ---
    async def _handle_tool_call_start_zmq(self, topic: str, data: dict):
        try:
            event = ToolCallStartEvent(**data)
            logger.debug(f"AppCore ZMQ: Received ToolCallStartEvent for ID {event.tool_call_id}, Name: {event.tool_name} on topic {topic}")
            self.application_state["pending_tool_call_starts"][event.tool_call_id] = event
            self.application_state["pending_tool_call_args"][event.tool_call_id] = ""
        except Exception as e:
            logger.error(f"AppCore ZMQ: Error processing ToolCallStartEvent data: {e}. Data: {data}", exc_info=True)

    async def _handle_tool_call_args_zmq(self, topic: str, data: dict):
        try:
            event = ToolCallArgsEvent(**data)
            logger.debug(f"AppCore ZMQ: Received ToolCallArgsEvent for ID {event.tool_call_id}, Delta: {event.delta[:50]}... on topic {topic}")
            if event.tool_call_id in self.application_state["pending_tool_call_args"]:
                self.application_state["pending_tool_call_args"][event.tool_call_id] += event.delta
            else:
                logger.warning(f"AppCore ZMQ: Received ToolCallArgsEvent for unknown tool_call_id {event.tool_call_id}")
        except Exception as e:
            logger.error(f"AppCore ZMQ: Error processing ToolCallArgsEvent data: {e}. Data: {data}", exc_info=True)
            
    async def _handle_tool_call_end_zmq(self, topic: str, data: dict):
        try:
            event = ToolCallEndEvent(**data)
            logger.debug(f"AppCore ZMQ: Received ToolCallEndEvent for ID {event.tool_call_id} on topic {topic}")
            
            start_event = self.application_state["pending_tool_call_starts"].pop(event.tool_call_id, None)
            accumulated_args = self.application_state["pending_tool_call_args"].pop(event.tool_call_id, None)

            if not start_event or accumulated_args is None:
                logger.error(f"AppCore ZMQ: Could not find start/args for ToolCallEndEvent ID {event.tool_call_id}.")
                return

            # Publishing InternalExecuteToolRequest still uses _publish_event.
            # Its topic will be "InternalExecuteToolRequest" due to the else clause in _publish_event.
            # [MEMORY BANK: ACTIVE]
            await self._publish_event(
                InternalExecuteToolRequest(
                    tool_call_id=event.tool_call_id,
                    tool_name=start_event.tool_name,
                    arguments_json=accumulated_args,
                    parent_message_id=start_event.parent_message_id # type: ignore
                )
            )
            logger.info(f"AppCore ZMQ: Published InternalExecuteToolRequest for tool '{start_event.tool_name}' (Call ID: {event.tool_call_id})")
        except Exception as e:
            logger.error(f"AppCore ZMQ: Error processing ToolCallEndEvent data: {e}. Data: {data}", exc_info=True)

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

        lifecycle_topic = "app.agent.lifecycle" # MODIFIED: Defined topic

        if current_active_agent_slug:
            logger.info(f"Deactivating agent: {current_active_agent_slug}")
            # MODIFIED: Direct publish for AgentLifecycleEvent
            deactivating_event = AgentLifecycleEvent(agent_name=current_active_agent_slug, lifecycle_type="deactivating")
            # [MEMORY BANK: ACTIVE]
            await self.event_bus.publish(lifecycle_topic, deactivating_event.model_dump(mode='json'))
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
            # MODIFIED: Direct publish for AgentLifecycleEvent
            activating_event = AgentLifecycleEvent(agent_name=agent_slug_to_activate, lifecycle_type="activating")
            # [MEMORY BANK: ACTIVE]
            await self.event_bus.publish(lifecycle_topic, activating_event.model_dump(mode='json'))
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
        if self.ui_client:
            logger.info("AppCore: /exit command received, calling ui_client.stop()")
            await self.ui_client.stop()
            # By stopping the UI client, its _main_loop_task will end.
            # main.py is awaiting this task, so it will proceed to its finally block for shutdown.
            # No need to raise SystemExit here anymore, as that was causing issues with task context.
        else:
            logger.warning("AppCore: /exit command received, but no ui_client is set. Raising SystemExit as fallback.")
            raise SystemExit("User requested exit via /exit command, ui_client not available.") 

    async def _cmd_global_help(self, ctx: CommandContext):
        await self._publish_system_text_message("--- Global Commands ---")
        global_cmds_help = []
        for name, cmd_def in self.application_state["global_commands"].items():
            if name == cmd_def.name: 
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
            await self._cmd_global_agents(ctx)
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
                description="Switches to a specified agent, or lists available agents if no name is provided.",
                parameters=[ParameterDefinition(name="agent_name", param_type=str, description="The agent's name. If omitted, lists available agents.", required=False)],
                category="Global"
            ),
        ]
        for cmd_def in global_command_definitions:
            self.application_state["global_commands"][cmd_def.name] = cmd_def
            for alias in cmd_def.aliases:
                self.application_state["global_commands"][alias] = cmd_def
    
    async def initialize_core(self):
        """Initializes the AppCore, subscribes to events, and sets up global commands.
        Assumes self.event_bus is already started by the creator of AppCore (e.g., main.py).
        """
        # MODIFIED: Event bus start is managed by main.py
        # await self.event_bus.start() 
        # logger.info("AppCore's ZeroMQEventBus started.") # Removed

        # Subscribe to tool call events for orchestration
        # These topics are class names, can be changed to hierarchical if desired later
        # [MEMORY BANK: ACTIVE]
        await self.event_bus.subscribe(ToolCallStartEvent.__name__, self._handle_tool_call_start_zmq)
        # [MEMORY BANK: ACTIVE]
        await self.event_bus.subscribe(ToolCallArgsEvent.__name__, self._handle_tool_call_args_zmq)
        # [MEMORY BANK: ACTIVE]
        await self.event_bus.subscribe(ToolCallEndEvent.__name__, self._handle_tool_call_end_zmq)
        logger.info("AppCore subscribed to ToolCall Start/Args/End events via ZMQ.")

        # MODIFIED: Subscribe to AppInputEvent from UI Clients using new topic
        app_input_topic = "app.ui.input"
        # [MEMORY BANK: ACTIVE]
        await self.event_bus.subscribe(topic_pattern=app_input_topic, handler_coroutine=self._handle_app_input_zmq)
        logger.info(f"AppCore subscribed to AppInputEvent on topic '{app_input_topic}' via ZMQ.")

        self._register_global_commands()

        default_agent_slug = None
        if self.app_services.raw_app_config and hasattr(self.app_services.raw_app_config, 'application') and self.app_services.raw_app_config.application:
            default_agent_slug = self.app_services.raw_app_config.application.default_agent
        
        if default_agent_slug:
            if not self.application_state["available_agents"]:
                 logger.warning("No agents loaded, cannot switch to default agent.")
            else:
                await self._switch_to_agent(default_agent_slug)
        else:
            logger.info("No default agent specified.")
            await self._publish_system_text_message("No default agent. Use '/agents' and '/agent <name>'.")

    # --- ZMQ AppInputEvent Handler ---
    async def _handle_app_input_zmq(self, topic: str, event_data: dict): # MODIFIED: param name to event_data for clarity
        try:
            # event_data is the raw dict from ZMQ, AppInputEvent.model_validate handles parsing
            event = AppInputEvent.model_validate(event_data) # Use model_validate for Pydantic v2
            raw_input_str = event.input_text.strip()
            logger.debug(f"AppCore ZMQ received AppInputEvent from '{event.source_ui_client_id}': '{raw_input_str}' on topic '{topic}'")

            potential_cmd_word_full = raw_input_str.split(" ", 1)[0]

            if potential_cmd_word_full.startswith("/"):
                global_cmd_word = potential_cmd_word_full[1:]
                
                if global_cmd_word in self.application_state["global_commands"]:
                    cmd_to_run = self.application_state["global_commands"][global_cmd_word]
                    args_string = raw_input_str.partition(" ")[2] 
                    
                    temp_cmd_input = StringCommandInput(args_string)
                    
                    try:
                        parsed_args = await parse_arguments(temp_cmd_input, cmd_to_run.parameters)
                        
                        prompt_function = getattr(self.app_services.output_handler, 'prompt_for_input', lambda prompt, sensitive: asyncio.sleep(0, result="dummy_prompt"))

                        ctx = CommandContext(
                            input=temp_cmd_input,
                            output=self.app_services.output_handler, 
                            prompt_func=prompt_function,
                            app_services=self.app_services,
                            agent_name="global", 
                            loop=asyncio.get_event_loop(),
                            parsed_args=parsed_args
                        )

                        await cmd_to_run.handler(ctx)
                    except ArgumentParsingError as ape:
                        logger.error(f"Arg parsing error for global cmd '{global_cmd_word}': {ape}", exc_info=False)
                        usage = " ".join([f"<{p.name}>" if p.required else f"[{p.name}]" for p in cmd_to_run.parameters])
                        await self._publish_system_text_message(f"Error: {ape}. Usage: /{global_cmd_word} {usage}")
                    except SystemExit:
                        raise 
                    except Exception as e:
                        logger.error(f"Error executing global cmd '{global_cmd_word}': {e}", exc_info=True)
                        await self._publish_system_text_message(f"Error in global command '{global_cmd_word}'.")
                    return 

            active_agent_slug = self.application_state.get("active_agent_name")
            if active_agent_slug:
                run_id = str(uuid.uuid4())
                thread_id = active_agent_slug 
                
                logger.info(f"Publishing RunStartedEvent for agent '{active_agent_slug}', Run ID: {run_id}, Input: {raw_input_str[:50]}...")
                # Publishing RunStartedEvent now uses _publish_event, which will apply the correct topic.
                # [MEMORY BANK: ACTIVE]
                await self._publish_event(RunStartedEvent(type=ag_ui_events.EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id))
                
                user_message_id = str(uuid.uuid4())
                content_to_send = raw_input_str if raw_input_str else "" 
                user_message = ag_ui_types.UserMessage(
                    id=user_message_id,
                    role="user",
                    content=content_to_send 
                )
                
                # Publishing MessagesSnapshotEvent now uses _publish_event, which will apply the correct topic.
                # [MEMORY BANK: ACTIVE]
                await self._publish_event(MessagesSnapshotEvent(type=ag_ui_events.EventType.MESSAGES_SNAPSHOT, messages=[user_message]))
                logger.info(f"Published MessagesSnapshotEvent with UserMessage (ID: {user_message_id}) for Run ID: {run_id}")
            elif not (potential_cmd_word_full.startswith("/")): 
                await self._publish_system_text_message(f"No active agent for input: '{raw_input_str}'. Use '/agent <name>'.")
        except Exception as e:
            logger.error(f"AppCore ZMQ: Error processing AppInputEvent data: {e}. Data: {event_data}", exc_info=True)

    async def shutdown(self):
        """Gracefully shuts down the AppCore.
        Assumes self.event_bus is stopped by the creator of AppCore (e.g., main.py).
        """
        logger.info("AppCore shutting down...")
        # MODIFIED: Event bus stop is managed by main.py
        # if self.event_bus:
        #     logger.info("Stopping AppCore's ZeroMQEventBus...")
        #     await self.event_bus.stop()
        #     logger.info("AppCore's ZeroMQEventBus stopped.")
        
        if self.application_state.get("active_agent_instance"):
            active_agent_slug = self.application_state.get("active_agent_name")
            logger.info(f"Deactivating final agent '{active_agent_slug}' during shutdown.")
            
            # MODIFIED: Direct publish for AgentLifecycleEvent
            lifecycle_topic = "app.agent.lifecycle"
            deactivating_event = AgentLifecycleEvent(agent_name=str(active_agent_slug), lifecycle_type="deactivating")
            # Ensure event_bus is still available for this last publish
            if self.event_bus and self.event_bus._running: # Check if bus is usable
                 # [MEMORY BANK: ACTIVE]
                 await self.event_bus.publish(lifecycle_topic, deactivating_event.model_dump(mode='json'))
            else:
                logger.warning("Event bus not available or not running during AppCore shutdown, cannot publish final agent deactivation.")

            self.application_state["active_agent_instance"] = None
            self.application_state["active_agent_name"] = None

        logger.info("AppCore shutdown complete.")

async def create_application_core(initial_app_services: AppServices) -> AppCore:
    """
    Creates and initializes the core application logic.
    """
    app_core_instance = AppCore(initial_app_services)
    await app_core_instance.initialize_core()
    return app_core_instance