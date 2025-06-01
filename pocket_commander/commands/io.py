#%%
# pocket_commander/commands/io.py
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type, TypeVar, Callable, Awaitable

T = TypeVar('T')

# Type definition for the interactive prompt function
PromptFunc = Callable[[str, Optional[str]], Awaitable[str]]

class AbstractCommandInput(ABC):
    """
    Abstract base class for command input handling.
    It provides methods to access the command word, remaining input,
    and potentially pre-parsed arguments.
    """
    def __init__(self, raw_input_str: str):
        self._raw_input_str = raw_input_str

    @property
    def raw_input_string(self) -> str:
        """The original, unprocessed input string."""
        return self._raw_input_str

    @abstractmethod
    def get_command_word(self) -> Optional[str]:
        """
        Extracts and returns the primary command word from the input.
        Returns None if no command word is identified (e.g., for non-command input).
        """
        pass

    @abstractmethod
    def get_argument(self, name: str, type_hint: Type[T] = str, default: Optional[T] = None) -> Optional[T]:
        """
        Retrieves a specific argument by name, with optional type casting and default value.
        How arguments are named and parsed depends on the concrete implementation and
        is typically handled by a dedicated parsing utility using CommandDefinition.
        This method might be used by concrete implementations to access pre-parsed values.
        """
        pass

    @abstractmethod
    def get_all_arguments(self) -> Dict[str, Any]:
        """
        Returns a dictionary of all parsed arguments.
        The structure of this dictionary depends on the concrete implementation.
        A dedicated parsing utility will typically be responsible for populating this
        based on a CommandDefinition.
        """
        pass

    @abstractmethod
    def get_remaining_input(self) -> str:
        """
        Returns the portion of the input string that hasn't been parsed into
        the primary command or specific arguments. Useful for commands that take
        free-form text after the command word, or for non-command input.
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