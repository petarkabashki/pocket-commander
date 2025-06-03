# Command Handling in Pocket Commander

This document outlines how commands are handled within the Pocket Commander system, detailing the components involved and the flow of information.

## Command Handling Flow

The command handling process is event-driven and involves several key components interacting via an `AsyncEventBus`.

1.  **User Input (UI Client):**
    *   The user types a command into an interface managed by an `AbstractAgUIClient` implementation, such as the [`TerminalAgUIClient`](../pocket_commander/ag_ui/terminal_client.py:1).
    *   The UI client captures this raw input.

2.  **Input Event Publication:**
    *   The UI client ([`TerminalAgUIClient`](../pocket_commander/ag_ui/terminal_client.py:1) or other) publishes an `AppInputEvent` to the central [`AsyncEventBus`](../pocket_commander/event_bus.py:1). This event, defined in [`pocket_commander/events.py`](../pocket_commander/events.py:1), contains the user's input string.
    *   The UI client also typically publishes the user's input as a series of `ag_ui.TextMessage*Events` (with `role="user"`) to the event bus so it appears in the displayed message history. These events are defined in [`pocket_commander/ag_ui/events.py`](../pocket_commander/ag_ui/events.py:1).

3.  **Application Core Processing (`app_core.py`):**
    *   The [`AppCore`](../pocket_commander/app_core.py:1) module subscribes to `AppInputEvent` on the [`AsyncEventBus`](../pocket_commander/event_bus.py:1).
    *   Upon receiving an `AppInputEvent`, [`AppCore`](../pocket_commander/app_core.py:1) parses the input string.
        *   **Global Commands:** If the input is identified as a global command (e.g., `/agent switch <name>`, `/help`, `/exit`), [`AppCore`](../pocket_commander/app_core.py:1) handles its execution directly. The logic for parsing and identifying these commands might involve the [`pocket_commander/commands/parser.py`](../pocket_commander/commands/parser.py:1) module.
        *   **Agent Dispatch:** If the input is not a global command, it's considered input for the currently active agent. [`AppCore`](../pocket_commander/app_core.py:1) then typically publishes events like `RunStartedEvent` and `MessagesSnapshotEvent` (containing the user's input as an `ag_ui_types.UserMessage`) to the event bus, which the active agent subscribes to.

4.  **Agent Processing (If Applicable):**
    *   The active agent (a PocketFlow `AsyncNode` or `Flow`) receives the input via the events published by [`AppCore`](../pocket_commander/app_core.py:1).
    *   The agent processes the command/query according to its specific logic. This might involve calling tools, interacting with LLMs, etc.

5.  **Output Generation and Display:**
    *   **Global Commands:** Output from global commands executed by [`AppCore`](../pocket_commander/app_core.py:1) is published as `ag_ui.events` (e.g., `TextMessageStartEvent`, `TextMessageContentEvent`, `TextMessageEndEvent` with `role="system"`) to the [`AsyncEventBus`](../pocket_commander/event_bus.py:1).
    *   **Agents:** Agents also publish their responses, status updates, tool usage, and errors as a stream of `ag_ui.events` to the [`AsyncEventBus`](../pocket_commander/event_bus.py:1).
    *   The UI client ([`TerminalAgUIClient`](../pocket_commander/ag_ui/terminal_client.py:1)) subscribes to these various `ag_ui.events`.
    *   Upon receiving these events, the UI client renders the information appropriately for the user (e.g., printing messages to the console, showing tool call progress).

## Key Components Involved:

*   **UI Client (`AbstractAgUIClient` / `TerminalAgUIClient`):**
    *   [`pocket_commander/ag_ui/client.py`](../pocket_commander/ag_ui/client.py:1) (Abstract definition)
    *   [`pocket_commander/ag_ui/terminal_client.py`](../pocket_commander/ag_ui/terminal_client.py:1) (Terminal implementation)
    *   Responsible for capturing user input and displaying output.
*   **Event Bus (`AsyncEventBus`):**
    *   [`pocket_commander/event_bus.py`](../pocket_commander/event_bus.py:1)
    *   The central message broker for asynchronous communication. This is an **in-process event bus** using `asyncio.Queue`.
*   **Event Definitions:**
    *   [`pocket_commander/events.py`](../pocket_commander/events.py:1): Defines `AppInputEvent` and re-exports `ag_ui.events`.
    *   [`pocket_commander/ag_ui/events.py`](../pocket_commander/ag_ui/events.py:1): Defines the rich `ag_ui` event protocol for detailed UI updates.
*   **Application Core (`AppCore`):**
    *   [`pocket_commander/app_core.py`](../pocket_commander/app_core.py:1)
    *   Orchestrates command handling, global command execution, and dispatch to agents.
*   **Command Parser:**
    *   [`pocket_commander/commands/parser.py`](../pocket_commander/commands/parser.py:1)
    *   Involved in parsing command syntax, especially for global commands. Uses definitions from [`pocket_commander/commands/definition.py`](../pocket_commander/commands/definition.py:1).
*   **Agents (PocketFlow Nodes/Flows):**
    *   Located in `pocket_commander/core_agents/` and user-defined locations.
    *   Process non-global commands and queries.

## ZeroMQ Messages:

The core command handling flow relies on the in-process `AsyncEventBus`. Events are Python Pydantic objects passed within the same process.

While a document [`docs/zeromq_event_bus_architecture.md`](zeromq_event_bus_architecture.md:1) outlines a conceptual plan for ZeroMQ integration (for future inter-process communication), **ZeroMQ messages are not currently part of the primary command handling flow as implemented.**

## Visual Summary (Conceptual Flow)

```mermaid
sequenceDiagram
    participant User
    participant TerminalAgUIClient
    participant AsyncEventBus
    participant AppCore
    participant ActiveAgent

    User->>TerminalAgUIClient: Types command (e.g., "/agent list" or "summarize this text")
    TerminalAgUIClient->>AsyncEventBus: Publishes AppInputEvent
    Note over TerminalAgUIClient, AppCore: (UI also publishes user input as ag_ui.TextMessage for history)
    AsyncEventBus-->>AppCore: Delivers AppInputEvent
    AppCore->>AppCore: Parses input
    alt Global Command (e.g., /agent list)
        AppCore->>AppCore: Executes global command
        AppCore->>AsyncEventBus: Publishes ag_ui.TextMessageEvents (output)
    else Agent Command/Query
        AppCore->>AsyncEventBus: Publishes RunStartedEvent / MessagesSnapshotEvent
        AsyncEventBus-->>ActiveAgent: Delivers events
        ActiveAgent->>ActiveAgent: Processes command/query
        ActiveAgent->>AsyncEventBus: Publishes ag_ui.events (output, tool calls, etc.)
    end
    AsyncEventBus-->>TerminalAgUIClient: Delivers ag_ui.events
    TerminalAgUIClient->>User: Displays output/response