#%%
# pocket_commander/commands/terminal_io.py
from typing import Any, Dict, Optional, Type, TypeVar, List

from pocket_commander.commands.io import AbstractCommandInput, AbstractOutputHandler
from pocket_commander.terminal_interface import TerminalApp # For type hinting and console access

T = TypeVar('T')

class TerminalCommandInput(AbstractCommandInput):
    """
    Terminal-specific implementation of command input.
    Handles input strings from the terminal.
    For bare-word commands, it assumes the input is the string *after* the command word.
    """
    def __init__(self, command_word: str, remaining_input_str: str, terminal_app: 'TerminalApp'):
        super().__init__(raw_input_data=remaining_input_str) # Store the part after command word
        self.command_word = command_word
        self.terminal_app = terminal_app
        self._parsed_args: Optional[List[str]] = None # For simple space splitting

    def _parse_if_needed(self):
        if self._parsed_args is None:
            # Simple space splitting for arguments from the remaining input string
            self._parsed_args = self.raw_input.strip().split() if self.raw_input.strip() else []

    def get_argument(self, name: str, type_hint: Type[T] = str, default: Optional[T] = None) -> Optional[T]:
        """
        For simple space-splitted args, 'name' is treated as an integer index.
        This is a basic implementation and can be made more robust.
        """
        self._parse_if_needed()
        try:
            index = int(name)
            if 0 <= index < len(self._parsed_args):
                value_str = self._parsed_args[index]
                # Basic type casting (can be expanded)
                if type_hint == bool:
                    return value_str.lower() in ['true', '1', 'yes', 'y']
                return type_hint(value_str)
            return default
        except (ValueError, IndexError):
            return default

    def get_all_arguments(self) -> Dict[str, Any]:
        """
        Returns arguments as a dictionary with indices as keys for simple splitting,
        and also a special key 'raw_string' for the full argument string.
        """
        self._parse_if_needed()
        args_dict = {str(i): val for i, val in enumerate(self._parsed_args)}
        args_dict["raw_string"] = self.raw_input # The string after the command
        return args_dict

    def get_remaining_input(self) -> str:
        """
        For TerminalCommandInput, this typically returns the full string that was
        passed as `remaining_input_str` during initialization, as that's already
        considered the "remaining" part after the command word itself.
        """
        return self.raw_input


class TerminalOutputHandler(AbstractOutputHandler):
    """
    Terminal-specific implementation of command output.
    Uses the Rich console from TerminalApp to display messages.
    """
    def __init__(self, terminal_app: 'TerminalApp'):
        self.terminal_app = terminal_app
        self.console = terminal_app.console

    async def send_message(self, message: Any, style: Optional[str] = None):
        # display_output is not async, so no await here
        self.terminal_app.display_output(str(message), style=style)

    async def send_error(self, message: Any, details: Optional[str] = None, style: str = "bold red"):
        full_message = f"Error: {message}"
        if details:
            full_message += f"\nDetails: {details}"
        self.terminal_app.display_output(full_message, style=style)

    async def send_data(self, data: Any, format_hint: Optional[str] = None, style: Optional[str] = None):
        # For now, just print the string representation.
        # Could be enhanced to use Rich's table, JSON formatting, etc. based on format_hint.
        if format_hint == 'json':
            import json
            try:
                # Pretty print JSON
                self.console.print_json(json.dumps(data))
                return
            except TypeError: # Not JSON serializable
                pass # Fall through to default
        
        self.terminal_app.display_output(str(data), style=style)