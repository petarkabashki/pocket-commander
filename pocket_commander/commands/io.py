#%%
# pocket_commander/commands/io.py
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type, TypeVar

T = TypeVar('T')

class AbstractCommandInput(ABC):
    """
    Abstract base class for command input handling.
    It provides methods to access parsed arguments and raw input.
    """
    def __init__(self, raw_input_data: Any):
        self._raw_input_data = raw_input_data

    @property
    def raw_input(self) -> Any:
        """The original, unprocessed input data."""
        return self._raw_input_data

    @abstractmethod
    def get_argument(self, name: str, type_hint: Type[T] = str, default: Optional[T] = None) -> Optional[T]:
        """
        Retrieves a specific argument by name, with optional type casting and default value.
        How arguments are named and parsed depends on the concrete implementation.
        For simple space-splitted args, 'name' might be an index or not used directly.
        """
        pass

    @abstractmethod
    def get_all_arguments(self) -> Dict[str, Any]:
        """
        Returns a dictionary of all parsed arguments.
        The structure of this dictionary depends on the concrete implementation.
        """
        pass

    @abstractmethod
    def get_remaining_input(self) -> str:
        """
        Returns the portion of the input string that hasn't been parsed into
        the primary command or specific arguments. Useful for commands that take
        free-form text after the command word.
        """
        pass


class AbstractOutputHandler(ABC):
    """
    Abstract base class for handling output from commands.
    Provides methods for sending various types of messages.
    """

    @abstractmethod
    async def send_message(self, message: Any, style: Optional[str] = None):
        """Sends a regular message to the output channel."""
        pass

    @abstractmethod
    async def send_error(self, message: Any, details: Optional[str] = None, style: str = "bold red"):
        """Sends an error message to the output channel."""
        pass

    @abstractmethod
    async def send_data(self, data: Any, format_hint: Optional[str] = None, style: Optional[str] = None):
        """
        Sends structured data to the output channel.
        The 'format_hint' can suggest how the data might be displayed (e.g., 'json', 'table').
        """
        pass