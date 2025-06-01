#%%
# pocket_commander/commands/core.py
import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Dict

if TYPE_CHECKING:
    from pocket_commander.commands.io import AbstractCommandInput, AbstractOutputHandler
    from pocket_commander.terminal_interface import TerminalApp # For type hinting

@dataclass
class CommandMetadata:
    """Stores metadata for a registered command."""
    name: str
    func: Callable[..., Any] # The actual command function
    description: str
    aliases: List[str] = field(default_factory=list)

@dataclass
class CommandContext:
    """
    Context object passed to command functions, providing access to I/O,
    mode details, and other relevant information.
    """
    input: 'AbstractCommandInput'
    output: 'AbstractOutputHandler'
    mode_name: str
    # Using 'TerminalApp' for now, could be abstracted if other app types emerge
    terminal_app: 'TerminalApp' 
    mode_flow: Any # Instance of the current mode's flow class
    loop: asyncio.AbstractEventLoop
    
    # Potentially add a logger instance here later
    # logger: Any 

    # Convenience properties or methods can be added as needed
    @property
    def console(self):
        """Direct access to the Rich console from terminal_app for convenience."""
        return self.terminal_app.console