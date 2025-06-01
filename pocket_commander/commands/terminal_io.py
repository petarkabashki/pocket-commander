#%%
# pocket_commander/commands/terminal_io.py
from typing import Any, Dict, Optional, Type, TypeVar, List
from rich.console import Console # Changed from TerminalApp import

from pocket_commander.commands.io import AbstractCommandInput, AbstractOutputHandler

T = TypeVar('T')

class TerminalCommandInput(AbstractCommandInput):
    """
    Terminal-specific implementation of command input.
    Handles a full input string from the terminal.
    """
    def __init__(self, full_input_str: str):
        super().__init__(full_input_str) # Store the full input string
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
                    return value_str.lower() in ['true', '1', 'yes', 'y']
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
    """
    def __init__(self, console: Console): # Changed from terminal_app
        self.console = console

    async def send_message(self, message: Any, style: Optional[str] = None):
        from rich.text import Text # Local import to avoid circular if Text is complex
        if style:
            self.console.print(Text(str(message), style=style))
        else:
            self.console.print(str(message))

    async def send_error(self, message: Any, details: Optional[str] = None, style: str = "bold red"):
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
                # Pretty print JSON
                self.console.print_json(json.dumps(data))
                return
            except TypeError: # Not JSON serializable
                pass # Fall through to default
        
        if style:
            self.console.print(Text(str(data), style=style))
        else:
             self.console.print(str(data))