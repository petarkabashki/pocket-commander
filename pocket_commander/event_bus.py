#%%
# pocket_commander/zeromq_eventbus_poc.py
import asyncio
import json
import uuid
import fnmatch
from typing import Callable, Coroutine, Any, Optional, Dict, List, Tuple

import zmq
import zmq.asyncio
# import logging # Will add if logging is explicitly requested

# log = logging.getLogger(__name__) # Placeholder for logger

class ZeroMQEventBus:
    """
    An event bus implementation using ZeroMQ for asynchronous event publishing and subscribing.

    This class provides a Pythonic interface to a ZeroMQ-based event system,
    allowing components to publish events (as Python dictionaries serialized to JSON)
    to specific topics and subscribe to topics (potentially with wildcards)
    to receive and handle these events asynchronously.

    It supports:
    - Hierarchical topics.
    - Client-side wildcard topic pattern matching (`fnmatch`).
    - Client-side custom filter functions for fine-grained event selection.
    - Handler priorities for local subscribers.
    - A "consumed" sentinel to stop event propagation among local handlers.
    - Communication with a central ZeroMQ broker (XPUB/XSUB pattern assumed).
    """

    CONSUMED = object()  # Sentinel to indicate an event has been consumed

    def __init__(
        self,
        broker_publisher_frontend_address: str,
        broker_subscriber_frontend_address: str,
        identity: Optional[str] = None,
    ):
        """
        Initializes the ZeroMQEventBus.

        Args:
            broker_publisher_frontend_address: The ZMQ address of the broker's socket
                where publishers should send messages (e.g., "tcp://localhost:5559").
            broker_subscriber_frontend_address: The ZMQ address of the broker's socket
                where subscribers should connect to receive messages (e.g., "tcp://localhost:5560").
            identity: An optional unique string to identify this event bus instance,
                primarily for logging/debugging. Auto-generated if None.
        """
        self.broker_publisher_frontend_address = broker_publisher_frontend_address
        self.broker_subscriber_frontend_address = broker_subscriber_frontend_address
        self.identity = identity or f"zmq_event_bus_client_{uuid.uuid4().hex[:8]}"

        self.context = zmq.asyncio.Context()
        self.pub_socket: Optional[zmq.asyncio.Socket] = None
        self.sub_socket: Optional[zmq.asyncio.Socket] = None

        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._zmq_topic_prefix_ref_counts: Dict[bytes, int] = {} # For ZMQ-level subscription ref counting
        self._receive_loop_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """
        Starts the event bus.

        Creates and configures ZMQ sockets, connects to the broker,
        and starts the internal message receiving loop.
        """
        if self._running:
            # print(f"[{self.identity}] Event bus already started.") # Using print for PoC
            return

        # print(f"[{self.identity}] Starting event bus...")
        self.pub_socket = self.context.socket(zmq.PUB)
        # print(f"[{self.identity}] Connecting PUB socket to {self.broker_publisher_frontend_address}")
        self.pub_socket.connect(self.broker_publisher_frontend_address)

        self.sub_socket = self.context.socket(zmq.SUB)
        # print(f"[{self.identity}] Connecting SUB socket to {self.broker_subscriber_frontend_address}")
        self.sub_socket.connect(self.broker_subscriber_frontend_address)

        # Re-apply ZMQ-level subscriptions if any were made before start
        for prefix_bytes in list(self._zmq_topic_prefix_ref_counts.keys()): # Iterate over a copy
            if self._zmq_topic_prefix_ref_counts.get(prefix_bytes, 0) > 0:
                # print(f"[{self.identity}] Re-applying ZMQ subscription to: {prefix_bytes.decode('utf-8', 'ignore')}")
                if self.sub_socket: # Ensure sub_socket is available
                     self.sub_socket.subscribe(prefix_bytes)

        self._running = True
        self._receive_loop_task = asyncio.create_task(self._message_receive_loop())
        # print(f"[{self.identity}] Event bus started. Listening for messages.")

    async def stop(self) -> None:
        """
        Stops the event bus.

        Gracefully stops the message receiving loop, closes ZMQ sockets,
        and terminates the ZMQ context.
        """
        if not self._running and not self._receive_loop_task:
            # print(f"[{self.identity}] Event bus already stopped or not started.")
            return

        # print(f"[{self.identity}] Stopping event bus...")
        self._running = False

        if self._receive_loop_task:
            self._receive_loop_task.cancel()
            try:
                await self._receive_loop_task
            except asyncio.CancelledError:
                # print(f"[{self.identity}] Message receiving loop cancelled.")
                pass
            except Exception as e:
                # print(f"[{self.identity}] Error during message loop shutdown: {e}")
                pass
            self._receive_loop_task = None

        if self.pub_socket:
            # print(f"[{self.identity}] Closing PUB socket.")
            self.pub_socket.close(linger=0)
            self.pub_socket = None
        if self.sub_socket:
            # print(f"[{self.identity}] Closing SUB socket.")
            self.sub_socket.close(linger=0)
            self.sub_socket = None

        # print(f"[{self.identity}] Terminating ZMQ context.")
        if not self.context.closed: # Check if context is not already closed
            await self.context.destroy(linger=0) # Use destroy for async context
        # print(f"[{self.identity}] Event bus stopped.")


    async def publish(self, topic: str, event_data: dict) -> None:
        """
        Publishes an event to a given topic.

        Args:
            topic: The full hierarchical topic string for the event (e.g., "app.core.user_input").
            event_data: The Python dictionary representing the event.
                        This will be serialized to JSON.

        Raises:
            RuntimeError: If the event bus is not started or the PUB socket is not available.
            TypeError: If event_data cannot be serialized to JSON.
            zmq.ZMQError: For ZeroMQ related errors during send.
        """
        if not self._running or not self.pub_socket:
            raise RuntimeError(f"[{self.identity}] Event bus not started or PUB socket unavailable. Cannot publish.")

        try:
            json_payload_bytes = json.dumps(event_data).encode('utf-8')
        except TypeError as e:
            # print(f"[{self.identity}] Failed to serialize event_data to JSON for topic '{topic}': {e}")
            raise
        
        topic_bytes = topic.encode('utf-8')
        
        try:
            await self.pub_socket.send_multipart([topic_bytes, json_payload_bytes])
            # print(f"[{self.identity}] Published to topic '{topic}': {event_data}")
        except zmq.ZMQError as e:
            # print(f"[{self.identity}] ZMQError publishing to topic '{topic}': {e}")
            raise


    def _get_broad_zmq_prefix(self, topic_pattern: str) -> str:
        """
        Determines the broadest ZMQ topic prefix for a given fnmatch-style topic pattern.
        For example, 'app.core.*.event' -> 'app.core.'
        'app.*.event' -> 'app.'
        'app.specific.event' -> 'app.specific.event'
        '*' -> ''
        """
        parts = []
        for char in topic_pattern:
            if char in ['*', '?', '[']:
                break
            parts.append(char)
        
        prefix = "".join(parts)
        return prefix

    async def subscribe(
        self,
        topic_pattern: str,
        handler_coroutine: Callable[[str, dict], Coroutine[Any, Any, Any]],
        priority: int = 0,
        custom_filter_function: Optional[Callable[[str, dict], bool]] = None,
    ) -> str:
        """
        Subscribes a handler coroutine to a topic pattern.

        Args:
            topic_pattern: The pattern to match against incoming event topics
                           (e.g., "app.core.*", "app.module.specific_event").
                           Supports `fnmatch`-style wildcards.
            handler_coroutine: The asynchronous function to be invoked when an event matches.
                               It will receive `(actual_topic: str, event_data_dict: dict)`.
            priority: An integer indicating the local execution priority for this handler
                      if multiple local handlers match the same event (lower numbers execute first).
            custom_filter_function: An optional callable that receives
                                    `(actual_topic: str, event_data_dict: dict)` and
                                    returns `True` if the handler should be invoked, `False` otherwise.
                                    This is applied *after* the `topic_pattern` matches.

        Returns:
            A unique `subscription_id` (str) for this subscription.

        Raises:
            RuntimeError: If the event bus is not started or SUB socket is not available
                          (unless only storing subscription and applying on start).
        """
        if not self.sub_socket and self._running: # Check if running but socket somehow not there
             raise RuntimeError(f"[{self.identity}] SUB socket not available. Cannot subscribe at ZMQ level.")

        subscription_id = str(uuid.uuid4())
        
        broad_zmq_prefix_str = self._get_broad_zmq_prefix(topic_pattern)
        broad_zmq_prefix_bytes = broad_zmq_prefix_str.encode('utf-8')

        self._subscriptions[subscription_id] = {
            "topic_pattern": topic_pattern,
            "handler": handler_coroutine,
            "priority": priority,
            "custom_filter": custom_filter_function,
            "zmq_prefix_bytes": broad_zmq_prefix_bytes, # Store for unsubscribe
        }

        current_ref_count = self._zmq_topic_prefix_ref_counts.get(broad_zmq_prefix_bytes, 0)
        if current_ref_count == 0 and self.sub_socket: # Only subscribe if socket exists
            try:
                # print(f"[{self.identity}] Subscribing at ZMQ level to: {broad_zmq_prefix_str}")
                self.sub_socket.subscribe(broad_zmq_prefix_bytes)
            except zmq.ZMQError as e:
                # print(f"[{self.identity}] ZMQError subscribing to prefix '{broad_zmq_prefix_str}': {e}")
                del self._subscriptions[subscription_id] # Rollback
                raise
        
        self._zmq_topic_prefix_ref_counts[broad_zmq_prefix_bytes] = current_ref_count + 1
        
        # print(f"[{self.identity}] Subscribed handler for pattern '{topic_pattern}' (ID: {subscription_id}), ZMQ prefix '{broad_zmq_prefix_str}'")
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribes a handler.

        Args:
            subscription_id: The unique ID returned by the `subscribe` method.

        Returns:
            `True` if a subscription was found and removed, `False` otherwise.
        
        Raises:
            RuntimeError: If SUB socket is not available when trying to unsubscribe at ZMQ level.
        """
        subscription_details = self._subscriptions.pop(subscription_id, None)

        if not subscription_details:
            # print(f"[{self.identity}] Unsubscribe failed: No subscription found with ID {subscription_id}")
            return False

        broad_zmq_prefix_bytes = subscription_details["zmq_prefix_bytes"]
        current_ref_count = self._zmq_topic_prefix_ref_counts.get(broad_zmq_prefix_bytes, 0)

        if current_ref_count > 0:
            new_ref_count = current_ref_count - 1
            self._zmq_topic_prefix_ref_counts[broad_zmq_prefix_bytes] = new_ref_count
            
            if new_ref_count == 0:
                if self.sub_socket: # Only unsubscribe if socket exists
                    try:
                        # print(f"[{self.identity}] Unsubscribing at ZMQ level from: {broad_zmq_prefix_bytes.decode('utf-8', 'ignore')}")
                        self.sub_socket.unsubscribe(broad_zmq_prefix_bytes)
                    except zmq.ZMQError as e:
                        # print(f"[{self.identity}] ZMQError unsubscribing from prefix '{broad_zmq_prefix_bytes.decode('utf-8','ignore')}': {e}")
                        # The ref count is already decremented. What to do here?
                        # For now, just print. The ZMQ sub might remain.
                        pass
                if broad_zmq_prefix_bytes in self._zmq_topic_prefix_ref_counts: # Check before del
                    del self._zmq_topic_prefix_ref_counts[broad_zmq_prefix_bytes] # Clean up if zero
        
        # print(f"[{self.identity}] Unsubscribed handler with ID {subscription_id} (pattern: '{subscription_details['topic_pattern']}')")
        return True

    async def _message_receive_loop(self) -> None:
        """
        Internal asyncio task to continuously receive messages from the SUB socket
        and dispatch them to registered handlers.
        """
        # print(f"[{self.identity}] Message receiving loop started.")
        while self._running and self.sub_socket:
            try:
                # print(f"[{self.identity}] Awaiting message from SUB socket...")
                topic_bytes, json_payload_bytes = await self.sub_socket.recv_multipart()
                # print(f"[{self.identity}] Received raw message: topic_bytes={topic_bytes}, payload_len={len(json_payload_bytes)}")

                try:
                    actual_topic_str = topic_bytes.decode('utf-8')
                    event_data_dict = json.loads(json_payload_bytes.decode('utf-8'))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    # print(f"[{self.identity}] Failed to decode/deserialize message: {e}. Topic bytes: {topic_bytes}, Payload bytes: {json_payload_bytes[:100]}...")
                    continue # Skip malformed message

                # print(f"[{self.identity}] Received event on topic '{actual_topic_str}': {event_data_dict}")

                matched_handlers: List[Tuple[int, Callable, str]] = [] # (priority, handler_coro, sub_id)

                for sub_id, details in list(self._subscriptions.items()): # list() for safe iteration if modified
                    topic_pattern: str = details["topic_pattern"]
                    
                    if fnmatch.fnmatch(actual_topic_str, topic_pattern):
                        # print(f"[{self.identity}] Topic '{actual_topic_str}' matched pattern '{topic_pattern}' for sub {sub_id}")
                        custom_filter: Optional[Callable[[str, dict], bool]] = details.get("custom_filter")
                        passes_custom_filter = True
                        if custom_filter:
                            try:
                                passes_custom_filter = custom_filter(actual_topic_str, event_data_dict)
                                # print(f"[{self.identity}] Custom filter for sub {sub_id} returned {passes_custom_filter}")
                            except Exception as e_filter:
                                # print(f"[{self.identity}] Error in custom_filter for subscription {sub_id} (pattern '{topic_pattern}'): {e_filter}")
                                passes_custom_filter = False # Treat filter error as not passing

                        if passes_custom_filter:
                            matched_handlers.append((details["priority"], details["handler"], sub_id))
                
                if not matched_handlers:
                    # print(f"[{self.identity}] No local handlers matched for topic '{actual_topic_str}'")
                    continue

                # Sort handlers by priority (lower number = higher priority)
                matched_handlers.sort(key=lambda x: x[0])
                # print(f"[{self.identity}] Sorted matched handlers for '{actual_topic_str}': {[(p, s_id) for p, _, s_id in matched_handlers]}")

                for priority, handler_coro, sub_id in matched_handlers:
                    try:
                        # print(f"[{self.identity}] Invoking handler (priority {priority}, sub {sub_id}) for topic '{actual_topic_str}'")
                        result = await handler_coro(actual_topic_str, event_data_dict)
                        if result is self.CONSUMED:
                            # print(f"[{self.identity}] Event on topic '{actual_topic_str}' consumed by handler for sub {sub_id}. Stopping further local processing.")
                            break 
                    except Exception as e_handler:
                        # print(f"[{self.identity}] Error in handler for subscription {sub_id} (pattern '{self._subscriptions.get(sub_id, {}).get('topic_pattern')}'): {e_handler}")
                        pass # Continue to other handlers despite one failing

            except zmq.ZMQError as e:
                if e.errno == zmq.ETERM:
                    # print(f"[{self.identity}] ZMQ context terminated, exiting receive loop.")
                    break
                elif e.errno == zmq.EAGAIN: # Should not happen with async recv unless timeout specified
                    # print(f"[{self.identity}] ZMQ EAGAIN encountered in async recv, should not happen.")
                    await asyncio.sleep(0.001) # Brief pause
                    continue
                # print(f"[{self.identity}] ZMQError in receive loop: {e} (errno: {e.errno})")
                if not self._running: # If stopping, this might be expected
                    break
                await asyncio.sleep(1) # Wait a bit before retrying on other errors
            except asyncio.CancelledError:
                # print(f"[{self.identity}] Receive loop cancelled.")
                break
            except Exception as e:
                # print(f"[{self.identity}] Unexpected error in receive loop: {e}") # exc_info=True for full traceback
                if not self._running:
                    break
                await asyncio.sleep(1) # Wait before retrying
        
        # print(f"[{self.identity}] Message receiving loop finished.")

# Example usage (for testing, not part of the class itself)
async def _example_main():
    # This requires a running ZMQ broker (XPUB/XSUB)
    # e.g., using the zmq_broker_poc.py script from the documentation
    BROKER_PUB_FRONTEND = "tcp://localhost:5559"
    BROKER_SUB_FRONTEND = "tcp://localhost:5560"

    bus1 = ZeroMQEventBus(BROKER_PUB_FRONTEND, BROKER_SUB_FRONTEND, identity="Bus1")
    bus2 = ZeroMQEventBus(BROKER_PUB_FRONTEND, BROKER_SUB_FRONTEND, identity="Bus2")

    await bus1.start()
    await bus2.start()

    async def handler1(topic: str, data: dict):
        print(f"[Handler1 - Bus1] Received on '{topic}': {data}")
        if data.get("value") == "consume_me":
            print("[Handler1 - Bus1] Consuming event.")
            return ZeroMQEventBus.CONSUMED

    async def handler2_low_priority(topic: str, data: dict):
        print(f"[Handler2_LowPrio - Bus1] Received on '{topic}': {data}")

    def custom_filter_even_ids(topic: str, data: dict) -> bool:
        return data.get("id", 0) % 2 == 0

    await bus1.subscribe("test.event.*", handler1, priority=0)
    await bus1.subscribe("test.event.specific", handler2_low_priority, priority=10)
    
    # Bus2 subscription
    async def handler_bus2(topic: str, data: dict):
        print(f"[Handler_Bus2] Received on '{topic}': {data}")

    await bus2.subscribe("test.event.alpha", handler_bus2)
    await bus2.subscribe("test.data", handler_bus2, custom_filter_function=custom_filter_even_ids)


    print("Publishing events...")
    await bus1.publish("test.event.alpha", {"message": "Hello Alpha from Bus1", "id": 1})
    await asyncio.sleep(0.1)
    await bus2.publish("test.event.beta", {"message": "Hello Beta from Bus2", "id": 2}) # Bus1 handlers should get this
    await asyncio.sleep(0.1)
    await bus1.publish("test.event.specific", {"message": "Specific event, should be consumed", "value": "consume_me", "id": 3})
    await asyncio.sleep(0.1)
    await bus1.publish("test.event.specific", {"message": "Specific event, after consume", "id": 4}) # Low prio should get this
    await asyncio.sleep(0.1)
    
    await bus1.publish("test.data", {"source": "bus1", "id": 10}) # Bus2 handler_bus2 should get (id 10 is even)
    await bus1.publish("test.data", {"source": "bus1", "id": 11}) # Bus2 handler_bus2 should NOT get (id 11 is odd)


    await asyncio.sleep(1) # Let messages process

    print("Stopping buses...")
    await bus1.stop()
    await bus2.stop()
    print("Buses stopped.")

if __name__ == "__main__":
    # To run this example, you need a ZMQ broker running.
    # You can use the `zmq_broker_poc.py` from the design document.
    # Example: python pocket_commander/zmq_broker_poc.py
    # Then run this file: python pocket_commander/zeromq_eventbus_poc.py
    
    # For PoC, using print instead of log. Setup logging if this moves to production.
    # import logging
    # logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    # log = logging.getLogger(__name__) # Then assign to self.log in __init__ or use module-level log

    print("Running ZeroMQEventBus example (requires a running broker)...")
    # BROKER_PUB_FRONTEND_ADDR = "tcp://localhost:5559" # Defined in _example_main
    # BROKER_SUB_FRONTEND_ADDR = "tcp://localhost:5560" # Defined in _example_main
    try:
        asyncio.run(_example_main())
    except KeyboardInterrupt:
        print("Example interrupted.")
    except ConnectionRefusedError:
        print("Connection refused. Is the ZeroMQ broker (e.g., zmq_broker_poc.py) running?")
        # The following line to print addresses won't work as _example_main's closure is not directly accessible here.
        # print(f"Broker expected at PUB: ..., SUB: ...") 
    print("Example finished.")