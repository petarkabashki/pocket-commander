import logging
import datetime
from pocket_commander.tools.decorators import tool

logger = logging.getLogger(__name__)

@tool(
    name="show_time",
    description="Shows the current date and time.",
     # No parameters for this tool
)
async def show_time() -> str:
    """
    Returns the current date and time as a formatted string.
    """
    logger.info("Tool 'show_time' called.")
    now = datetime.datetime.now()
    formatted_time = now.strftime("%Y-%m-%d %H:%M:%S")
    return f"The current date and time is: {formatted_time}"