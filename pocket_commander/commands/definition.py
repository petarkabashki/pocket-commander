#%%
# pocket_commander/commands/definition.py
from typing import Any, Callable, List, Optional, Dict, Awaitable
from pydantic import BaseModel, Field
from pocket_commander.commands.io import AbstractCommandInput, AbstractOutputHandler, PromptFunc
import asyncio # Required for CommandContext type hint

# Forward declaration for CommandContext to resolve circular import if it were direct
CommandContext = Any # Actual definition will be in core.py

class ParameterDefinition(BaseModel):
    """
    Defines a parameter for a command.
    """
    name: str = Field(..., description="The name of the parameter.")
    param_type: Any = Field(default=str, description="The Python type of the parameter.")
    description: Optional[str] = Field(None, description="A brief description of the parameter.")
    required: bool = Field(default=True, description="Whether the parameter is required.")
    default: Optional[Any] = Field(None, description="The default value if the parameter is not provided.")
    # For variadic arguments (*args), 'name' could be 'args' and a specific type like List[str]
    # For keyword arguments (**kwargs), 'name' could be 'kwargs' and type Dict[str, Any]

    class Config:
        arbitrary_types_allowed = True

class CommandDefinition(BaseModel):
    """
    Defines a command, including its metadata, function, and parameters.
    """
    name: str = Field(..., description="The primary name of the command (e.g., 'help', 'agent').")
    command_function: Callable[[CommandContext], Awaitable[Any]] = Field(
        ..., description="The asynchronous function to execute for this command."
    )
    description: Optional[str] = Field(None, description="A user-friendly description of what the command does.")
    parameters: List[ParameterDefinition] = Field(default_factory=list, description="A list of parameter definitions for the command.")
    aliases: List[str] = Field(default_factory=list, description="Alternative names for the command.")
    category: Optional[str] = Field("General", description="Category for grouping commands (e.g., 'File Operations', 'Agent Management').")

    class Config:
        arbitrary_types_allowed = True

# Example Usage (for illustration, not part of the actual file content for definition.py)
# async def example_command_func(ctx: CommandContext):
#     await ctx.output.send_message(f"Example command executed in agent: {ctx.agent_name}")

# example_param = ParameterDefinition(name="target_agent", param_type=str, description="The agent to switch to.")
# example_command = CommandDefinition(
#     name="agent",
#     command_function=example_command_func, # Replace with actual async function
#     description="Switches to a specified agent.",
#     parameters=[example_param],
#     aliases=["m", "switch_agent"]
# )