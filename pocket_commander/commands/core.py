#%%
# pocket_commander/commands/core.py
import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from pocket_commander.commands.io import AbstractCommandInput, AbstractOutputHandler, PromptFunc
    # Forward reference for AppServices, which will be defined in pocket_commander.types
    AppServices = Any

@dataclass
class CommandContext:
    """
    Context object passed to command functions, providing access to I/O,
    application services, mode details, and other relevant information.
    """
    input: 'AbstractCommandInput'
    output: 'AbstractOutputHandler'
    prompt_func: 'PromptFunc'
    app_services: 'AppServices' # Provides access to shared services like config, logger
    mode_name: Optional[str] # Name of the mode in which the command is executed, if any
    loop: asyncio.AbstractEventLoop
    parsed_args: dict[str, Any] # Arguments parsed by the argument parsing utility

    # Potentially add a logger instance here later, accessible via app_services
    # @property
    # def logger(self):
    #     return self.app_services.logger # Assuming logger is part of AppServices

    # Convenience properties or methods can be added as needed based on AppServices content.
    # For example, if raw_app_config is frequently needed:
    # @property
    # def raw_app_config(self) -> dict[str, Any]:
    #     return self.app_services['raw_app_config'] # If AppServices is a TypedDict