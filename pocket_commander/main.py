import asyncio
import logging

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO, # Changed to INFO for less verbose default terminal output
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pocket_commander.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Import TerminalApp
from .terminal_interface import TerminalApp

async def main():
    logger.info("Initializing PocketFlow Terminal...")
    app = TerminalApp()
    await app.run()
    logger.info("PocketFlow Terminal exited.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user (KeyboardInterrupt).")
    except Exception as e:
        logger.exception("An unhandled exception occurred in main:")