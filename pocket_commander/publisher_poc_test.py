#%%
import asyncio
import logging
import random
import signal
from pocket_commander.zeromq_eventbus_poc import ZeroMQEventBus # Assuming it's in the same package path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - PUBLISHER - %(levelname)s - %(message)s')

running = True

def handle_signal(signum, frame):
    """Handles termination signals."""
    global running
    logging.info(f"Signal {signum} received, stopping publisher...")
    running = False

async def run_publisher(bus: ZeroMQEventBus, publish_interval: float = 1.0):
    """
    Publishes various events at a set interval.
    """
    global running
    event_counter = 0
    sensor_types = ["temp", "humidity", "pressure", "light_level"]
    log_levels = ["INFO", "WARNING", "ERROR", "DEBUG"]
    system_components = ["auth_service", "data_pipeline", "api_gateway", "worker_node_alpha"]

    while running:
        event_counter += 1
        choice = random.randint(1, 3)

        try:
            if choice == 1:
                # Sensor event
                sensor = random.choice(sensor_types)
                topic = f"events.sensor.{sensor}"
                data = {
                    "value": round(random.uniform(0, 100) + (event_counter * 0.1), 2),
                    "unit": "C" if sensor == "temp" else ("%" if sensor == "humidity" else ("hPa" if sensor == "pressure" else "lux")),
                    "timestamp": asyncio.get_event_loop().time(),
                    "sensor_id": f"sensor_{random.randint(1,5)}"
                }
                await bus.publish(topic, data)
                logging.info(f"Published to '{topic}': {data}")

            elif choice == 2:
                # Log event
                level = random.choice(log_levels)
                component = random.choice(system_components)
                topic = f"events.log.{component}.{level.lower()}"
                data = {
                    "message": f"Log event number {event_counter} from {component}.",
                    "level": level,
                    "timestamp": asyncio.get_event_loop().time(),
                    "component_id": component
                }
                await bus.publish(topic, data)
                logging.info(f"Published to '{topic}': {data}")

            elif choice == 3:
                # System status event
                component = random.choice(system_components)
                status = random.choice(["OPERATIONAL", "DEGRADED", "OFFLINE"])
                topic = f"events.status.{component}"
                data = {
                    "component": component,
                    "status": status,
                    "timestamp": asyncio.get_event_loop().time(),
                    "details": f"Status update for {component}: {status}"
                }
                await bus.publish(topic, data)
                logging.info(f"Published to '{topic}': {data}")

            await asyncio.sleep(publish_interval)

        except RuntimeError as e: # Bus might not be running if stop is called
            if "Event bus is not running" in str(e) and not running:
                logging.info("Publisher stopping as event bus is not running (likely shutdown).")
                break
            else:
                logging.error(f"RuntimeError during publish: {e}", exc_info=True)
                break # Stop on other runtime errors
        except Exception as e:
            logging.error(f"Error during publishing: {e}", exc_info=True)
            # Continue or break depending on desired robustness
            if not running: # Check if shutdown was initiated during error
                break
            await asyncio.sleep(publish_interval) # Wait before retrying if an error occurred

    logging.info("Publisher loop finished.")


async def main():
    global running
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # These addresses should match the broker's frontend (XSUB)
    broker_publisher_address = "tcp://localhost:5559"
    # The subscriber address is not directly used by a pure publisher,
    # but the bus needs it for its own SUB socket if it were also subscribing.
    # For a pure publisher, we can provide a dummy or the actual one.
    # Let's provide the actual one for consistency with the bus's design.
    broker_subscriber_address = "tcp://localhost:5560"

    bus = ZeroMQEventBus(
        broker_publisher_frontend_address=broker_publisher_address,
        broker_subscriber_frontend_address=broker_subscriber_address, # Needed for bus init
        identity="test-publisher"
    )

    try:
        await bus.start() # Start the bus (connects its PUB socket)
        await run_publisher(bus, publish_interval=0.5)
    except ConnectionRefusedError:
        logging.error(f"Connection refused. Ensure the ZeroMQ broker (zmq_broker_poc.py) is running and accessible at {broker_publisher_address}.")
    except Exception as e:
        logging.critical(f"Publisher main encountered an error: {e}", exc_info=True)
    finally:
        logging.info("Publisher main: stopping event bus...")
        if bus._running: # Check if bus was successfully started
             await bus.stop()
        logging.info("Publisher main: event bus stopped.")
        # Terminate context if this is the last user of it.
        # In PoC, each script manages its own context effectively.
        if not bus.context.closed:
            bus.context.term()
            logging.info("Publisher main: ZMQ context terminated.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Publisher process terminated by KeyboardInterrupt.")
    except Exception as e:
        logging.critical(f"Publisher process failed critically: {e}", exc_info=True)
    finally:
        logging.info("Publisher process shutdown complete.")
#%%