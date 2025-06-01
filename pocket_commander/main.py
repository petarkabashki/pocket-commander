import asyncio
import logging
import yaml # For loading configuration
from typing import Dict, Any

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO, # Consider making this configurable
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pocket_commander.log', mode='w'), # Overwrite log each run
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Import new core components
from pocket_commander.app_core import create_application_core
from pocket_commander.flows.terminal_interaction_flow import TerminalInteractionFlow
from pocket_commander.types import AppServices
# TerminalOutputHandler and TerminalCommandInput are used internally by TIF

async def main():
    logger.info("Initializing Pocket Commander (Functional Core Edition)...")
    
    # 1. Load Raw Application Configuration
    raw_app_config: Dict[str, Any] = {}
    try:
        with open("pocket_commander.conf.yaml", 'r') as f:
            raw_app_config = yaml.safe_load(f)
        logger.info("Application configuration loaded successfully.")
    except FileNotFoundError:
        logger.error("Configuration file 'pocket_commander.conf.yaml' not found. Exiting.")
        return
    except yaml.YAMLError as e:
        logger.error(f"Error parsing configuration file: {e}. Exiting.")
        return
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading configuration: {e}. Exiting.")
        return

    # 2. Prepare AppServices (partially, handlers will be added from TerminalInteractionFlow)
    # This dictionary will be passed by reference and updated.
    app_services_dict: Dict[str, Any] = {
        "raw_app_config": raw_app_config,
        "output_handler": None, # Placeholder
        "prompt_func": None,    # Placeholder
        # '_application_state_DO_NOT_USE_DIRECTLY': None # Placeholder for app_core to inject state for TIF prompt
    }

    # 3. Initialize TerminalInteractionFlow
    # It needs app_services for config and will provide I/O handlers.
    # The process_input_callback is initially None and set later.
    terminal_flow = TerminalInteractionFlow(
        app_services=app_services_dict, # Pass the dict by reference
        process_input_callback=None 
    )

    # 4. Populate AppServices with concrete I/O handlers from TerminalInteractionFlow
    app_services_dict["output_handler"] = terminal_flow.get_output_handler()
    app_services_dict["prompt_func"] = terminal_flow.request_dedicated_input
    
    # Cast to the TypedDict for type safety when passing to app_core
    # Pydantic/TypedDict doesn't enforce runtime checks here, it's for static analysis.
    # We trust that we've populated the required fields.
    app_services_typed = AppServices(**app_services_dict) # type: ignore 
    # The type: ignore is because we're building it progressively.
    # A more robust way might be a builder pattern for AppServices.

    # 5. Create the Application Core and get the top-level input processor
    # create_application_core will use the provided app_services (with handlers)
    # and might inject its internal state into app_services_dict if the HACK for TIF prompt is used.
    try:
        top_level_input_processor = await create_application_core(app_services_typed)
        # If app_core needs to inject its state for TIF's prompt:
        # It should have done so by modifying the 'app_services_dict' (or 'app_services_typed')
        # it received, e.g., app_services_typed['_application_state_DO_NOT_USE_DIRECTLY'] = internal_app_state_dict
    except Exception as e:
        logger.error(f"Failed to create application core: {e}", exc_info=True)
        # Attempt to inform user via TIF if output_handler was set up
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
    except KeyboardInterrupt: # Should be handled within TIF, but as a fallback.
        logger.info("Application terminated by user (KeyboardInterrupt in main).")
        if terminal_flow._running: # Check if TIF is still marked as running
            await terminal_flow.stop()
    except Exception as e:
        logger.exception("An unhandled exception occurred during terminal_flow.start():")
        if terminal_flow._running:
            await terminal_flow.stop()
            
    logger.info("Pocket Commander (Functional Core Edition) exited.")

if __name__ == "__main__":
    # Ensure the event loop is suitable for prompt_toolkit if on Windows
    if asyncio.get_event_loop_policy().__class__.__name__ == 'WindowsProactorEventLoopPolicy' \
       and isinstance(asyncio.get_event_loop(), asyncio.ProactorEventLoop):
        pass # Proactor is fine
    elif asyncio.get_event_loop_policy().__class__.__name__ == 'WindowsSelectorEventLoopPolicy':
         # On Windows, prompt_toolkit might prefer ProactorEventLoop for better async handling
         # However, changing it globally can have side effects.
         # For now, we'll proceed with default. If issues arise, this might need adjustment.
         # asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
         # loop = asyncio.ProactorEventLoop()
         # asyncio.set_event_loop(loop)
         pass


    try:
        asyncio.run(main())
    except SystemExit:
        logger.info("SystemExit caught at the very end. Application has shut down.")
    except KeyboardInterrupt: # Final fallback
        logger.info("Application terminated by user (KeyboardInterrupt at top level).")
    except Exception as e:
        logger.critical(f"A critical unhandled exception occurred at the top level: {e}", exc_info=True)
    finally:
        logging.shutdown()