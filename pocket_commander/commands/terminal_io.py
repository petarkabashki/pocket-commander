#%%
# pocket_commander/commands/terminal_io.py
import asyncio 
import uuid 
import logging 
from typing import Any, Dict, Optional, Type, TypeVar, List
from rich.console import Console # Keep for potential direct use, though TerminalAgUIClient has its own

from pocket_commander.commands.io import AbstractCommandInput # AbstractOutputHandler removed
from pocket_commander.event_bus import AsyncEventBus, BaseEvent 
# SystemMessageEvent and AgentOutputEvent are less relevant for direct terminal output now
# from pocket_commander.events import SystemMessageEvent, SystemMessageType 
# from pocket_commander.events import AgentOutputEvent 

logger = logging.getLogger(__name__) 

T = TypeVar('T')

class TerminalCommandInput(AbstractCommandInput):
    """
    Terminal-specific implementation of command input.
    Handles a full input string from the terminal.
    """
    def __init__(self, full_input_str: str):
        self._raw_input_str = full_input_str 
        self._command_word: Optional[str] = None
        self._args_str: str = "" 
        self._parsed_args: Optional[List[str]] = None 
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
        args_dict["raw_string"] = self._args_str 
        return args_dict

    def get_remaining_input(self) -> str:
        """
        Returns the portion of the input string *after* the command word.
        """
        return self._args_str

class StringCommandInput(TerminalCommandInput): # Added for clarity, used in app_core
    """
    An alias or specific version of TerminalCommandInput initialized from a string,
    primarily used for parsing argument strings for global commands internally.
    """
    def __init__(self, args_string: str):
        # For StringCommandInput, the "command word" is notional or empty,
        # and the full args_string is treated as the arguments.
        super().__init__(args_string)
        # Override parsing if needed, or ensure TerminalCommandInput handles this correctly.
        # If args_string is purely arguments, then _command_word might be empty
        # and _args_str would be the full args_string.
        # Let's adjust:
        if " " not in args_string.strip(): # If it's a single word or empty
            self._command_word = args_string.strip() # Treat as command if no spaces
            self._args_str = ""
        else: # If there are spaces, assume first word is notional command, rest is args
              # This behavior is inherited from TerminalCommandInput, which is fine for parse_arguments
              # as it operates on get_remaining_input() or similar.
              # For StringCommandInput, we often want the *whole string* to be parsed as arguments.
              # So, let's ensure _args_str is the full input string for parsing.
            self._command_word = "" # No command word for pure arg string
            self._args_str = args_string # The whole string is args


# TerminalOutputHandler class has been removed as its functionality is
# now covered by TerminalAgUIClient and the ag_ui event system.