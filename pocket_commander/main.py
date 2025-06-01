import asyncio
import logging
import yaml # For loading configuration
from typing import Dict, Any

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from pocket_commander.config_loader import load_and_register_mcp_tools_from_config
from pocket_commander.utils.logging_utils import setup_logging # New import

# Old logging setup removed
# logging.basicConfig(
#     level=logging.INFO, # Consider making this configurable
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler('pocket_commander.log', mode='w'), # Overwrite log each run
#         logging.StreamHandler()
#     ]
# )
# logger = logging.getLogger(__name__) # This can stay if needed for main.py specific logs,
                                     # but root logger is now configured by setup_logging

# Import new core components
from pocket_commander.app_core import create_application_core
from pocket_commander.flows.terminal_interaction_flow import TerminalInteractionFlow
from pocket_commander.types import AppServices
# TerminalOutputHandler and TerminalCommandInput are used internally by TIF

async def main():
    # Initial logger for bootstrap messages before full config.
    # This will use Python's default logging until setup_logging is called.
    bootstrap_logger = logging.getLogger(__name__ + ".bootstrap")
    bootstrap_logger.info("Initializing Pocket Commander (Functional Core Edition)...")

    # 1. Load Raw Application Configuration
    raw_app_config: Dict[str, Any] = {}
    try:
        with open("pocket_commander.conf.yaml", 'r') as f:
            raw_app_config = yaml.safe_load(f)
        bootstrap_logger.info("Application configuration loaded successfully.")
    except FileNotFoundError:
        bootstrap_logger.error("Configuration file 'pocket_commander.conf.yaml' not found. Exiting.")
        print("CRITICAL: Configuration file 'pocket_commander.conf.yaml' not found. Exiting.")
        return
    except yaml.YAMLError as e:
        bootstrap_logger.error(f"Error parsing configuration file: {e}. Exiting.")
        print(f"CRITICAL: Error parsing configuration file: {e}. Exiting.")
        return
    except Exception as e:
        bootstrap_logger.error(f"An unexpected error occurred while loading configuration: {e}. Exiting.")
        print(f"CRITICAL: An unexpected error occurred while loading configuration: {e}. Exiting.")
        return

    # 1a. Setup Logging (New Step)
    # This must be done after raw_app_config is loaded.
    initial_log_level_str = setup_logging(raw_app_config)
    # From now on, logging is configured. We can use the standard logger.
    logger = logging.getLogger(__name__) # Get a logger instance for main module
    logger.info(f"Logging system configured. Initial global log level: {initial_log_level_str}")


    # 1b. Load and Register MCP Tools from Configuration
    # This should happen after basic config load but before AppServices fully depends on tools
    try:
        load_and_register_mcp_tools_from_config("pocket_commander.conf.yaml")
        logger.info("MCP tools loaded and registered from configuration.")
    except Exception as e:
        logger.error(f"Failed to load or register MCP tools from config: {e}", exc_info=True)
        # Decide if this is a fatal error. For now, we'll log and continue.

    # 2. Prepare AppServices
    app_services_dict: Dict[str, Any] = {
        "raw_app_config": raw_app_config,
        "current_log_level": initial_log_level_str, # Store initial level
        "output_handler": None, # Placeholder
        "prompt_func": None,    # Placeholder
        "_application_state_DO_NOT_USE_DIRECTLY": None # Initialize for app_core if it uses it
    }

    # 3. Initialize TerminalInteractionFlow
    terminal_flow = TerminalInteractionFlow(
        app_services=app_services_dict,
        process_input_callback=None
    )

    # 4. Populate AppServices with concrete I/O handlers from TerminalInteractionFlow
    app_services_dict["output_handler"] = terminal_flow.get_output_handler()
    app_services_dict["prompt_func"] = terminal_flow.request_dedicated_input
    
    app_services_typed = AppServices(**app_services_dict) # type: ignore

    # 5. Create the Application Core
    try:
        top_level_input_processor = await create_application_core(app_services_dict)
    except Exception as e:
        logger.error(f"Failed to create application core: {e}", exc_info=True)
        if app_services_typed.get("output_handler"):
            try:
                await app_services_typed["output_handler"].send_error("Critical error: Could not initialize application core.", str(e))
            except Exception as e_send:
                logger.error(f"Additionally, failed to send core creation error to terminal: {e_send}")
        return

    # 6. Set the process_input_callback for TerminalInteractionFlow
    terminal_flow.process_input_callback = top_level_input_processor

    # 7. Start the TerminalInteractionFlow's main loop
    try:
        await terminal_flow.start()
    except SystemExit:
        logger.info("Application exit initiated by SystemExit (e.g., /exit command).")
    except KeyboardInterrupt:
        logger.info("Application terminated by user (KeyboardInterrupt in main).")
        if terminal_flow._running:
            await terminal_flow.stop()
    except Exception as e:
        logger.exception("An unhandled exception occurred during terminal_flow.start():")
        if terminal_flow._running:
            await terminal_flow.stop()
            
    logger.info("Pocket Commander (Functional Core Edition) exited.")

if __name__ == "__main__":
    if asyncio.get_event_loop_policy().__class__.__name__ == 'WindowsProactorEventLoopPolicy' \
       and isinstance(asyncio.get_event_loop(), asyncio.ProactorEventLoop):
        pass
    elif asyncio.get_event_loop_policy().__class__.__name__ == 'WindowsSelectorEventLoopPolicy':
        pass

    try:
        asyncio.run(main())
    except SystemExit:
        # Logging might already be shut down if this happens late.
        print("SystemExit caught at the very end. Application has shut down.")
    except KeyboardInterrupt:
        print("Application terminated by user (KeyboardInterrupt at top level).")
    except Exception as e:
        # Use print as logging might be unreliable here
        print(f"A critical unhandled exception occurred at the top level: {e}")
        # Optionally, try to log if possible, but don't rely on it
        try:
            logging.critical(f"A critical unhandled exception occurred at the top level: {e}", exc_info=True)
        except: # noqa
            pass
    finally:
        # Ensure logging is shut down cleanly
        logging.shutdown()