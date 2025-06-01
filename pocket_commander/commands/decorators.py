#%%
# pocket_commander/commands/decorators.py
import functools
from typing import Callable, List, Optional, Any
from pocket_commander.commands.core import CommandMetadata

def command(name: str, description: str, aliases: Optional[List[str]] = None):
    """
    Decorator to mark a method within a ModeFlow class as a command.

    Args:
        name: The primary name of the command.
        description: A short description of what the command does.
        aliases: An optional list of alternative names for the command.
    """
    if aliases is None:
        aliases = []

    def decorator(func: Callable[..., Any]):
        # Ensure the decorated function is async, as per design decision
        if not asyncio.iscoroutinefunction(func):
            raise TypeError(f"Command '{name}' function must be an async function (defined with 'async def').")

        # Attach metadata to the function object itself.
        # This metadata will be discovered by the ModeFlow's command registry.
        setattr(func, '_command_metadata', CommandMetadata(
            name=name,
            func=func,
            description=description,
            aliases=aliases
        ))

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # The first argument to the method will be 'self' (the ModeFlow instance)
            # The second should be the CommandContext instance.
            # This wrapper primarily ensures the original function is called.
            # Type checking for CommandContext presence can be done at dispatch time.
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

# Need to import asyncio for the type check
import asyncio