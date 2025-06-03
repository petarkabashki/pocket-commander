import asyncio
import logging
import yaml # For loading configuration
from typing import Dict, Any, Optional
import subprocess # For managing the broker process
import sys # For python executable path

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from pocket_commander.config_loader import load_and_register_mcp_tools_from_config, load_and_resolve_app_config, AppConfig
from pocket_commander.tools.registry import global_tool_registry
from pocket_commander.utils.logging_utils import setup_logging
from pocket_commander.event_bus import ZeroMQEventBus # MODIFIED: Import ZeroMQEventBus
# SystemMessageEvent and TerminalOutputHandler might be obsolete or their roles changed
# from pocket_commander.events import SystemMessageEvent, SystemMessageType # Keep if AppCore still uses for critical errors
# from pocket_commander.commands.terminal_io import TerminalOutputHandler # Replaced by TerminalAgUIClient

# Import new core components
from pocket_commander.app_core import create_application_core, AppCore # Import AppCore class
# from pocket_commander.flows.terminal_interaction_flow import TerminalInteractionFlow # Replaced
from pocket_commander.ag_ui.terminal_client import TerminalAgUIClient # New UI Client
from pocket_commander.types import AppServices

logging.basicConfig(
    level=logging.DEBUG,           # set root level to DEBUG
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


async def main():
    print("PRINT: main() function started.", flush=True) # AI! Add print
    bootstrap_logger = logging.getLogger(__name__ + ".bootstrap")
    # bootstrap_logger.info("Initializing Pocket Commander (ZeroMQ Edition)...") # Defer this until after logging is set up

    app_config: Optional[AppConfig] = load_and_resolve_app_config()
    
    if app_config is None:
        print("CRITICAL: Failed to load or resolve application configuration. Exiting.", flush=True) # AI! Add flush
        # bootstrap_logger.critical("Failed to load or resolve application configuration. Exiting.") # Logging not set up yet
        return
    # bootstrap_logger.info("Application configuration loaded and agents resolved successfully.") # Logging not set up yet
    print("PRINT: App config loaded. About to call setup_logging.", flush=True) # AI! Add print

    initial_log_level_str = setup_logging(app_config) 
    logger = logging.getLogger(__name__) # Now it's safe to get and use loggers
    logger.info("Initializing Pocket Commander (ZeroMQ Edition)...") # Moved here
    logger.info("Application configuration loaded and agents resolved successfully.") # Moved here
    logger.info(f"Logging system configured. Initial global log level: {initial_log_level_str}")

    # Start ZMQ Broker Subprocess
    broker_process: Optional[asyncio.subprocess.Process] = None
    if app_config.zeromq_event_bus: # Check if ZMQ is configured for broker
        try:
            broker_script_path = "pocket_commander/zmq_broker_poc.py"
            cmd = [sys.executable, "-u", broker_script_path] # -u for unbuffered output
            logger.info(f"Attempting to start ZMQ broker: {' '.join(cmd)}")
            broker_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            logger.info(f"ZMQ broker process started with PID: {broker_process.pid}")
            await asyncio.sleep(1) # Give broker a moment to start
        except Exception as e:
            logger.error(f"Failed to start ZMQ broker process: {e}", exc_info=True)
            # Decide if this is a critical failure. For now, allow continuation
            # if an external broker might be used or for robust startup.
    else:
        logger.warning("ZeroMQ event bus not configured in app_config. Broker not started by main.py.")

    # MODIFIED: Instantiate and start ZeroMQEventBus
    event_bus_instance: Optional[ZeroMQEventBus] = None
    if app_config.zeromq_event_bus:
        zmq_conf = app_config.zeromq_event_bus
        logger.info(f"Initializing ZeroMQEventBus with pub: {zmq_conf.broker_publisher_frontend_address}, sub: {zmq_conf.broker_subscriber_frontend_address}")
        event_bus_instance = ZeroMQEventBus(
            broker_publisher_frontend_address=zmq_conf.broker_publisher_frontend_address,
            broker_subscriber_frontend_address=zmq_conf.broker_subscriber_frontend_address
        )
        try:
            await event_bus_instance.start()
            logger.info("ZeroMQEventBus started successfully.")
            logger.info("THIS IS A TEST LOG FROM MAIN.PY AFTER EVENT BUS START.") # AI! Add test log
        except Exception as e:
            logger.critical(f"Failed to start ZeroMQEventBus: {e}", exc_info=True)
            # Terminate broker if it was started
            if broker_process and broker_process.returncode is None:
                logger.info("Terminating broker process due to event bus start failure...")
                broker_process.terminate()
                await broker_process.wait()
            return # Critical failure if event bus cannot start
    else:
        logger.critical("ZeroMQEventBus configuration missing in app_config. Cannot proceed.")
        # Terminate broker if it was started
        if broker_process and broker_process.returncode is None:
            logger.info("Terminating broker process due to missing event bus config...")
            broker_process.terminate()
            await broker_process.wait()
        return

    try:
        tools_package_path = "pocket_commander/tools"
        tools_module_path = "pocket_commander.tools"
        logger.info(f"Scanning for native tools in: {tools_package_path} (module: {tools_module_path})")
        global_tool_registry.scan_and_register_tools(tools_package_path, tools_module_path)
        logger.info("Native tools scanned and registered.")
    except Exception as e:
        logger.error(f"Failed to scan or register native tools: {e}", exc_info=True)
    try:
        load_and_register_mcp_tools_from_config(app_config, global_tool_registry)
        logger.info("MCP tools loaded and registered from configuration.")
    except Exception as e:
        logger.error(f"Failed to load or register MCP tools from config: {e}", exc_info=True)

    app_services_dict: Dict[str, Any] = {
        "raw_app_config": app_config,
        "current_log_level": initial_log_level_str,
        "output_handler": None, 
        "prompt_func": None,    
        "global_tool_registry": global_tool_registry,
        "event_bus": event_bus_instance, # MODIFIED: Pass the created bus instance
        "_application_state_DO_NOT_USE_DIRECTLY": None,
        "get_current_agent_slug": None,
        "get_available_agents": None,
        "request_agent_switch": None,
    }
    
    app_services_typed = AppServices(**app_services_dict)
    
    app_core_instance: Optional[AppCore] = None
    ui_client_instance: Optional[TerminalAgUIClient] = None

    try:
        # Create and initialize AppCore first
        # AppCore will receive the ZeroMQEventBus via app_services_typed
        app_core_instance = await create_application_core(app_services_typed)
        logger.info("Application core created and initialized.")

        # Now that AppCore is created, populate its methods into AppServices
        if app_core_instance:
            app_services_typed.get_current_agent_slug = app_core_instance.get_current_agent_slug
            app_services_typed.get_available_agents = app_core_instance.get_available_agents
            app_services_typed.request_agent_switch = app_core_instance.request_agent_switch
            # MODIFIED: app_services_typed.event_bus is already set, AppCore uses it.
            logger.info("AppServices populated with AppCore methods.")
        else:
            raise RuntimeError("AppCore instance was not created successfully.")

        # Create UI Client
        ui_client_instance = TerminalAgUIClient(app_services=app_services_typed, client_id="main_terminal")

        # AI! Assign ui_client_instance to app_core_instance
        if app_core_instance and ui_client_instance:
            app_core_instance.ui_client = ui_client_instance
            logger.info("Assigned UI client instance to AppCore.")
        elif not app_core_instance:
            logger.error("Cannot assign UI client to AppCore because AppCore instance is missing.")
        elif not ui_client_instance:
            logger.error("Cannot assign UI client to AppCore because UI Client instance is missing.")
            
    except Exception as e:
        logger.error(f"Failed to create application core or UI client: {e}", exc_info=True)
        print(f"Critical error during initialization: {e}")
        # Shutdown sequence for early exit
        if event_bus_instance: # MODIFIED: Check if bus instance exists
            logger.info("Stopping event bus due to initialization error...")
            await event_bus_instance.stop()
            logger.info("Event bus stopped.")
        if broker_process and broker_process.returncode is None:
            logger.info("Terminating broker process due to initialization error...")
            broker_process.terminate()
            await broker_process.wait()
            logger.info("Broker process terminated.")
        return

    try:
        if ui_client_instance:
            await ui_client_instance.start() 
            logger.info("Terminal UI Client started.")
            
            if ui_client_instance._main_loop_task: 
                await ui_client_instance._main_loop_task 
            else: 
                # Fallback loop if main_loop_task isn't running for some reason (should not happen)
                while ui_client_instance._running: 
                    await asyncio.sleep(0.1) # Check more frequently
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
        
        if app_core_instance: 
            logger.info("Shutting down Application Core...")
            await app_core_instance.shutdown() 
            logger.info("Application Core shut down.")
        
        # MODIFIED: Stop the event bus managed by main.py
        if event_bus_instance:
            logger.info("Stopping event bus...")
            await event_bus_instance.stop()
            logger.info("Event bus stopped.")

        if broker_process and broker_process.returncode is None:
            logger.info("Terminating ZMQ broker process...")
            broker_process.terminate()
            try:
                await asyncio.wait_for(broker_process.wait(), timeout=5.0)
                logger.info("ZMQ broker process terminated gracefully.")
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for ZMQ broker to terminate. Sending SIGKILL...")
                broker_process.kill()
                await broker_process.wait()
                logger.info("ZMQ broker process killed.")
            except Exception as e:
                logger.error(f"Error during broker termination: {e}", exc_info=True)
            
    logger.info("Pocket Commander (ZeroMQ Edition) exited.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except SystemExit:
        # This can happen if ui_client_instance.start() raises SystemExit (e.g. /exit command)
        # and the exception is not caught by the try/except SystemExit block in main's loop.
        # Or if main() itself raises SystemExit before the main loop.
        print("SystemExit caught at the very end. Application has shut down.")
    except KeyboardInterrupt:
        print("\nApplication terminated by user (KeyboardInterrupt at top level).")
    except Exception as e:
        # This catches exceptions that might occur outside the main try/finally block in main(),
        # or if asyncio.run() itself fails.
        print(f"A critical unhandled exception occurred at the top level: {e}")
        # Try to log, but be careful as logging might be part of the problem.
        try:
            logging.critical(f"A critical unhandled exception occurred at the top level: {e}", exc_info=True)
        except: # noqa
            pass # Avoid further errors if logging fails
    finally:
        # Ensure logging resources are released.
        logging.shutdown()