#%%
import zmq
import zmq
import zmq.asyncio
import asyncio
import json
import uuid
import logging
import signal
from typing import Callable, Coroutine, Any, Optional, Dict, List, Tuple
from fnmatch import fnmatch

# Logging will be configured by the main application

class ZeroMQEventBus:
    """
    A ZeroMQ-based event bus for asynchronous event publishing and subscribing.
    Uses a PUB/SUB pattern with a central broker (XPUB/XSUB forwarder).
    Event data is transported as JSON-serialized Python dictionaries.
    Supports hierarchical topics, fnmatch-style topic patterns for subscription,
    custom filter functions, and local handler priority.
    """
    CONSUMED = object()  # Sentinel to indicate an event has been consumed locally

    def __init__(self,
                 broker_publisher_frontend_address: str,
                 broker_subscriber_frontend_address: str,
                 identity: Optional[str] = None):
        """
        Initializes the ZeroMQEventBus.

        Args:
            broker_publisher_frontend_address: ZMQ address of the broker's XSUB socket (where this bus will publish).
            broker_subscriber_frontend_address: ZMQ address of the broker's XPUB socket (where this bus will subscribe).
            identity: Optional unique string for this event bus instance (for logging/debugging).
        """
        self.broker_publisher_addr = broker_publisher_frontend_address
        self.broker_subscriber_addr = broker_subscriber_frontend_address
        self.identity = identity or f"eventbus-{uuid.uuid4().hex[:8]}"

        self.context = zmq.asyncio.Context()
        self.pub_socket: Optional[zmq.asyncio.Socket] = None
        self.sub_socket: Optional[zmq.asyncio.Socket] = None

        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._zmq_topic_subscriptions: Dict[bytes, int] = {} # Ref count for ZMQ SUB socket subscriptions
        self._receive_loop_task: Optional[asyncio.Task] = None
        self._running = False

        logging.info(f"[{self.identity}] Initialized. Publisher Addr: {self.broker_publisher_addr}, Subscriber Addr: {self.broker_subscriber_addr}")

    async def start(self):
        """
        Starts the event bus: creates and connects sockets, starts the message receiving loop.
        """
        if self._running:
            logging.warning(f"[{self.identity}] Event bus is already running.")
            return

        self.pub_socket = self.context.socket(zmq.PUB)
        try:
            self.pub_socket.connect(self.broker_publisher_addr)
            logging.info(f"[{self.identity}] PUB socket connected to {self.broker_publisher_addr}")
        except zmq.error.ZMQError as e:
            logging.error(f"[{self.identity}] Failed to connect PUB socket to {self.broker_publisher_addr}: {e}")
            self.pub_socket.close()
            self.pub_socket = None
            raise

        self.sub_socket = self.context.socket(zmq.SUB)
        try:
            self.sub_socket.connect(self.broker_subscriber_addr)
            logging.info(f"[{self.identity}] SUB socket connected to {self.broker_subscriber_addr}")
        except zmq.error.ZMQError as e:
            logging.error(f"[{self.identity}] Failed to connect SUB socket to {self.broker_subscriber_addr}: {e}")
            self.sub_socket.close()
            self.sub_socket = None
            if self.pub_socket: # cleanup pub socket if sub failed
                self.pub_socket.close()
                self.pub_socket = None
            raise
        
        # Resubscribe to all necessary ZMQ topics based on current _subscriptions
        # This is important if start() is called after some subscribe() calls were made before a previous stop()
        # or if we want to allow subscribe() calls before start().
        for sub_id, sub_details in self._subscriptions.items():
            self._ensure_zmq_subscription(sub_details['topic_pattern'])


        self._running = True
        logging.info(f"[{self.identity}] Creating _receive_loop_task...") # ADDED
        self._receive_loop_task = asyncio.create_task(self._receive_messages())
        logging.info(f"[{self.identity}] _receive_loop_task created: {self._receive_loop_task}. Event bus started. Receiving messages...") # MODIFIED

    async def stop(self):
        """
        Stops the event bus: stops the message receiving loop, closes sockets.
        """
        if not self._running:
            logging.warning(f"[{self.identity}] Event bus is not running.")
            return

        self._running = False
        if self._receive_loop_task:
            try:
                # Give the loop a chance to finish processing current message or timeout
                await asyncio.wait_for(self._receive_loop_task, timeout=1.0)
            except asyncio.TimeoutError:
                logging.warning(f"[{self.identity}] Receive loop timed out during stop. Cancelling.")
                self._receive_loop_task.cancel()
            except Exception as e:
                logging.error(f"[{self.identity}] Error during receive loop shutdown: {e}")
            finally:
                 # Ensure task is awaited if cancelled
                if self._receive_loop_task.cancelled() or not self._receive_loop_task.done():
                    try:
                        await self._receive_loop_task # Wait for cancellation to complete
                    except asyncio.CancelledError:
                        logging.info(f"[{self.identity}] Receive loop task successfully cancelled.")
                    except Exception as e:
                        logging.error(f"[{self.identity}] Exception while awaiting cancelled receive loop: {e}")


        if self.pub_socket:
            self.pub_socket.close()
            self.pub_socket = None
            logging.info(f"[{self.identity}] PUB socket closed.")
        if self.sub_socket:
            self.sub_socket.close()
            self.sub_socket = None
            logging.info(f"[{self.identity}] SUB socket closed.")
        
        # Context termination should happen when all event bus instances are done
        # For PoC, we might close it here, but in a real app, context might be shared or managed globally.
        # if not self.context.closed:
        #     self.context.term()
        #     logging.info(f"[{self.identity}] ZMQ context terminated.")
        logging.info(f"[{self.identity}] Event bus stopped.")

    async def publish(self, topic: str, event_data: dict):
        """
        Publishes an event.

        Args:
            topic: The full hierarchical topic string for the event.
            event_data: Python dictionary representing the event.
        
        Raises:
            TypeError: If event_data is not a dict.
            RuntimeError: If the event bus is not running or PUB socket is not available.
        """
        logging.info(f"[{self.identity}] Attempting to PUBLISH. Running: {self._running}, Pub Socket: {self.pub_socket is not None}") # ADDED
        if not self._running or not self.pub_socket:
            logging.error(f"[{self.identity}] Cannot publish: Event bus not running or PUB socket unavailable.")
            # Avoid raising RuntimeError to see if other parts of the system log issues
            # This might mask the problem if publish is called when bus is not ready,
            # but for debugging lack of logs, this might reveal if publish is even attempted.
            # Consider re-adding 'raise' later if this doesn't help.
            return # MODIFIED: from raise to return for now
        if not isinstance(event_data, dict):
            logging.error(f"[{self.identity}] Cannot publish: event_data must be a dict. Got {type(event_data)}")
            raise TypeError(f"event_data must be a dict, got {type(event_data)}")

        try:
            json_payload = json.dumps(event_data)
            topic_bytes = topic.encode('utf-8')
            payload_bytes = json_payload.encode('utf-8')

            await self.pub_socket.send_multipart([topic_bytes, payload_bytes])
            logging.info(f"[{self.identity}] PUBLISHING to topic '{topic}': {json.dumps(event_data)[:150]}...") # INFO level for visibility
        except Exception as e:
            logging.error(f"[{self.identity}] Error publishing to topic '{topic}': {e}", exc_info=True)
            # Potentially re-raise or handle more gracefully depending on requirements

    def _get_broadest_zmq_prefix(self, topic_pattern: str) -> bytes:
        """
        Determines the broadest ZMQ topic prefix for a given fnmatch pattern.
        E.g., "app.core.*.event" -> "app.core."
        E.g., "*.event" -> "" (subscribe to all)
        """
        if '*' not in topic_pattern and '?' not in topic_pattern and '[' not in topic_pattern:
            # If no wildcards, it's a literal prefix (or full topic)
            return topic_pattern.encode('utf-8')
        
        parts = topic_pattern.split('.')
        broad_prefix_parts = []
        for part in parts:
            if '*' in part or '?' in part or '[' in part:
                break
            broad_prefix_parts.append(part)
        
        if not broad_prefix_parts:
            return b"" # Subscribe to all ZMQ topics if pattern starts with wildcard
        
        return ('.'.join(broad_prefix_parts) + '.').encode('utf-8')


    def _ensure_zmq_subscription(self, topic_pattern: str):
        """Ensures the SUB socket is subscribed to the necessary ZMQ prefix for the pattern."""
        if not self.sub_socket or self.sub_socket.closed:
            # logging.warning(f"[{self.identity}] SUB socket not available for ZMQ subscription based on pattern '{topic_pattern}'. Will attempt on start.")
            return

        zmq_prefix = self._get_broadest_zmq_prefix(topic_pattern)
        if self._zmq_topic_subscriptions.get(zmq_prefix, 0) == 0:
            try:
                self.sub_socket.subscribe(zmq_prefix)
                logging.info(f"[{self.identity}] SUB socket subscribed to ZMQ prefix: '{zmq_prefix.decode()}' for pattern '{topic_pattern}'")
            except zmq.error.ZMQError as e:
                logging.error(f"[{self.identity}] Failed to subscribe SUB socket to ZMQ prefix '{zmq_prefix.decode()}': {e}")
                return # Don't increment count if subscribe failed
        
        self._zmq_topic_subscriptions[zmq_prefix] = self._zmq_topic_subscriptions.get(zmq_prefix, 0) + 1


    def _try_zmq_unsubscribe(self, topic_pattern: str):
        """Decrements ref count for a ZMQ prefix and unsubscribes if count reaches zero."""
        if not self.sub_socket or self.sub_socket.closed:
            return

        zmq_prefix = self._get_broadest_zmq_prefix(topic_pattern)
        if zmq_prefix in self._zmq_topic_subscriptions:
            self._zmq_topic_subscriptions[zmq_prefix] -= 1
            if self._zmq_topic_subscriptions[zmq_prefix] <= 0:
                try:
                    self.sub_socket.unsubscribe(zmq_prefix)
                    logging.info(f"[{self.identity}] SUB socket unsubscribed from ZMQ prefix: '{zmq_prefix.decode()}' (due to pattern '{topic_pattern}')")
                except zmq.error.ZMQError as e:
                    logging.error(f"[{self.identity}] Failed to unsubscribe SUB socket from ZMQ prefix '{zmq_prefix.decode()}': {e}")
                del self._zmq_topic_subscriptions[zmq_prefix]


    async def subscribe(self,
                        topic_pattern: str,
                        handler_coroutine: Callable[[str, dict], Coroutine[Any, Any, Any]],
                        priority: int = 0,
                        custom_filter_function: Optional[Callable[[str, dict], bool]] = None
                        ) -> str:
        """
        Subscribes a handler coroutine to events matching a topic pattern.

        Args:
            topic_pattern: fnmatch-style pattern for topics (e.g., "app.core.*").
            handler_coroutine: Async function to call with (actual_topic: str, event_data: dict).
            priority: Local execution priority (lower numbers execute first).
            custom_filter_function: Optional function (topic, data) -> bool for further filtering.

        Returns:
            A unique subscription ID (str).
        """
        subscription_id = str(uuid.uuid4())
        self._subscriptions[subscription_id] = {
            'topic_pattern': topic_pattern,
            'handler': handler_coroutine,
            'priority': priority,
            'custom_filter': custom_filter_function,
            'id': subscription_id
        }
        
        # Ensure ZMQ subscription if bus is running, otherwise it will be handled on start
        if self._running and self.sub_socket and not self.sub_socket.closed:
            self._ensure_zmq_subscription(topic_pattern)
        elif not self._running and not self.sub_socket : # if called before start
             pass # ZMQ subscription will be handled by start() iterating _subscriptions
        
        logging.info(f"[{self.identity}] Handler subscribed with ID {subscription_id} to pattern '{topic_pattern}', priority {priority}")
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribes a handler.

        Args:
            subscription_id: The string ID returned by subscribe().

        Returns:
            True if unsubscribed, False if ID not found.
        """
        if subscription_id in self._subscriptions:
            sub_details = self._subscriptions.pop(subscription_id)
            topic_pattern = sub_details['topic_pattern']
            
            # Attempt to unsubscribe from ZMQ prefix if bus is running
            if self._running and self.sub_socket and not self.sub_socket.closed:
                 self._try_zmq_unsubscribe(topic_pattern)
            elif not self._running and not self.sub_socket: # if called before start
                # If bus hasn't started, ZMQ subscriptions haven't happened yet.
                # We just need to ensure that when start() runs, it doesn't try to subscribe for this removed handler.
                # This is implicitly handled as _subscriptions is already updated.
                pass

            logging.info(f"[{self.identity}] Unsubscribed handler with ID {subscription_id} from pattern '{topic_pattern}'")
            return True
        logging.warning(f"[{self.identity}] Unsubscribe failed: ID {subscription_id} not found.")
        return False

    async def _receive_messages(self):
        """
        Internal loop to receive messages from the SUB socket and dispatch them.
        """
        logging.info(f"[{self.identity}] _receive_messages task started. Running: {self._running}, Sub Socket: {self.sub_socket is not None}") # ADDED
        if not self.sub_socket:
            logging.error(f"[{self.identity}] Cannot receive messages: SUB socket is not initialized.")
            self._running = False # Stop the bus if socket is bad
            return

        while self._running:
            try:
                logging.info(f"[{self.identity}] _receive_messages: Top of loop. Waiting for message on SUB socket...") # ADDED
                # logging.debug(f"[{self.identity}] Waiting for message on SUB socket...")
                topic_bytes, payload_bytes = await self.sub_socket.recv_multipart()
                
                actual_topic = topic_bytes.decode('utf-8')
                event_data_dict: dict = json.loads(payload_bytes.decode('utf-8'))
                logging.info(f"[{self.identity}] RECEIVED on topic '{actual_topic}': {json.dumps(event_data_dict)[:150]}...") # INFO level for visibility

                matched_handlers: List[Dict[str, Any]] = []
                for sub_id, sub_details in list(self._subscriptions.items()): # Iterate copy in case of unsubscribe within handler
                    if fnmatch(actual_topic, sub_details['topic_pattern']):
                        if sub_details['custom_filter']:
                            try:
                                if not sub_details['custom_filter'](actual_topic, event_data_dict):
                                    continue # Custom filter returned False
                            except Exception as cf_exc:
                                logging.error(f"[{self.identity}] Custom filter for pattern '{sub_details['topic_pattern']}' raised an exception: {cf_exc}", exc_info=True)
                                continue # Skip handler if filter errors
                        matched_handlers.append(sub_details)
                
                if not matched_handlers:
                    continue

                # Sort handlers by priority (lower number = higher priority)
                matched_handlers.sort(key=lambda s: s['priority'])

                for handler_details in matched_handlers:
                    try:
                        # logging.debug(f"[{self.identity}] Invoking handler for topic '{actual_topic}', pattern '{handler_details['topic_pattern']}'")
                        result = await handler_details['handler'](actual_topic, event_data_dict)
                        if result == ZeroMQEventBus.CONSUMED:
                            # logging.debug(f"[{self.identity}] Event on topic '{actual_topic}' consumed by handler for pattern '{handler_details['topic_pattern']}'")
                            break # Stop processing this event for other local handlers
                    except Exception as e:
                        logging.error(f"[{self.identity}] Handler for pattern '{handler_details['topic_pattern']}' raised an exception on topic '{actual_topic}': {e}", exc_info=True)
                        # Decide if one handler erroring should stop others (for now, it continues)
            
            except zmq.error.ContextTerminated:
                logging.info(f"[{self.identity}] Context terminated, stopping receive loop.")
                self._running = False
                break
            except zmq.error.ZMQError as e:
                if e.errno == zmq.ETERM: # Context terminated
                    logging.info(f"[{self.identity}] ZMQ ETERM received, stopping receive loop.")
                elif e.errno == zmq.EAGAIN : # zmq.EAGAIN can happen if recv is non-blocking and no message
                    # This shouldn't happen with await recv_multipart unless timeout is used,
                    # but good to be aware of. Our poller loop in broker uses timeout.
                    # Here, recv_multipart is blocking.
                    logging.warning(f"[{self.identity}] ZMQ EAGAIN received unexpectedly: {e}")
                    await asyncio.sleep(0.01) # Brief pause
                    continue
                else:
                    logging.error(f"[{self.identity}] ZMQError in receive loop: {e.errno} - {e}", exc_info=True)
                
                if not self._running: # If stop was called during the error
                    break
                # Consider if some ZMQErrors should stop the loop
                await asyncio.sleep(0.1) # Avoid tight loop on persistent ZMQ errors
            except json.JSONDecodeError as e:
                logging.error(f"[{self.identity}] Failed to decode JSON payload: {e}. Payload (bytes): {payload_bytes[:200]}...", exc_info=True)
            except UnicodeDecodeError as e:
                logging.error(f"[{self.identity}] Failed to decode topic or payload from UTF-8: {e}", exc_info=True)
            except asyncio.CancelledError:
                logging.info(f"[{self.identity}] Receive loop task cancelled.")
                self._running = False # Ensure loop terminates
                raise # Re-raise to allow stop() to await cancellation
            except Exception as e:
                logging.error(f"[{self.identity}] Unexpected error in receive loop: {e}", exc_info=True)
                if not self._running:
                    break
                await asyncio.sleep(1) # Pause before retrying after unknown error

        logging.info(f"[{self.identity}] Message receiving loop finished.")

    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

# Example Usage (for testing within this file, normally in separate test scripts)
async def example_handler_generic(topic: str, data: dict):
    logging.info(f"HANDLER_GENERIC Received on topic '{topic}': {data} (Priority 0)")

async def example_handler_specific(topic: str, data: dict):
    logging.info(f"HANDLER_SPECIFIC Received on topic '{topic}': {data} (Priority -1)")
    if data.get("value", 0) > 150:
        logging.info(f"HANDLER_SPECIFIC Consuming event for value > 150 on topic {topic}")
        return ZeroMQEventBus.CONSUMED

async def example_handler_another(topic: str, data: dict):
    logging.info(f"HANDLER_ANOTHER Received on topic '{topic}': {data} (Priority 1)")

def example_custom_filter(topic: str, data: dict) -> bool:
    is_sensor_event = topic.startswith("events.sensor.")
    has_value_key = "value" in data
    logging.debug(f"CUSTOM_FILTER for topic '{topic}', data keys '{list(data.keys())}': is_sensor={is_sensor_event}, has_value={has_value_key}")
    return is_sensor_event and has_value_key


async def main_test():
    # Ensure broker is running first (e.g., pocket_commander/zmq_broker_poc.py)
    # This test assumes broker is at default tcp://localhost:5559 (PUB frontend) and tcp://localhost:5560 (SUB frontend)
    
    bus = ZeroMQEventBus(
        broker_publisher_frontend_address="tcp://localhost:5559",
        broker_subscriber_frontend_address="tcp://localhost:5560",
        identity="test-bus"
    )

    # Test subscribe before start
    sub_id_generic_before_start = await bus.subscribe("events.*", example_handler_generic, priority=0)
    
    await bus.start()

    sub_id_specific = await bus.subscribe("events.sensor.temp", example_handler_specific, priority=-1)
    sub_id_another = await bus.subscribe("events.sensor.*", example_handler_another, priority=1)
    sub_id_filtered = await bus.subscribe("events.sensor.humidity", example_handler_generic, priority=0, custom_filter_function=example_custom_filter)
    # This one should not match humidity if filter is correct
    sub_id_no_filter_match = await bus.subscribe("events.log.system", example_handler_generic, priority=0, custom_filter_function=example_custom_filter)


    logging.info("Publishing test events...")
    await bus.publish("events.sensor.temp", {"value": 100, "unit": "C"})
    await asyncio.sleep(0.1)
    await bus.publish("events.sensor.temp", {"value": 200, "unit": "C"}) # Should be consumed by specific_handler
    await asyncio.sleep(0.1)
    await bus.publish("events.sensor.humidity", {"value": 60, "unit": "%"}) # Should be caught by filtered and generic
    await asyncio.sleep(0.1)
    await bus.publish("events.log.system", {"message": "System boot", "level": "INFO"}) # Caught by generic, not by filter
    await asyncio.sleep(0.1)

    # Test unsubscribe
    unsub_result = await bus.unsubscribe(sub_id_another)
    logging.info(f"Unsubscribe result for sub_id_another: {unsub_result}")
    await bus.publish("events.sensor.pressure", {"value": 1012, "unit": "hPa"}) # another_handler should not fire

    logging.info("Waiting for a bit to ensure messages are processed...")
    await asyncio.sleep(2)  # Wait for messages to be processed by handlers

    await bus.stop()
    
    # Test context manager
    logging.info("Testing context manager...")
    async with ZeroMQEventBus( "tcp://localhost:5559", "tcp://localhost:5560", "ctx-mgr-bus") as bus2:
        sub_ctx = await bus2.subscribe("ctx.test", example_handler_generic)
        await bus2.publish("ctx.test", {"data": "from_context_manager"})
        await asyncio.sleep(0.5)
    logging.info("Context manager test finished.")


if __name__ == "__main__":
    # This is for standalone testing of the event bus class.
    # Make sure the zmq_broker_poc.py is running separately.
    try:
        asyncio.run(main_test())
    except KeyboardInterrupt:
        logging.info("Event bus test process terminated by KeyboardInterrupt.")
    except ConnectionRefusedError:
        logging.error("Connection refused. Make sure the ZeroMQ broker (zmq_broker_poc.py) is running.")
    except Exception as e:
        logging.critical(f"Event bus test process failed critically: {e}", exc_info=True)

#%%