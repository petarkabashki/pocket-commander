import asyncio
import logging
import yaml # For loading configuration
from typing import Dict, Any

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from pocket_commander.config_loader import load_and_register_mcp_tools_from_config, load_and_resolve_app_config
from pocket_commander.tools.registry import global_tool_registry
from pocket_commander.utils.logging_utils import setup_logging
from pocket_commander.event_bus import AsyncEventBus
# SystemMessageEvent and TerminalOutputHandler might be obsolete or their roles changed
# from pocket_commander.events import SystemMessageEvent, SystemMessageType # Keep if AppCore still uses for critical errors
# from pocket_commander.commands.terminal_io import TerminalOutputHandler # Replaced by TerminalAgUIClient

# Import new core components
from pocket_commander.app_core import create_application_core, AppCore # Import AppCore class
# from pocket_commander.flows.terminal_interaction_flow import TerminalInteractionFlow # Replaced
from pocket_commander.ag_ui.terminal_client import TerminalAgUIClient # New UI Client
from pocket_commander.types import AppServices

async def main():
    bootstrap_logger = logging.getLogger(__name__ + ".bootstrap")
    bootstrap_logger.info("Initializing Pocket Commander (AgUIClient Edition)...")

    raw_app_config: Dict[str, Any] = load_and_resolve_app_config()
    
    if raw_app_config is None:
        print("CRITICAL: Failed to load or resolve application configuration. Exiting.")
        return
    bootstrap_logger.info("Application configuration loaded and agents resolved successfully.")

    initial_log_level_str = setup_logging(raw_app_config)
    logger = logging.getLogger(__name__)
    logger.info(f"Logging system configured. Initial global log level: {initial_log_level_str}")

    try:
        tools_package_path = "pocket_commander/tools"
        tools_module_path = "pocket_commander.tools"
        logger.info(f"Scanning for native tools in: {tools_package_path} (module: {tools_module_path})")
        global_tool_registry.scan_and_register_tools(tools_package_path, tools_module_path)
        logger.info("Native tools scanned and registered.")
    except Exception as e:
        logger.error(f"Failed to scan or register native tools: {e}", exc_info=True)
    try:
        load_and_register_mcp_tools_from_config(raw_app_config, global_tool_registry)
        logger.info("MCP tools loaded and registered from configuration.")
    except Exception as e:
        logger.error(f"Failed to load or register MCP tools from config: {e}", exc_info=True)

    event_bus_instance = AsyncEventBus()

    app_services_dict: Dict[str, Any] = {
        "raw_app_config": raw_app_config,
        "current_log_level": initial_log_level_str,
        "output_handler": None, # No longer set here; UI client handles output
        "prompt_func": None,    # No longer set here; UI client handles prompts
        "global_tool_registry": global_tool_registry,
        "event_bus": event_bus_instance,
        "_application_state_DO_NOT_USE_DIRECTLY": None,
        # These will be populated after AppCore is created
        "get_current_agent_slug": None,
        "get_available_agents": None,
        "request_agent_switch": None,
    }
    
    app_services_typed = AppServices(**app_services_dict)
    
    app_core_instance: Optional[AppCore] = None
    ui_client_instance: Optional[TerminalAgUIClient] = None

    try:
        # Create and initialize AppCore first
        app_core_instance = await create_application_core(app_services_typed)
        logger.info("Application core created and initialized.")

        # Now that AppCore is created, populate its methods into AppServices
        if app_core_instance:
            app_services_typed.get_current_agent_slug = app_core_instance.get_current_agent_slug
            app_services_typed.get_available_agents = app_core_instance.get_available_agents
            app_services_typed.request_agent_switch = app_core_instance.request_agent_switch
            logger.info("AppServices populated with AppCore methods.")
        else:
            raise RuntimeError("AppCore instance was not created successfully.")


        # Create UI Client
        ui_client_instance = TerminalAgUIClient(app_services=app_services_typed, client_id="main_terminal")
        # The AppCore now gets app_services directly, and UI client also gets it.
        # If AppCore needs a reference to the UI client (e.g. to call request_dedicated_input directly),
        # it could be passed here, or AppCore could find it via AppServices if we add it there.
        # For now, UI client operates by listening to events and publishing AppInputEvent.
        # Agents/AppCore request dedicated input via RequestPromptEvent.
        
        # app_services_typed.output_handler is no longer used from here.
        # app_services_typed.prompt_func is no longer set/used from here.
        # The old TerminalOutputHandler is removed.
        
    except Exception as e:
        logger.error(f"Failed to create application core or UI client: {e}", exc_info=True)
        # Publishing SystemMessageEvent might not work if event bus or UI client isn't up.
        # Rely on console print for critical bootstrap errors.
        print(f"Critical error during initialization: {e}")
        return

    await event_bus_instance.start()
    logger.info("Event bus started.")

    try:
        if ui_client_instance:
            # Start the UI client's main loop (non-blocking)
            # TerminalAgUIClient.start() itself creates a task for its loop.
            await ui_client_instance.start() 
            logger.info("Terminal UI Client started.")
            
            # Keep the main function alive, perhaps waiting for a shutdown signal
            # or for the UI client's task to complete (e.g. on /exit)
            if ui_client_instance._main_loop_task: # Accessing protected member for clarity here
                await ui_client_instance._main_loop_task 
            else: # Fallback if task isn't exposed or start isn't creating one as expected
                while True: # Replace with a more robust shutdown mechanism
                    await asyncio.sleep(1)
                    if not ui_client_instance._running: # Check if client stopped itself
                        break
        else:
            logger.error("UI Client instance not created. Cannot start UI.")

    except SystemExit:
        logger.info("Application exit initiated by SystemExit (e.g., /exit command).")
    except KeyboardInterrupt:
        logger.info("Application terminated by user (KeyboardInterrupt in main).")
    finally:
        logger.info("Initiating shutdown sequence...")
        if ui_client_instance and ui_client_instance._running:
            logger.info("Stopping UI client...")
            await ui_client_instance.stop()
            logger.info("UI client stopped.")
        
        # TODO: Add AppCore shutdown logic if needed (e.g., deactivating agents)
        # if app_core_instance and hasattr(app_core_instance, 'shutdown'):
        # await app_core_instance.shutdown()

        logger.info("Stopping event bus...")
        await event_bus_instance.stop()
        logger.info("Event bus stopped.")
            
    logger.info("Pocket Commander (AgUIClient Edition) exited.")

if __name__ == "__main__":
    # Windows event loop policy handling (unchanged)
    if asyncio.get_event_loop_policy().__class__.__name__ == 'WindowsProactorEventLoopPolicy' \
       and isinstance(asyncio.get_event_loop(), asyncio.ProactorEventLoop):
        pass
    elif asyncio.get_event_loop_policy().__class__.__name__ == 'WindowsSelectorEventLoopPolicy':
        pass

    try:
        asyncio.run(main())
    except SystemExit:
        print("SystemExit caught at the very end. Application has shut down.")
    except KeyboardInterrupt:
        print("\nApplication terminated by user (KeyboardInterrupt at top level).")
    except Exception as e:
        print(f"A critical unhandled exception occurred at the top level: {e}")
        try:
            logging.critical(f"A critical unhandled exception occurred at the top level: {e}", exc_info=True)
        except: # noqa
            pass
    finally:
        logging.shutdown()