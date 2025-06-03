# ZeroMQ Event Bus Architecture for Pocket Commander

## 1. Introduction and Goals

This document outlines the research, design, and architecture for replacing the current Python-based `AsyncEventBus` in Pocket Commander with a ZeroMQ-based event system.

**Goals:**
-   Implement a robust, scalable event bus using ZeroMQ.
-   Support hierarchical topics.
-   Enable custom/advanced event filtering.
-   Explore how concepts like "event consumed" and "handler priority" can be adapted.
-   Provide a clear Python API for publishing and subscribing to events.
-   Lay the groundwork for potential future inter-process or distributed communication.

## 2. ZeroMQ Pattern Exploration

This section will detail the investigation of various ZeroMQ patterns and their suitability for Pocket Commander.

### 2.1. ROUTER/DEALER
-   **Description:** Asynchronous request/reply. ROUTER sockets can receive from many DEALERs and know their identities. DEALERs can send to ROUTERs and distribute messages round-robin to connected peers.
-   **Potential for Broker:** Can be used to build intelligent brokers that manage complex routing, load balancing, or stateful interactions.
-   **Flexibility for Advanced Features:**
    -   **Targeted Messages/Replies:** ROUTER knows the origin of messages, allowing for direct replies or targeted dispatches.
    -   **Custom Routing Logic:** Broker can implement arbitrary logic based on message content or topic.
    -   **Implementing "Consume":** A ROUTER-based broker could potentially manage "consume" semantics by tracking message delivery and acknowledgments.
-   **Pros for Pocket Commander:**
    -   High flexibility.
    -   Good for building custom broker logic.
    -   Can handle asynchronous communication well.
-   **Cons for Pocket Commander:**
    -   More complex to set up than PUB/SUB.
    -   Requires careful management of message envelopes and identities.
-   **Considerations:**
    -   How to structure the broker (if any) using ROUTER/DEALER.
    -   How subscribers register their interests.

### 2.2. PUB/SUB (with XPUB/XSUB)
-   **Description:** Classic publish-subscribe.
    -   `PUB` sockets distribute messages to all connected `SUB` sockets.
    -   `SUB` sockets subscribe to topics (typically prefixes).
    -   `XPUB` (Extended PUB) sockets act like `PUB` but also receive and process subscription messages (special ZMQ messages: `0x01`+topic for subscribe, `0x00`+topic for unsubscribe) from connected `XSUB` or `SUB` sockets. The `XPUB` socket can also allow the application to read these subscription messages.
    -   `XSUB` (Extended SUB) sockets act like `SUB` but also send their subscription messages upstream, typically to an `XPUB`.
-   **Subscription Management with XPUB/XSUB:**
    -   The core topic-based filtering based on subscriptions is handled *by the ZeroMQ XPUB socket itself*.
    -   When a `SUB`/`XSUB` client calls `socket.subscribe("topic.prefix")`, a special message is sent to the `XPUB` it's connected to. The `XPUB` uses this to filter outgoing messages.
    -   An application hosting an `XPUB` socket can *optionally read* these subscription messages if it needs to be aware of active subscriptions (e.g., for logging, metrics, or more advanced application-level routing decisions beyond ZeroMQ's prefix filtering).
-   **Potential for Broker (Forwarder Device):**
    -   A common pattern is to use an `XSUB` socket on the broker's frontend (to receive from publishers) and an `XPUB` socket on the backend (for subscribers to connect to).
    -   The broker logic reads from the frontend `XSUB` and forwards to the backend `XPUB`. The `XPUB` then handles distributing to subscribers based on their ZeroMQ-managed subscriptions.
-   **Pros for Pocket Commander:**
    -   Relatively simple and well-understood pattern for event broadcasting.
    -   Efficient for distributing events to multiple interested parties.
    -   Subscription management for basic topic filtering is largely handled by ZeroMQ itself, reducing custom broker logic for this aspect.
    -   Broker can still be aware of subscriptions by reading them from the `XPUB` socket if needed.
-   **Cons for Pocket Commander:**
    -   ZeroMQ's built-in topic filtering is prefix-based. More complex filtering (e.g., wildcards in the middle of topics, regex, content-based) would require application-level logic (either in the subscriber or in a more intelligent broker that processes subscription messages and message content).
    -   No built-in ZeroMQ mechanism for "consume once" semantics across multiple, distinct subscribers interested in the same message. This would require application-level coordination.
    -   Handler priority is not inherently managed by the bus; it would be a subscriber-side concern or require significant custom broker logic.

### 2.3. PUSH/PULL
-   **Description:** Distributes messages to a pool of workers (PULL sockets) in a round-robin or fair-queued manner.
-   **Pros for Pocket Commander:**
    -   Useful for distributing tasks.
-   **Cons for Pocket Commander:**
    -   Not ideal as a general-purpose event bus where multiple components might be interested in the same event. More for work distribution.

### 2.4. Selected Pattern(s) and Rationale
-   **Selected for V1: PUB/SUB with XPUB/XSUB for the broker/forwarder.**
-   **Rationale:**
    -   Leverages ZeroMQ's built-in subscription handling (prefix-based topic filtering), simplifying the initial broker implementation.
    -   Provides a solid foundation for event broadcasting.
    -   Allows for a phased approach; a more intelligent broker (e.g., using ROUTER/DEALER) can be developed in a later version if advanced server-side filtering, "consume" logic, or priority management at the broker becomes critical.
    -   Sufficient for achieving core goals of hierarchical topics (as part of the message or ZMQ topic string) and allowing client-side advanced filtering.

## 3. Broker Strategy
-   **Chosen Strategy for V1: A simple message forwarder broker.**
-   **Implementation Details:**
    -   The broker will be a dedicated process.
    -   **Frontend (for Publishers):** An `XSUB` socket will listen for incoming messages from publishers. Publishers will send their messages with the full hierarchical topic string (e.g., `app.core.event_type.detail`) as the ZeroMQ topic.
        -   Example: Publisher `socket.send_string(f"{hierarchical_topic}", zmq.SNDMORE); socket.send_pyobj(event_data_pydantic_model)`
    -   **Backend (for Subscribers):** An `XPUB` socket will allow subscribers to connect and make subscriptions.
        -   Subscribers will use standard ZeroMQ `socket.subscribe("app.core.event_type")` calls. The `XPUB` socket handles the prefix-based filtering.
    -   **Broker Logic:** The core logic will be to read messages from the frontend `XSUB` socket and immediately forward them (topic and payload) to the backend `XPUB` socket.
        -   `message = frontend_socket.recv_multipart()`
        -   `backend_socket.send_multipart(message)`
    -   The broker *may* optionally read subscription messages from the `XPUB` socket for logging or metrics but will not use them for custom filtering logic in V1.
    -   This design keeps the broker simple and relies on ZeroMQ's capabilities for basic PUB/SUB mechanics.
    -   Advanced features like "consume" logic or fine-grained "handler priority" will be the responsibility of the subscribing clients in V1.

## 4. Hierarchical Topic Design (V1 - XPUB/XSUB Broker)
-   **Topic String Format:** Dot-separated strings, e.g., `app.core.event_type.specific_detail`.
-   **Mapping to ZeroMQ:**
    -   Publishers will set the full hierarchical topic string as the **ZeroMQ topic** for each message. ZeroMQ topics are byte strings.
    -   The `ZeroMQEventBus` wrapper's `publish` method will handle encoding this topic string appropriately before sending.
    -   Example (conceptual, within the wrapper): `zmq_socket.send_string(full_hierarchical_topic, flags=zmq.SNDMORE).send_pyobj(event_data_pydantic_model)`
-   **Subscription Mechanism (ZeroMQ Level):**
    -   Subscribers will use the standard ZeroMQ `socket.subscribe("some.prefix.")` method call.
    -   The `XPUB` socket in the broker will perform prefix matching on the full topic strings sent by publishers.
    -   For example, a subscriber calling `socket.subscribe("app.core.")` will receive messages with topics like `app.core.event_A`, `app.core.module_X.event_B`, etc.
    -   Subscribing to an empty string (`socket.subscribe("")`) will match all messages (if not further filtered by client-side logic).
-   **Subscription Mechanism (Python API Level):**
    -   The `ZeroMQEventBus` wrapper's `subscribe` method will take a `topic_pattern` argument. This pattern might be more expressive (e.g., allowing wildcards) than ZeroMQ's native prefix matching.
    -   If the `topic_pattern` is a simple prefix, it can be directly passed to `zmq_socket.subscribe()`.
    -   If the `topic_pattern` is more complex (e.g., `app.*.event_type`), the wrapper might subscribe to a broader ZeroMQ topic (e.g., `app.`) and then apply the more specific pattern matching client-side (see Section 5).

## 5. Custom/Advanced Filtering Design (V1 - Client-Side Focus)
-   **Client-Side vs. Broker-Side Filtering (V1):**
    -   For V1, with the XPUB/XSUB broker, advanced filtering (beyond ZeroMQ's native prefix matching on topics) will be implemented **client-side** within the `ZeroMQEventBus` wrapper and the subscriber's application logic.
    -   The ZeroMQ broker will only perform prefix-based topic filtering as provided by the `XPUB` socket.
-   **Filter Syntax/Mechanism (Client-Side):**
    -   The `ZeroMQEventBus.subscribe()` method (see Section 7 API Design) will accept a `topic_pattern` string and potentially an additional `custom_filter_function: Optional[Callable[[str, BaseModel], bool]]`.
    -   **Topic Pattern Matching (Client-Side):**
        -   The `topic_pattern` can support wildcards (e.g., `app.core.*.event_x`, `app.*.some_event`). `fnmatch` can be used for this.
        -   The subscriber's `ZeroMQEventBus` instance will subscribe to the broadest possible ZeroMQ topic prefix that encompasses the `topic_pattern` (e.g., for `app.core.*.event_x`, it might subscribe to `app.core.` at the ZeroMQ level).
        -   When a message arrives, the client-side wrapper will first match the full incoming topic against the registered `topic_pattern` using `fnmatch`.
    -   **Custom Filter Function (Client-Side):**
        -   If a `custom_filter_function` is provided during subscription, it will be called after the `topic_pattern` matches.
        -   This function will receive the full `topic` string and the deserialized `event_data` (a Python `dict`) and must return `True` for the handler to be invoked, `False` otherwise.
        -   This allows for arbitrary filtering logic, including regex on topic parts or conditions based on message content within the dictionary.
-   **Implementation Details (Client-Side Wrapper):**
    -   The `ZeroMQEventBus` wrapper will maintain a list of registered handlers, each associated with its `topic_pattern` and optional `custom_filter_function`.
    -   Upon receiving a message from its ZeroMQ SUB socket:
        1.  Deserialize the message payload (JSON string) into an `event_data_dict` (Python `dict`).
        2.  Iterate through all registered handlers.
        3.  For each handler:
            a.  Check if the incoming message's `topic` matches the handler's `topic_pattern` (e.g., using `fnmatch`).
            b.  If it matches and a `custom_filter_function` exists for that handler, call `custom_filter_function(topic, event_data_dict)`.
            c.  If both pattern and custom filter (if present) pass, asynchronously invoke the handler coroutine (passing `topic` and `event_data_dict`).
-   **Broker-Side Filtering (V1):** Limited to ZeroMQ's native prefix matching on the topics provided by subscribers to the `XPUB` socket.

## 6. Adaptation of "Event Consumed" and "Handler Priority" (V1 - Client-Side Focus)

With the V1 XPUB/XSUB forwarder broker, both "event consumed" and "handler priority" will primarily be client-side considerations. The broker itself will not enforce these semantics across different subscriber processes.

-   **"Event Consumed" Logic (V1):**
    -   **Across Different Subscriber Processes:** The XPUB/XSUB pattern broadcasts messages to all matching ZeroMQ subscribers. One subscriber "consuming" an event does not prevent other independent subscriber processes from also receiving and processing it. True "consume once across distributed subscribers" is out of scope for the V1 simple forwarder broker.
    -   **Within a Single Subscriber Process:** The `ZeroMQEventBus` Python wrapper *can* implement a local "consume" mechanism.
        -   If multiple handlers are registered within the same client process that match a given incoming event, the wrapper can execute them.
        -   If a handler coroutine returns a special sentinel value (e.g., `ZeroMQEventBus.CONSUMED`), the wrapper can stop processing that specific event instance for any subsequent, lower-priority (if applicable) local handlers within that same client. This mimics the behavior of the existing `AsyncEventBus`.
        -   This requires the `ZeroMQEventBus.CONSUMED` sentinel to be defined and the handler invocation loop in the wrapper to check for it.

-   **"Handler Priority" Logic (V1):**
    -   **Across Different Subscriber Processes:** The V1 XPUB/XSUB broker does not manage or enforce priority between different subscriber processes.
    -   **Within a Single Subscriber Process:** The `ZeroMQEventBus` Python wrapper *can* implement local handler priority.
        -   When subscribing a handler via `ZeroMQEventBus.subscribe()`, an optional `priority: int` parameter can be accepted (e.g., lower numbers execute first).
        -   When an event arrives and matches multiple local handlers (after topic pattern and custom filtering), the wrapper will sort these matched local handlers by their specified priority before invoking them sequentially.
        -   This allows developers to control the order of execution for handlers *within the same application component* that are interested in the same event.

-   **Future Considerations:**
    -   If true distributed "consume" or cross-process priority becomes a requirement, a more advanced broker (likely using ROUTER/DEALER patterns) and potentially acknowledgment schemes would need to be designed in a future version.

## 7. API Design for ZeroMQ Event Bus Wrapper (V1 - JSON/Dict Focus)

This Python class will be the primary interface for application components to interact with the ZeroMQ event system.

-   **Core Python Class:** `ZeroMQEventBus`
    -   `CONSUMED = object()`: A class-level sentinel that handler coroutines can return to indicate the event should not be processed by further local handlers (if priorities are used).
    -   `__init__(self, broker_publisher_frontend_address: str, broker_subscriber_frontend_address: str, identity: Optional[str] = None)`:
        -   `broker_publisher_frontend_address`: The ZMQ address of the broker's socket where publishers should send messages (e.g., the broker's XSUB socket address like `tcp://localhost:5559`).
        -   `broker_subscriber_frontend_address`: The ZMQ address of the broker's socket where subscribers should connect to receive messages (e.g., the broker's XPUB socket address like `tcp://localhost:5560`).
        -   `identity: Optional[str]`: An optional unique string to identify this event bus instance, primarily for logging/debugging. Can be auto-generated if `None`.
        -   Initializes ZMQ context, but sockets are created and connected in `start()`.
    -   `async start(self)`:
        -   Creates and configures the internal ZMQ `PUB` socket (for publishing from this instance) and `SUB` socket (for receiving messages for this instance's subscriptions).
        -   Connects the `PUB` socket to `broker_publisher_frontend_address`.
        -   Connects the `SUB` socket to `broker_subscriber_frontend_address`.
        -   Starts an `asyncio` task to continuously receive messages from the `SUB` socket and dispatch them to registered handlers based on topic patterns, custom filters, and priorities.
    -   `async stop(self)`:
        -   Gracefully stops the message receiving task.
        -   Closes the ZMQ sockets and terminates the ZMQ context.
    -   `async publish(self, topic: str, event_data: dict)`:
        -   `topic: str`: The full hierarchical topic string for the event (e.g., `app.core.user_input`).
        -   `event_data: dict`: The Python dictionary representing the event.
        -   Serializes `event_data` to a JSON string (UTF-8 encoded bytes) as per Section 8.
        -   Sends the `topic` (UTF-8 encoded string) and the JSON `event_data` bytes as a multi-part ZMQ message via the internal `PUB` socket.
    -   `async subscribe(self, topic_pattern: str, handler_coroutine: Callable[[str, dict], Coroutine[Any, Any, Any]], priority: int = 0, custom_filter_function: Optional[Callable[[str, dict], bool]] = None) -> uuid.UUID`:
        -   `topic_pattern: str`: The pattern to match against incoming event topics (e.g., `app.core.*`, `app.module.specific_event`). Supports `fnmatch`-style wildcards.
        -   `handler_coroutine: Callable[[str, dict], Coroutine[Any, Any, Any]]`: The asynchronous function to be invoked when an event matches. It will receive `(actual_topic: str, event_data_dict: dict)`.
        -   `priority: int = 0`: An integer indicating the local execution priority for this handler if multiple local handlers match the same event (lower numbers execute first).
        -   `custom_filter_function: Optional[Callable[[str, dict], bool]] = None`: An optional callable that receives `(actual_topic: str, event_data_dict: dict)` and returns `True` if the handler should be invoked, `False` otherwise. This is applied *after* the `topic_pattern` matches.
        -   **Internal Logic:**
            1.  Generates a unique `subscription_id` (e.g., `uuid.UUID`).
            2.  Determines the broadest ZMQ topic prefix required for this `topic_pattern` (e.g., for `app.core.*.event_x`, the ZMQ subscription might be to `app.core.`).
            3.  Calls `self.sub_socket.subscribe(broad_zmq_prefix_bytes)` to subscribe at the ZeroMQ level. This might be a no-op if already subscribed to this prefix or a broader one.
            4.  Stores the `subscription_id`, `topic_pattern`, `handler_coroutine`, `priority`, and `custom_filter_function` in an internal collection of active subscriptions.
            5.  Returns the `subscription_id`.
    -   `async unsubscribe(self, subscription_id: uuid.UUID) -> bool`:
        -   `subscription_id: uuid.UUID`: The unique ID returned by the `subscribe` method.
        -   Removes the handler details associated with `subscription_id` from the internal collection.
        -   **Optional Optimization:** Check if the ZMQ topic prefix associated with the removed subscription is still needed by other active subscriptions. If not, call `self.sub_socket.unsubscribe(broad_zmq_prefix_bytes)`. This requires careful reference counting for ZMQ-level subscriptions.
        -   Returns `True` if a subscription was found and removed, `False` otherwise.

-   **Event Representation (V1):** Standard Python dictionaries (`dict`) will be used for `event_data`. (See Section 8).
-   **Asynchronous Nature:** All potentially blocking I/O operations (publishing, receiving, dispatching) will be asynchronous and integrate with `asyncio`.

## 8. Serialization / Deserialization (V1 - JSON and Dictionaries)
-   **Chosen Format for V1: JSON.**
-   **Event Data Structure for V1: Standard Python dictionaries (`dict`).** Pydantic models will not be used for event data in V1 to simplify the initial implementation.
-   **Rationale for V1:**
    -   **Simplicity:** Python's built-in `json` module is straightforward to use.
    -   **Universality:** JSON is human-readable and widely supported if other non-Python components were ever to interact (though less of a concern for V1).
    -   **Reduced Dependencies:** Avoids adding Pydantic as a core dependency for the event data structure itself in this iteration.
    -   Type safety and performance benefits of Pydantic/MessagePack are deferred for potential future enhancements.
-   **Implementation:**
    -   **Serialization:** The `ZeroMQEventBus.publish()` method will use `json.dumps(event_data_dict)` to convert the Python dictionary to a JSON string. This string will then be UTF-8 encoded to bytes for sending over ZeroMQ.
    -   **Deserialization:** The receiving loop in `ZeroMQEventBus` will receive bytes, UTF-8 decode them to a JSON string, and then use `json.loads(json_string)` to convert it back to a Python dictionary.
    -   **Event Type Distinction:** Since Pydantic models are not used, if different "types" of events need to be distinguished by subscribers, a convention must be adopted. For example, the `event_data_dict` could contain a common key like `'event_type': 'USER_INPUT'` or `'event_type': 'SYSTEM_NOTIFICATION'`. Subscribers would then inspect this key within the dictionary to understand the event's nature and structure.
    -   The ZeroMQ message on the wire will typically be two parts: `[topic_bytes, json_string_bytes]`.

## 9. Proof of Concept (PoC) Outline (V1 - XPUB/XSUB, JSON/Dict)

-   **Goals of PoC:**
    1.  Validate the XPUB/XSUB forwarder broker pattern for message relay.
    2.  Test hierarchical topic publishing (full topic string as ZMQ topic) and ZeroMQ-level prefix-based subscription.
    3.  Implement and test client-side `fnmatch` topic pattern matching within the `ZeroMQEventBus` wrapper for dispatching to specific handlers.
    4.  Implement and test client-side `custom_filter_function` (operating on topic string and event `dict`) in the wrapper.
    5.  Demonstrate the core `ZeroMQEventBus` Python wrapper API as defined in Section 7, including:
        -   `__init__`, `start`, `stop`.
        -   `publish(topic: str, event_data: dict)`.
        -   `subscribe(topic_pattern: str, handler_coroutine: Callable[[str, dict], ...], priority: int, custom_filter_function: Optional[Callable[[str, dict], bool]])`.
        -   Local handler `priority` execution order.
        -   Local `ZeroMQEventBus.CONSUMED` sentinel behavior.
        -   `unsubscribe(subscription_id: uuid.UUID)`.
    6.  Verify JSON serialization of Python `dict` event data for transport and deserialization back to `dict`.
    7.  Ensure basic `asyncio` integration of the `ZeroMQEventBus` (message receiving loop, handler invocation) is functional and non-blocking.

-   **Key Components to Build for PoC:**
    1.  **Simple Broker Script (`zmq_broker_poc.py`):**
        -   Initializes ZMQ context.
        -   Creates an `XSUB` socket and binds it to a frontend address (e.g., `tcp://*:5559`).
        -   Creates an `XPUB` socket and binds it to a backend address (e.g., `tcp://*:5560`).
        -   Implements a simple polling loop (e.g., using `zmq.proxy_steerable` or a manual `zmq.Poller` loop) to receive messages from the `XSUB` socket and forward them to the `XPUB` socket.
        -   Includes basic logging for connections and message forwarding.
    2.  **`ZeroMQEventBus` Class (Core V1 implementation in `zeromq_eventbus_poc.py`):**
        -   Implement `__init__`, `start`, `stop` as per API design in Section 7.
        -   Implement `publish` method (serializes `dict` to JSON string, sends `topic_str` and `json_bytes`).
        -   Implement `subscribe` method (stores handler details, derives ZMQ prefix, calls ZMQ `sub_socket.subscribe()`).
        -   Implement `unsubscribe` method (removes handler, potentially ZMQ `sub_socket.unsubscribe()`).
        -   Implement the internal `asyncio` message receiving loop:
            -   Receives multi-part messages `[topic_bytes, json_payload_bytes]` from its ZMQ `SUB` socket.
            -   Decodes `topic_bytes` to string, deserializes `json_payload_bytes` to `dict`.
            -   Iterates through its list of registered (local) subscriptions/handlers.
            -   For each, applies `fnmatch` on `topic_pattern` against the received topic.
            -   If `fnmatch` passes, applies `custom_filter_function` (if provided).
            -   Collects all fully matched local handlers.
            -   Sorts these matched handlers by their `priority`.
            -   Invokes handler coroutines sequentially, checking for `ZeroMQEventBus.CONSUMED` to stop further local processing for that event instance.
    3.  **Publisher Test Script (`publisher_poc_test.py`):**
        -   Instantiates `ZeroMQEventBus`.
        -   Calls `await bus.start()`.
        -   In an `asyncio` loop or using `asyncio.sleep`, periodically calls `await bus.publish()` with:
            -   Various hierarchical topic strings.
            -   Sample `dict` payloads (e.g., `{'value': 123, 'type': 'sensor_reading'}`).
        -   Includes logging for published events.
    4.  **Subscriber Test Script (`subscriber_poc_test.py`):**
        -   Instantiates `ZeroMQEventBus`.
        -   Defines several `async def handler_function(topic: str, data: dict): ...` examples. Some should log received data, one might return `ZeroMQEventBus.CONSUMED`.
        -   Defines a few `def custom_filter(topic: str, data: dict) -> bool: ...` examples (e.g., check if `data['value'] > 100`).
        -   Calls `await bus.subscribe()` multiple times with:
            -   Different `topic_pattern`s (some specific, some with wildcards like `events.data.*`).
            -   Different handler functions.
            -   Different `priority` values to test ordering.
            -   Some with and some without `custom_filter_function`.
        -   Calls `await bus.start()`.
        -   Includes an `asyncio.Event` or similar to keep the script running to receive messages.
        -   Logs details of which handler received which event, and the order if multiple local handlers match.

-   **Success Criteria for PoC:**
    1.  The `zmq_broker_poc.py` correctly starts and forwards messages from publishers to subscribers.
    2.  `publisher_poc_test.py` successfully sends events with specified topics and `dict` data.
    3.  `subscriber_poc_test.py` receives events based on its ZMQ-level prefix subscriptions.
    4.  The `ZeroMQEventBus` instance in `subscriber_poc_test.py` correctly dispatches events to local handlers based on:
        a.  `fnmatch` matching of `topic_pattern`.
        b.  Evaluation of `custom_filter_function`.
        c.  Execution order defined by `priority`.
    5.  The `ZeroMQEventBus.CONSUMED` sentinel, when returned by a handler, correctly prevents subsequent local handlers (for that event instance in that subscriber) from being called.
    6.  Event data (`dict`) is accurately transmitted and received (JSON serialization/deserialization works).
    7.  The PoC scripts run without unexpected `asyncio` errors or ZMQ-related crashes.
    8.  Basic `unsubscribe()` call removes a handler, and it no longer receives matching events.

## 10. Open Questions and Considerations (V1)

-   **Error Handling and Reporting:**
    -   **Serialization/Deserialization:** How should errors during JSON processing (e.g., invalid JSON, encoding issues) be handled within `ZeroMQEventBus`? Log and drop, or raise specific exceptions?
    -   **Handler Coroutine Errors:** If a subscribed handler coroutine raises an exception, should `ZeroMQEventBus` catch it, log it, and continue, or let the exception propagate (which might stop the bus's receiving loop if not handled carefully)?
    -   **ZMQ-Level Errors:** How should errors from `pyzmq` operations (e.g., socket creation, connection failures to the broker, send/receive errors) be managed, logged, and potentially surfaced to the application?
-   **Connection Management and Retries (to Broker):**
    -   Should `ZeroMQEventBus.start()` implement retries if the initial connection to the broker sockets fails?
    -   If an established connection to the broker is lost, should the `ZeroMQEventBus` instance attempt to reconnect automatically? What strategy (e.g., periodic retries, exponential backoff)? How does this affect publishing/subscribing during downtime?
-   **Broker Robustness and Lifecycle:**
    -   The PoC broker is minimal. A V1 production broker script should include:
        -   Graceful shutdown handling (e.g., on SIGINT/SIGTERM) to close ZMQ sockets and context properly.
        -   More comprehensive logging of its activities (connections, errors, potentially message rates).
        -   Basic error handling for its ZMQ operations.
    -   How will the broker process be managed (e.g., run as a separate service)?
-   **Security:**
    -   For V1, assuming the broker and all clients run on `localhost` or within a trusted network, ZMQ-level security is out of scope.
    -   If future versions require communication over untrusted networks, ZMQ security mechanisms (e.g., ZAP authentication, CurveZMQ encryption) would need to be designed and implemented.
-   **Performance Considerations for V1:**
    -   **JSON Overhead:** JSON processing (serialization/deserialization) is inherently slower and produces larger messages than binary formats like MessagePack. This is accepted for V1 simplicity but should be noted as a potential area for future optimization if performance becomes an issue.
    -   **Client-Side Filtering:** The overhead of iterating through all local subscriptions and applying `fnmatch` and `custom_filter_function` for every received message. If there are many subscriptions or very complex filters, this could impact performance on the client side.
    -   Consider basic performance testing as part of or after the PoC.
-   **Integration with Existing `AsyncEventBus` Users:**
    -   This will be a significant refactoring task. Key areas of change for existing components:
        -   Switching from Pydantic models for event data to plain Python `dict`s. This requires updating event publishing logic and handler signatures/logic.
        -   Adapting to the new `ZeroMQEventBus` API for `publish`, `subscribe`, and `unsubscribe`.
        -   Ensuring topic strings and patterns are correctly mapped.
-   **Configuration Management:**
    -   How will `ZeroMQEventBus` instances and the broker itself be configured with necessary parameters (e.g., broker IP addresses, port numbers)? Likely through a shared configuration file or environment variables.
-   **Testing Strategy for `ZeroMQEventBus` and Broker:**
    -   Beyond the PoC scripts, a more formal testing strategy will be needed:
        -   Unit tests for `ZeroMQEventBus` methods (mocking ZMQ interactions where appropriate).
        -   Integration tests involving the `ZeroMQEventBus`, the broker, and simple publisher/subscriber clients.
-   **`unsubscribe()` and ZMQ Prefix Management:**
    -   The "Optional Optimization" in the `ZeroMQEventBus.unsubscribe()` API (Section 7) for managing ZMQ-level `sub_socket.unsubscribe()` calls needs careful and robust implementation. A reliable reference counting mechanism for ZMQ topic prefixes will be essential to prevent premature unsubscriptions if multiple client-side patterns map to the same underlying ZMQ prefix, or to ensure unsubscription happens when a prefix is no longer needed.
-   **Event Type Discovery/Schema (Post-V1):**
    -   Without Pydantic models defining event structures, ensuring publishers and subscribers agree on the `dict` keys and value types for different events relies on convention or shared documentation. For future versions, a schema registration/discovery mechanism might be considered if event structures become complex or numerous.
-   **Message Ordering:**
    -   ZeroMQ PUB/SUB does not guarantee that a subscriber will receive messages in the exact order they were published if there are multiple publishers or network hops. For the V1 local broker, ordering from a single publisher to a single subscriber is generally reliable, but this is a known characteristic of PUB/SUB. If strict ordering of specific event sequences becomes critical across the system, alternative ZMQ patterns or application-level sequencing might be needed in the future.