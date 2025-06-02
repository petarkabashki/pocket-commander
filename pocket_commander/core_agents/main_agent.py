import asyncio
import logging
from typing import Dict, Any, Optional

from pocket_commander.pocketflow.base import AsyncNode # Assuming a base class for agents
from pocket_commander.types import AppServices, AgentConfig # AgentConfig for its own info
from pocket_commander.event_bus import AsyncEventBus
from pocket_commander.events import AppInputEvent, AgentOutputEvent, AgentLifecycleEvent
from pocket_commander.commands.io import AbstractCommandInput


logger = logging.getLogger(__name__)

class MainDefaultAgent(AsyncNode): # Or just "Agent" if that's the convention
    """
    The main default agent for Pocket Commander.
    Handles basic interactions and provides general information.
    Interacts via the event bus.
    """

    def __init__(self, app_services: AppServices, **init_args: Any):
        super().__init__() # PocketFlow.AsyncNode init
        self.app_services = app_services
        self.event_bus: AsyncEventBus = app_services.event_bus
        self.init_args = init_args
        self.slug = init_args.get("slug", "main") # Agent needs to know its own slug

        # Agent-specific state can be initialized here
        self.default_greet_name = init_args.get("default_greet_name", "User")
        self._is_active = False # Track activation state
        
        logger.info(f"MainDefaultAgent '{self.slug}' initialized with args: {init_args}")
        
        # Subscribe to events immediately upon initialization
        # This ensures the agent is ready to receive lifecycle events like "activating"
        # even if they are published very early in the app startup.
        if self.event_bus:
            asyncio.create_task(self._subscribe_to_events())
            logger.info(f"MainDefaultAgent '{self.slug}': Event subscription task created in __init__.")
        else:
            logger.error(f"MainDefaultAgent '{self.slug}': Event bus not available in __init__ for creating subscription task.")


    async def _subscribe_to_events(self):
        """Subscribes to necessary events. Called upon activation."""
        # This check is now more of a safeguard, as __init__ also checks.
        if self.event_bus: 
            await self.event_bus.subscribe(AppInputEvent, self.handle_app_input) # type: ignore
            await self.event_bus.subscribe(AgentLifecycleEvent, self.handle_lifecycle_event) # type: ignore
            logger.info(f"MainDefaultAgent '{self.slug}' successfully subscribed to AppInputEvent and AgentLifecycleEvent.")
        else:
            # This path should ideally not be hit if __init__ check passes.
            logger.error(f"MainDefaultAgent '{self.slug}': Event bus not available in _subscribe_to_events.")


    async def handle_lifecycle_event(self, event: AgentLifecycleEvent):
        logger.debug(f"MainDefaultAgent '{self.slug}' received AgentLifecycleEvent: {event.lifecycle_type} for agent '{event.agent_name}'")
        if event.agent_name == self.slug:
            if event.lifecycle_type == "activating" and not self._is_active:
                logger.info(f"MainDefaultAgent '{self.slug}': 'activating' event received, calling on_agent_activate.")
                await self.on_agent_activate()
            elif event.lifecycle_type == "deactivating" and self._is_active:
                logger.info(f"MainDefaultAgent '{self.slug}': 'deactivating' event received, calling on_agent_deactivate.")
                await self.on_agent_deactivate()

    async def on_agent_activate(self):
        """Logic to run when this agent becomes active."""
        # Subscription is now handled in __init__
        # await self._subscribe_to_events() 
        self._is_active = True
        logger.info(f"MainDefaultAgent '{self.slug}' activated.")
        logger.info(f"MainDefaultAgent '{self.slug}': Attempting to publish welcome message.")
        await self.event_bus.publish(
            AgentOutputEvent(
                message="Welcome Valued User from Main Agent! Type '/help' for commands.",
                style="bold blue"
            )
        )

    async def on_agent_deactivate(self):
        """Logic to run when this agent is being deactivated."""
        self._is_active = False
        logger.info(f"MainDefaultAgent '{self.slug}' deactivated.")
        # TODO: Implement unsubscription if event_bus supports it to prevent memory leaks
        # if self.event_bus:
        #     await self.event_bus.unsubscribe(AppInputEvent, self.handle_app_input)
        #     await self.event_bus.unsubscribe(AgentLifecycleEvent, self.handle_lifecycle_event)


    async def handle_app_input(self, event: AppInputEvent):
        """Handles raw input directed to this agent."""
        if not self._is_active: # Only process if active
            logger.debug(f"MainDefaultAgent '{self.slug}' received AppInputEvent but is not active. Ignoring.")
            return

        raw_text = event.raw_text.strip()
        # command_input: AbstractCommandInput = event.command_input # Available if needed
        
        parts = raw_text.lower().split(" ", 1)
        command = parts[0]
        args_str = parts[1] if len(parts) > 1 else ""

        logger.debug(f"MainDefaultAgent '{self.slug}' received input: command='{command}', args='{args_str}'")

        if command == "greet" or command == "hello":
            name_arg = args_str.strip() if args_str else None
            await self._do_greet(name_arg)
        elif command == "agentinfo":
            await self._do_agentinfo()
        elif command == "help":
            await self._do_help()
        else:
            await self.event_bus.publish(
                AgentOutputEvent(
                    message=f"'{raw_text}' is not a recognized command for the Main Agent. Try 'help'.",
                    style="italic yellow"
                )
            )

    async def _do_greet(self, name_arg: Optional[str]):
        name_to_greet = name_arg if name_arg else self.default_greet_name
        await self.event_bus.publish(
            AgentOutputEvent(
                message=f"Hello, {name_to_greet}, from the {self.slug} Agent!",
                style="bold magenta"
            )
        )

    async def _do_agentinfo(self):
        my_resolved_config: Optional[AgentConfig] = self.app_services.raw_app_config.get('resolved_agents', {}).get(self.slug)
        
        info_lines = [f"--- Agent: {self.slug} ---"]
        if my_resolved_config:
            info_lines.append(f"Description: {my_resolved_config.description}")
            info_lines.append(f"Path (Module): {my_resolved_config.path}")
            info_lines.append(f"Target Type: {'Class' if my_resolved_config.is_class_target else 'Function'}")
            target_name = my_resolved_config.target_class.__name__ if my_resolved_config.target_class else \
                          (my_resolved_config.target_composition_function.__name__ if my_resolved_config.target_composition_function else "N/A")
            info_lines.append(f"Target Name: {target_name}")
        info_lines.append(f"Init Args Received: {self.init_args}")

        await self.event_bus.publish(AgentOutputEvent(message="\n".join(info_lines), style="code"))

    async def _do_help(self):
        help_text = f"""--- {self.slug} Agent Help ---
Available inputs:
  greet [name]         - Greets you or the specified name. (Alias: hello)
  agentinfo            - Shows information about this agent.
  help                 - Shows this help message.

Global commands (start with /):
  /help                - Shows global application commands.
  /agents              - Lists all available agents.
  /agent <agent_name>  - Switches to the specified agent.
  /exit                - Exits Pocket Commander.
"""
        await self.event_bus.publish(AgentOutputEvent(message=help_text, style=None))

    # Required PocketFlow AsyncNode methods
    async def prep_async(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug(f"MainDefaultAgent '{self.slug}' prep_async called.")
        return shared

    async def exec_async(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug(f"MainDefaultAgent '{self.slug}' exec_async called.")
        return {"status": f"{self.slug} primarily event-driven, exec_async is placeholder."}

    async def post_async(self, shared: Dict[str, Any], prep_res: Dict[str, Any], exec_res: Dict[str, Any]) -> Optional[str]:
        logger.debug(f"MainDefaultAgent '{self.slug}' post_async called.")
        return None