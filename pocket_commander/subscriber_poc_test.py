#%%
import asyncio
import logging
import signal
import uuid # For potential use if needed, though bus handles sub_ids
from pocket_commander.zeromq_eventbus_poc import ZeroMQEventBus # Assuming it's in the same package path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - SUBSCRIBER - %(levelname)s - %(message)s')

running = True
keep_subscriber_running_event = asyncio.Event()

def handle_signal(signum, frame):
    """Handles termination signals."""
    global running
    logging.info(f"Signal {signum} received, stopping subscriber...")
    running = False
    keep_subscriber_running_event.set() # Signal the main loop to exit

# --- Example Handler Coroutines ---
async def generic_sensor_handler(topic: str, data: dict):
    logging.info(f"[HANDLER SensorGeneric] Topic: '{topic}', Data: {data} (Priority 0)")

async def temp_sensor_high_priority_handler(topic: str, data: dict):
    logging.info(f"[HANDLER TempSpecific] Topic: '{topic}', Data: {data} (Priority -10)")
    if data.get("value", 0) > 50 and topic.endswith(".temp"):
        logging.info(f"  [HANDLER TempSpecific] Temperature {data.get('value')} > 50. Consuming event.")
        return ZeroMQEventBus.CONSUMED # Test consumption

async def temp_sensor_low_priority_handler(topic: str, data: dict):
    # This should not run if the high_priority_handler consumed the event for temp > 50
    logging.info(f"[HANDLER TempLowPri] Topic: '{topic}', Data: {data} (Priority 10)")

async def all_events_handler(topic: str, data: dict):
    logging.info(f"[HANDLER AllEvents] Topic: '{topic}', Data: {data} (Priority 100)")

async def log_error_handler(topic: str, data: dict):
    logging.info(f"[HANDLER LogError] Topic: '{topic}', Data: {data} (Priority 0)")

async def status_degraded_handler(topic: str, data: dict):
    logging.info(f"[HANDLER StatusDegraded] Topic: '{topic}', Data: {data} (Priority 5)")


# --- Example Custom Filter Functions ---
def humidity_filter_high_value(topic: str, data: dict) -> bool:
    """Only pass if topic is for humidity and value is > 70."""
    is_humidity = "humidity" in topic
    value_high = data.get("value", 0) > 70
    # logging.debug(f"  [FILTER HumidityHigh] Topic: '{topic}', Value: {data.get('value')}, IsHumidity: {is_humidity}, ValueHigh: {value_high}")
    return is_humidity and value_high

def log_component_filter(topic: str, data: dict) -> bool:
    """Only pass if log is from 'auth_service'."""
    is_auth_log = "auth_service" in topic and "log" in topic
    # logging.debug(f"  [FILTER LogAuth] Topic: '{topic}', IsAuthLog: {is_auth_log}")
    return is_auth_log


async def run_subscriber(bus: ZeroMQEventBus):
    """
    Subscribes to various event patterns and logs received events.
    """
    global running

    # Subscription 1: Generic sensor events
    sub_id_sensor_generic = await bus.subscribe(
        topic_pattern="events.sensor.*",
        handler_coroutine=generic_sensor_handler,
        priority=0
    )
    logging.info(f"Subscribed generic_sensor_handler with ID: {sub_id_sensor_generic}")

    # Subscription 2: Specific temp sensor event, high priority, consumes if value > 50
    sub_id_temp_specific = await bus.subscribe(
        topic_pattern="events.sensor.temp",
        handler_coroutine=temp_sensor_high_priority_handler,
        priority=-10 # Higher priority
    )
    logging.info(f"Subscribed temp_sensor_high_priority_handler with ID: {sub_id_temp_specific}")

    # Subscription 3: Specific temp sensor event, lower priority
    sub_id_temp_low_pri = await bus.subscribe(
        topic_pattern="events.sensor.temp", # Same pattern as above
        handler_coroutine=temp_sensor_low_priority_handler,
        priority=10 # Lower priority
    )
    logging.info(f"Subscribed temp_sensor_low_priority_handler with ID: {sub_id_temp_low_pri}")
    
    # Subscription 4: All events (wildcard) - lowest priority
    sub_id_all_events = await bus.subscribe(
        topic_pattern="events.*", # Broad pattern
        handler_coroutine=all_events_handler,
        priority=100
    )
    logging.info(f"Subscribed all_events_handler with ID: {sub_id_all_events}")

    # Subscription 5: Log errors
    sub_id_log_error = await bus.subscribe(
        topic_pattern="events.log.*.error",
        handler_coroutine=log_error_handler,
        priority=0
    )
    logging.info(f"Subscribed log_error_handler with ID: {sub_id_log_error}")

    # Subscription 6: Humidity sensor events with custom filter for high values
    sub_id_humidity_filtered = await bus.subscribe(
        topic_pattern="events.sensor.humidity",
        handler_coroutine=generic_sensor_handler, # Reusing generic handler
        priority=1, # Give it a slightly different priority for observation
        custom_filter_function=humidity_filter_high_value
    )
    logging.info(f"Subscribed generic_sensor_handler (for humidity > 70) with ID: {sub_id_humidity_filtered}")

    # Subscription 7: Log events from a specific component using a filter
    sub_id_log_auth_filtered = await bus.subscribe(
        topic_pattern="events.log.*", # Broad log pattern
        handler_coroutine=log_error_handler, # Reusing log error handler for demo
        priority=2,
        custom_filter_function=log_component_filter
    )
    logging.info(f"Subscribed log_error_handler (for auth_service logs) with ID: {sub_id_log_auth_filtered}")

    # Subscription 8: Status degraded
    sub_id_status_degraded = await bus.subscribe(
        topic_pattern="events.status.*",
        handler_coroutine=status_degraded_handler,
        priority=5,
        custom_filter_function=lambda t, d: d.get("status") == "DEGRADED"
    )
    logging.info(f"Subscribed status_degraded_handler with ID: {sub_id_status_degraded}")


    logging.info("Subscriber setup complete. Listening for events...")
    logging.info("Press Ctrl+C to stop.")
    
    # Keep running until signal is received
    await keep_subscriber_running_event.wait()

    # Example of unsubscribing (optional, for testing)
    # if running: # Only if not shutting down already
    #     logging.info("Attempting to unsubscribe from generic sensor handler...")
    #     unsub_success = await bus.unsubscribe(sub_id_sensor_generic)
    #     logging.info(f"Unsubscribe successful for sub_id_sensor_generic: {unsub_success}")

    logging.info("Subscriber loop finished.")


async def main():
    global running
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # This address should match the broker's backend (XPUB)
    broker_subscriber_address = "tcp://localhost:5560"
    # The publisher address is not directly used by a pure subscriber,
    # but the bus needs it for its own PUB socket if it were also publishing.
    broker_publisher_address = "tcp://localhost:5559"


    bus = ZeroMQEventBus(
        broker_publisher_frontend_address=broker_publisher_address, # Needed for bus init
        broker_subscriber_frontend_address=broker_subscriber_address,
        identity="test-subscriber"
    )

    try:
        await bus.start() # Start the bus (connects its SUB socket and starts receive loop)
        await run_subscriber(bus)
    except ConnectionRefusedError:
        logging.error(f"Connection refused. Ensure the ZeroMQ broker (zmq_broker_poc.py) is running and accessible at {broker_subscriber_address}.")
    except Exception as e:
        logging.critical(f"Subscriber main encountered an error: {e}", exc_info=True)
    finally:
        logging.info("Subscriber main: stopping event bus...")
        if bus._running: # Check if bus was successfully started
            await bus.stop()
        logging.info("Subscriber main: event bus stopped.")
        # Terminate context if this is the last user of it.
        if not bus.context.closed:
            bus.context.term()
            logging.info("Subscriber main: ZMQ context terminated.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt: # This might be caught by the signal handler first
        logging.info("Subscriber process terminated by KeyboardInterrupt in __main__.")
    except Exception as e:
        logging.critical(f"Subscriber process failed critically: {e}", exc_info=True)
    finally:
        logging.info("Subscriber process shutdown complete.")

#%%