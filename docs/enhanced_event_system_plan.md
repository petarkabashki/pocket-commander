# Plan: Enhanced Event System for Pocket Commander

This document outlines the plan to enhance the event system in Pocket Commander, focusing on pattern-based subscriptions, listen/consume capabilities, and configurable event display for UI clients.

## Core Principle

The `TerminalAgUIClient` (and potentially other future UI clients) will require explicit pattern-based subscriptions to display any event. Nothing will be displayed by default without a matching subscription configuration.

## Phase 1: Enhance `AsyncEventBus` (in `pocket_commander/event_bus.py`)

1.  **Event Topics:**
    *   Modify `BaseEvent` (in `pocket_commander/event_bus.py`) to include an optional `topic: Optional[str] = None`.
    *   When an event is published, if `topic` is `None`, the bus auto-generates it:
        *   For `ag_ui.events` (from `pocket_commander/ag_ui/events.py`): `f"ag_ui.{event.type.value}"` (e.g., "ag_ui.TEXT_MESSAGE_START").
        *   For other internal events (inheriting from `event_bus.BaseEvent`): `type(event).__name__` (e.g., "AppInputEvent").

2.  **Pattern-Based Subscriptions & Priority (using `fnmatch`):**
    *   Change `AsyncEventBus._subscribers` from `Dict[Type[BaseEvent], List[EventHandler]]` to `Dict[str, List[Tuple[int, EventHandler]]]` (where the key is the pattern string, and the value is a list of (priority, handler) tuples).
    *   Modify `AsyncEventBus.subscribe` method signature to `subscribe(self, pattern: str, handler: EventHandler, priority: int = 0)`.
    *   Handlers for a given pattern will be stored sorted by their priority (lower numbers execute first).

3.  **Event Processing with Consume Logic:**
    *   In `AsyncEventBus._process_event(self, event: BaseEvent)`:
        *   Determine the event's generated or explicit `event_topic`.
        *   Find all subscribed `pattern`s that match the `event_topic` using `fnmatch.fnmatch()`.
        *   Collect all `(priority, handler)` tuples from these matching patterns.
        *   Sort the collected handlers globally by priority.
        *   Execute these handlers *sequentially* in order of priority.
        *   If a handler returns a special sentinel value, `AsyncEventBus.CONSUMED`, the bus will stop processing that specific event instance for any subsequent, lower-priority handlers.

4.  **Add Sentinel:**
    *   Define a class-level sentinel: `AsyncEventBus.CONSUMED = object()`.

## Phase 2: Adapt `TerminalAgUIClient` (in `pocket_commander/ag_ui/terminal_client.py`)

1.  **Explicit Pattern Subscriptions for All Displayed Events:**
    *   In `TerminalAgUIClient.initialize()`:
        *   Remove existing direct event type subscriptions.
        *   Introduce an internal `_subscription_config: List[Dict[str, Any]]`. This list will define *all* event patterns the terminal client should listen to and how to handle them. Example structure for each entry:
            ```python
            # Example entry in self._subscription_config
            {
                "pattern": "ag_ui.TEXT_MESSAGE_START.user", # Topic might include role for granular control
                "handler_method_name": "_handle_text_message_stream", # Name of the method in TerminalAgUIClient
                "priority": 0,
                # "consume_if_debug": True # Optional: flag for conditional consumption
            }
            ```
        *   The `initialize()` method will iterate this configuration and call `self.event_bus.subscribe(pattern, getattr(self, handler_method_name), priority)`.
        *   This `_subscription_config` will be the primary mechanism for controlling terminal display and could later be loaded from `pocket_commander.conf.yaml`. A default set of subscriptions will be needed to replicate current common output (user messages, assistant messages, system messages, tool calls/results, errors).

2.  **Refactor Event Handlers:**
    *   Consolidate specific handlers (e.g., `_handle_text_message_start`, `_handle_text_message_content`, `_handle_text_message_end`) into broader "stream" handlers (e.g., `_handle_text_message_stream(self, event)`).
    *   This stream handler will receive all events matching its subscribed pattern (e.g., "ag_ui.TEXT_MESSAGE.*") and will internally dispatch to specific rendering logic based on `event.type` and other event attributes (like `event.role`).
    *   Handlers can return `AsyncEventBus.CONSUMED` based on their internal logic (e.g., if a debug mode is active and the event is intended only for debugging and not for normal display).

## Phase 3: User-Facing Features (Future Enhancements)

*   Implement global commands (e.g., `/config terminal subscribe <pattern> [priority] <handler_info>` and `/config terminal unsubscribe <pattern_or_id>`) to allow dynamic management of the `TerminalAgUIClient`'s `_subscription_config` and re-initialize its subscriptions on the event bus.
*   Introduce commands to toggle client-side debug modes that might influence whether its handlers consume events or alter formatting.

## Mermaid Diagram: Proposed Event Flow with Pattern Matching and Consume

```mermaid
sequenceDiagram
    participant Publisher
    participant AsyncEventBus
    participant HandlerA_Prio0_Pattern1
    participant HandlerB_Prio1_Pattern1
    participant HandlerC_Prio0_Pattern2

    Publisher->>AsyncEventBus: publish(event{topic="ag_ui.TEXT_MESSAGE.CONTENT"})
    AsyncEventBus->>AsyncEventBus: Determine event_topic ("ag_ui.TEXT_MESSAGE.CONTENT")
    AsyncEventBus->>AsyncEventBus: Find matching patterns (e.g., Pattern1="ag_ui.TEXT_MESSAGE.*", Pattern2="ag_ui.*.CONTENT")
    AsyncEventBus->>AsyncEventBus: Collect handlers with priority: [(0, HandlerA), (1, HandlerB), (0, HandlerC)]
    AsyncEventBus->>AsyncEventBus: Sort handlers by priority: [(0, HandlerA), (0, HandlerC), (1, HandlerB)] (Order of A/C with same prio is based on subscription order for that prio)

    AsyncEventBus->>HandlerA_Prio0_Pattern1: await handle(event)
    HandlerA_Prio0_Pattern1-->>AsyncEventBus: return AsyncEventBus.CONSUMED

    Note over AsyncEventBus: Event consumed by HandlerA. Stop processing for this event.
    %% AsyncEventBus does NOT call HandlerC or HandlerB for this event.