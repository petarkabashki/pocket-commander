# System Patterns

## How the system is built
The system is built using Python, with a strong emphasis on asynchronous operations (`asyncio`). It is fundamentally an **agentic AI workflow engine** based on the **PocketFlow framework**, enhanced with a robust **event-driven architecture** for inter-agent and agent-application communication. User interaction is managed through an abstract `AgUIClient` interface, with a concrete terminal implementation.

## Key technical decisions
-   **PocketFlow Framework:** Adoption of PocketFlow for defining and managing agentic workflows. Agents are implemented as PocketFlow `AsyncNode` or `Flow` instances.
-   **Asynchronous Operations (`asyncio`):** Essential for building responsive and efficient AI agents that can handle multiple tasks or I/O-bound operations concurrently.
-   **Event-Driven Architecture:**
    -   A central `AsyncEventBus` ([`pocket_commander/event_bus.py`](pocket_commander/event_bus.py:1)) manages communication.
    -   `AppInputEvent` ([`pocket_commander/events.py`](pocket_commander/events.py:1)) is published by UI clients to send user input to `app_core`.
    -   Agents and `app_core` communicate with UI clients primarily using the `ag_ui.events` protocol (events defined in [`pocket_commander/ag_ui/events.py`](pocket_commander/ag_ui/events.py:1) and re-exported via [`pocket_commander/events.py`](pocket_commander/events.py:1)).
    -   Internal events like `AgentLifecycleEvent` are also used.
-   **Abstract UI Client (`AbstractAgUIClient`):**
    -   Defined in [`pocket_commander/ag_ui/client.py`](pocket_commander/ag_ui/client.py:1).
    -   Provides a standard interface for different UI implementations (e.g., terminal, web).
    -   Handles sending `AppInputEvent` and processing `ag_ui.events` for display.
-   **Terminal UI Client (`TerminalAgUIClient`):**
    -   Implemented in [`pocket_commander/ag_ui/terminal_client.py`](pocket_commander/ag_ui/terminal_client.py:1).
    -   Uses `prompt-toolkit` and `rich` for the interactive terminal.
    -   Replaces the previous `TerminalInteractionFlow`.
-   **Filesystem-Based Agent Discovery:** Agents are discovered from specified directories (`agent_discovery_folders` in [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1)). The `AgentResolver` ([`pocket_commander/agent_resolver.py`](pocket_commander/agent_resolver.py:1)) loads and prepares agent code.
-   **YAML-Based Agent Configuration:** Agents are defined in [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1), specifying their module `path`, `class_name` or `composition_function_name`, and `init_args`. The `AgentConfig` Pydantic model ([`pocket_commander/types.py`](pocket_commander/types.py:1)) defines this structure.
-   **Tool-Based Architecture:** Functionality is extended through modular, self-contained "tools".

## Architecture patterns
-   **Agentic Workflow Engine (PocketFlow):** Core pattern for executing workflows.
-   **Event-Driven / Publish-Subscribe:** Central to all communication. UI clients, `app_core`, and agents interact via events on the `AsyncEventBus`.
-   **Abstract UI Layer:** The `AbstractAgUIClient` allows for different UI frontends to connect to the same backend logic.
-   **Service Locator / Discovery (AgentResolver):** For agent loading.
-   **Configuration as Code (YAML):** For agent and application settings.
-   **Modular Design:** Enforced by PocketFlow, tools, events, and the new UI client abstraction.

## Agent System & UI Interaction Details

1.  **Event Bus (`AsyncEventBus`):** Central message broker in [`pocket_commander/event_bus.py`](pocket_commander/event_bus.py:1).

2.  **Core Event Types (`pocket_commander/events.py`):**
    *   `AppInputEvent`: Published by an `AbstractAgUIClient` (e.g., `TerminalAgUIClient`) when the user submits input. Consumed by `app_core` to handle global commands or dispatch to the active agent.
    *   `ag_ui.events` (e.g., `TextMessageStartEvent`, `ToolCallStartEvent`, etc.): A suite of events defined in [`pocket_commander/ag_ui/events.py`](pocket_commander/ag_ui/events.py:1) used by agents and `app_core` to stream rich output to UI clients. `AbstractAgUIClient` implementations subscribe to these to render UI updates.
    *   `AgentLifecycleEvent`: Internal event for managing agent state.
    *   `InternalExecuteToolRequest`: Internal event for `app_core` to request tool execution from a `ToolAgent`.

3.  **UI Client (`AbstractAgUIClient` / `TerminalAgUIClient`):**
    *   `AbstractAgUIClient` ([`pocket_commander/ag_ui/client.py`](pocket_commander/ag_ui/client.py:1)) defines the contract.
    *   `TerminalAgUIClient` ([`pocket_commander/ag_ui/terminal_client.py`](pocket_commander/ag_ui/terminal_client.py:1)) is the concrete implementation for the terminal.
    *   The client:
        *   Captures raw user input.
        *   Publishes an `AppInputEvent` to the `event_bus`.
        *   Also publishes the user's own input as a series of `ag_ui.TextMessage*Events` (with `role="user"`) to ensure it's part of the displayed message history.
        *   Subscribes to various `ag_ui.events` (like `TextMessageStartEvent`, `ToolCallStartEvent`, `RunErrorEvent`, etc.) to receive data from agents/`app_core`.
        *   Renders these events to the user (e.g., printing messages, tool call status to the console).
        *   Handles requests for dedicated input (e.g., prompts for passwords or specific choices) via internal `RequestPromptEvent` and `PromptResponseEvent`.

4.  **Application Core (`app_core.py`):**
    *   Subscribes to `AppInputEvent`.
    *   On receiving `AppInputEvent`:
        *   Parses the input for global commands (e.g., `/agent`, `/help`). If a global command is found, it's executed directly by `app_core`. Global command output is sent as `ag_ui.TextMessage*Events` (with `role="system"`).
        *   If not a global command, the input is dispatched to the currently active agent. This typically involves:
            *   Publishing a `RunStartedEvent`.
            *   Publishing a `MessagesSnapshotEvent` containing the user's input as an `ag_ui_types.UserMessage`.
    *   Orchestrates tool calls by listening to `ToolCallStart/Args/EndEvents` from agents and publishing `InternalExecuteToolRequest`.

5.  **Agent Configuration & Discovery:** (Largely unchanged by UI refactor)
    *   `AgentConfig` ([`pocket_commander/types.py`](pocket_commander/types.py:1)) and [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1).
    *   `AgentResolver` ([`pocket_commander/agent_resolver.py`](pocket_commander/agent_resolver.py:1)).

6.  **Agents as PocketFlow Implementations:** (Largely unchanged by UI refactor)
    *   Agents subscribe to `RunStartedEvent` and `MessagesSnapshotEvent` (or other relevant events) to receive tasks/input.
    *   Agents publish `ag_ui.events` (e.g., `TextMessageStart/Content/End`, `ToolCallStart/Args/End`) to stream their output and actions to the UI client.

## Folder Conventions (Updated for UI Client)
*   ... (other conventions remain similar) ...
*   `pocket_commander/ag_ui/`: Contains UI protocol definitions and client implementations.
    *   `events.py`: Defines `ag_ui` Pydantic event models for UI communication.
    *   `types.py`: Defines `ag_ui` Pydantic type models (e.g., `Message`, `ToolCall`).
    *   `client.py`: Defines `AbstractAgUIClient`.
    *   `terminal_client.py`: Defines `TerminalAgUIClient`.
*   `pocket_commander/flows/terminal_interaction_flow.py`: **Obsolete**. Functionality moved to `terminal_client.py`.
*   ... (other conventions remain similar) ...