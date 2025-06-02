import asyncio
import logging
import yaml # For loading configuration
from typing import Dict, Any

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from pocket_commander.config_loader import load_and_register_mcp_tools_from_config, load_and_resolve_app_config # Modified import
from pocket_commander.tools.registry import global_tool_registry
from pocket_commander.utils.logging_utils import setup_logging
from pocket_commander.event_bus import AsyncEventBus
from pocket_commander.events import SystemMessageEvent, SystemMessageType
from pocket_commander.commands.terminal_io import TerminalOutputHandler # Added

# Import new core components
from pocket_commander.app_core import create_application_core
from pocket_commander.flows.terminal_interaction_flow import TerminalInteractionFlow
from pocket_commander.types import AppServices

async def main():
    bootstrap_logger = logging.getLogger(__name__ + ".bootstrap")
    bootstrap_logger.info("Initializing Pocket Commander (Functional Core Edition)...")

    # Load and resolve application configuration, including agents
    raw_app_config: Dict[str, Any] = load_and_resolve_app_config() # Calls the unified loader
    
    if raw_app_config is None:
        # Error messages are already logged by load_and_resolve_app_config
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
        # MCP tools are loaded from the already resolved raw_app_config
        load_and_register_mcp_tools_from_config(raw_app_config, global_tool_registry)
        logger.info("MCP tools loaded and registered from configuration.")
    except Exception as e:
        logger.error(f"Failed to load or register MCP tools from config: {e}", exc_info=True)

    event_bus_instance = AsyncEventBus()

    app_services_dict: Dict[str, Any] = {
        "raw_app_config": raw_app_config, # This now contains 'resolved_agents'
        "current_log_level": initial_log_level_str,
        "output_handler": None, # Will be set shortly
        "prompt_func": None,    # Will be set by TerminalInteractionFlow
        "global_tool_registry": global_tool_registry,
        "event_bus": event_bus_instance,
        "_application_state_DO_NOT_USE_DIRECTLY": None
    }
    
    app_services_typed = AppServices(**app_services_dict)

    terminal_flow = TerminalInteractionFlow(
        app_services=app_services_typed,
        process_input_callback=None 
    )
    
    output_handler_instance = TerminalOutputHandler(terminal_flow.console, app_services_typed.event_bus)
    app_services_typed.output_handler = output_handler_instance
    app_services_typed.prompt_func = terminal_flow.request_dedicated_input
    
    try:
        # create_application_core will now receive app_services_typed
        # which has raw_app_config already populated with resolved_agents
        top_level_input_processor = await create_application_core(app_services_typed)
    except Exception as e:
        logger.error(f"Failed to create application core: {e}", exc_info=True)
        if app_services_typed.output_handler:
            try:
                await app_services_typed.event_bus.publish(SystemMessageEvent(message="Critical error: Could not initialize application core.", details=str(e), message_type=SystemMessageType.ERROR, style=None))
            except Exception as e_send:
                logger.error(f"Additionally, failed to send core creation error to terminal: {e_send}")
        return

    terminal_flow.process_input_callback = top_level_input_processor
    
    await event_bus_instance.start() # Start event bus before TIF's main loop
    logger.info("Event bus started.")

    try:
        await terminal_flow.start()
    except SystemExit:
        logger.info("Application exit initiated by SystemExit (e.g., /exit command).")
    except KeyboardInterrupt:
        logger.info("Application terminated by user (KeyboardInterrupt in main).")
    finally:
        logger.info("Initiating shutdown sequence...")
        if terminal_flow._running:
            await terminal_flow.stop()
        await event_bus_instance.stop()
        logger.info("Event bus stopped.")
            
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
        print("SystemExit caught at the very end. Application has shut down.")
    except KeyboardInterrupt:
        print("Application terminated by user (KeyboardInterrupt at top level).")
    except Exception as e:
        print(f"A critical unhandled exception occurred at the top level: {e}")
        try:
            logging.critical(f"A critical unhandled exception occurred at the top level: {e}", exc_info=True)
        except: # noqa
            pass
    finally:
        logging.shutdown()