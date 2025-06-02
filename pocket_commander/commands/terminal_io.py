#%%
# pocket_commander/commands/terminal_io.py
import asyncio # Added
import uuid # Added
import logging # Added
from typing import Any, Dict, Optional, Type, TypeVar, List
from rich.console import Console

from pocket_commander.commands.io import AbstractCommandInput, AbstractOutputHandler
from pocket_commander.event_bus import AsyncEventBus, BaseEvent # Added
from pocket_commander.events import SystemMessageEvent, SystemMessageType # Added
from pocket_commander.events import AgentOutputEvent # Added

logger = logging.getLogger(__name__) # Added

T = TypeVar('T')

class TerminalCommandInput(AbstractCommandInput):
    """
    Terminal-specific implementation of command input.
    Handles a full input string from the terminal.
    """
    # This class currently does not handle prompting directly.
    # Prompting logic (request_dedicated_input) is likely in TerminalInteractionFlow
    # or similar, and will be modified there.

    def __init__(self, full_input_str: str):
        # super().__init__(full_input_str) # AbstractCommandInput is a Protocol, no super init
        self._raw_input_str = full_input_str # Store the full input string
        self._command_word: Optional[str] = None
        self._args_str: str = "" # String after the command word
        self._parsed_args: Optional[List[str]] = None # For simple space splitting of _args_str
        self._parse_command_and_args_string()

    def _parse_command_and_args_string(self):
        """Parses the command word and the rest of the arguments string."""
        stripped_input = self._raw_input_str.strip()
        if not stripped_input:
            self._command_word = ""
            self._args_str = ""
            return
        
        parts = stripped_input.split(" ", 1)
        self._command_word = parts[0]
        if len(parts) > 1:
            self._args_str = parts[1]
        else:
            self._args_str = ""

    def _parse_args_list_if_needed(self):
        """Parses the _args_str into a list if not already done."""
        if self._parsed_args is None:
            self._parsed_args = self._args_str.strip().split() if self._args_str.strip() else []

    def get_command_word(self) -> Optional[str]:
        """Returns the identified command word (the first word of the input)."""
        return self._command_word

    def get_argument(self, name: str, type_hint: Type[T] = str, default: Optional[T] = None) -> Optional[T]:
        """
        For simple space-splitted args from the string *after* the command word,
        'name' is treated as an integer index.
        """
        self._parse_args_list_if_needed()
        try:
            index = int(name)
            if self._parsed_args and 0 <= index < len(self._parsed_args):
                value_str = self._parsed_args[index]
                if type_hint == bool:
                    return value_str.lower() in ['true', '1', 'yes', 'y'] # type: ignore
                return type_hint(value_str)
            return default
        except (ValueError, IndexError):
            return default

    def get_all_arguments(self) -> Dict[str, Any]:
        """
        Returns arguments (from the string *after* the command word) as a dictionary
        with indices as keys, and also 'raw_string' for the full argument string part.
        """
        self._parse_args_list_if_needed()
        args_dict = {str(i): val for i, val in enumerate(self._parsed_args or [])}
        args_dict["raw_string"] = self._args_str # The string after the command word
        return args_dict

    def get_remaining_input(self) -> str:
        """
        Returns the portion of the input string *after* the command word.
        """
        return self._args_str


class TerminalOutputHandler(AbstractOutputHandler):
    """
    Terminal-specific implementation of command output.
    Uses a Rich console instance to display messages.
    Subscribes to AgentOutputEvent and SystemMessageEvent to display messages.
    """
    def __init__(self, console: Console, event_bus: AsyncEventBus):
        self.console = console
        self.event_bus = event_bus
        self._subscription_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Subscribes to relevant events."""
        logger.info("TerminalOutputHandler initializing and subscribing to events.") # Added log
        await self.event_bus.subscribe(AgentOutputEvent, self._handle_agent_output_event) # type: ignore
        await self.event_bus.subscribe(SystemMessageEvent, self._handle_system_message_event) # type: ignore
        logger.info("TerminalOutputHandler subscriptions complete.") # Added log


    async def _handle_agent_output_event(self, event: AgentOutputEvent):
        logger.info(f"TerminalOutputHandler received AgentOutputEvent: '{event.message[:50]}...' Style: {event.style}") # Modified log
        """Handles AgentOutputEvent by printing the message to the console."""
        # This method is now the primary way agents send output to the terminal.
        await self.send_message(event.message, style=event.style)

    async def _handle_system_message_event(self, event: SystemMessageEvent):
        logger.info(f"TerminalOutputHandler received SystemMessageEvent: Type: {event.message_type}, Msg: '{event.message[:50]}...'") # Added log
        """Handles SystemMessageEvent by formatting and printing the message."""
        from rich.text import Text # Local import

        message_text = event.message
        style = event.style # Use event's style if provided

        if event.message_type == SystemMessageType.ERROR:
            message_text = f"Error: {event.message}"
            if not style: # Default error style if not overridden
                style = "bold red"
            if event.details:
                message_text += f"\nDetails: {event.details}"
        elif event.message_type == SystemMessageType.WARNING:
            if not style: # Default warning style
                style = "yellow"
        elif event.message_type == SystemMessageType.SUCCESS:
            if not style: # Default success style
                style = "bold green"
        # For INFO and RAW, use the message as is, and apply style if present

        if style:
            self.console.print(Text(str(message_text), style=style))
        else:
            self.console.print(str(message_text))

    # These methods are now primarily for internal use by the handlers,
    # or if some component *really* needs to bypass the event system (discouraged).
    async def send_message(self, message: Any, style: Optional[str] = None):
        from rich.text import Text # Local import
        if style:
            self.console.print(Text(str(message), style=style))
        else:
            self.console.print(str(message))

    async def send_error(self, message: Any, details: Optional[str] = None, style: str = "bold red"):
        # This method is effectively superseded by publishing a SystemMessageEvent with ERROR type.
        # Keeping it for now in case of direct use, but should be deprecated.
        full_message = f"Error: {message}"
        if details:
            full_message += f"\nDetails: {details}"
        
        from rich.text import Text
        self.console.print(Text(full_message, style=style))

    async def send_data(self, data: Any, format_hint: Optional[str] = None, style: Optional[str] = None):
        from rich.text import Text
        if format_hint == 'json':
            import json
            try:
                self.console.print_json(json.dumps(data))
                return
            except TypeError: 
                pass 
        
        if style:
            self.console.print(Text(str(data), style=style))
        else:
             self.console.print(str(data))

    async def close(self):
        """Unsubscribe or clean up (if needed). For now, not strictly necessary."""
        # If we had specific tasks tied to the handler, we might cancel them.
        # Unsubscribing is not directly supported by this simple event bus,
        # but not critical for shutdown if the bus itself stops.
        pass