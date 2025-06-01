#%%
# pocket_commander/types.py
from typing import TypedDict, Callable, Awaitable, Optional, Any, Dict
import logging # For potential logger type hint

# Attempt to import from .commands.io, handling potential circularity during initial setup
# or if this file is processed before commands.io is fully available.
try:
    from .commands.io import AbstractOutputHandler, PromptFunc
except ImportError:
    # Provide fallbacks if direct import fails (e.g. during linting or partial builds)
    # These are type placeholders and assume the actual types will be available at runtime.
    AbstractOutputHandler = Any
    PromptFunc = Callable[..., Awaitable[Any]]


class AppServices(TypedDict):
    """
    A container for shared application services passed around the system.
    """
    output_handler: AbstractOutputHandler
    prompt_func: PromptFunc
    raw_app_config: Dict[str, Any]
    # logger: Optional[logging.Logger] # Uncomment and configure if a shared logger is added