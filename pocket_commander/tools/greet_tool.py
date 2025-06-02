import logging
from pocket_commander.tools.decorators import tool
from pocket_commander.tools.definition import ToolParameterDefinition

logger = logging.getLogger(__name__)

@tool(
    name="greet_user",
    description="Greets the specified user.",
    
)
async def greet_user(name: str) -> str:
    """
    Greets the specified user.
    """
    logger.info(f"Tool 'greet_user' called with name: {name}")
    greeting = f"Hello, {name}! Welcome to Pocket Commander."
    # In a real scenario, this might return a dictionary or a more structured response
    # For now, a simple string is fine for testing.
    return greeting