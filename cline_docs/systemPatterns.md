# System Patterns

## How the system is built
The system is built using Python, with a strong emphasis on asynchronous operations (`asyncio`). It is fundamentally an **agentic AI workflow engine** based on the **PocketFlow framework**, now enhanced with a robust **event-driven architecture** for inter-agent and agent-application communication.

## Key technical decisions
-   **PocketFlow Framework:** Adoption of PocketFlow for defining and managing agentic workflows. Agents are implemented as PocketFlow `AsyncNode` or `Flow` instances.
-   **Asynchronous Operations (`asyncio`):** Essential for building responsive and efficient AI agents that can handle multiple tasks or I/O-bound operations concurrently.
-   **Event-Driven Architecture:** A central `AsyncEventBus` ([`pocket_commander/event_bus.py`](pocket_commander/event_bus.py:1)) manages communication. Agents and core components publish and subscribe to specific event types (e.g., `AppInputEvent`, `AgentOutputEvent`, `AgentLifecycleEvent` from [`pocket_commander/events.py`](pocket_commander/events.py:1)).
-   **Filesystem-Based Agent Discovery:** Agents are discovered from specified directories (`agent_discovery_folders` in [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1)). The `AgentResolver` ([`pocket_commander/agent_resolver.py`](pocket_commander/agent_resolver.py:1)) loads and prepares agent code.
-   **YAML-Based Agent Configuration:** Agents are defined in [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1), specifying their module `path`, `class_name` or `composition_function_name`, and `init_args` (including `slug`, `llm_profile`, `tool_names`, etc.). The `AgentConfig` Pydantic model ([`pocket_commander/types.py`](pocket_commander/types.py:1)) defines this structure.
-   **Tool-Based Architecture:** Functionality is extended through modular, self-contained "tools" that agents can utilize within their workflows.
-   **Interactive Terminal Interface:** Using `prompt-toolkit` and `rich` for a developer-friendly CLI to interact with and test the system.

## Architecture patterns
-   **Agentic Workflow Engine (PocketFlow):** The core pattern is an engine that executes predefined or dynamically generated workflows. Agents are PocketFlow `AsyncNode` or `Flow` implementations.
-   **Event-Driven / Publish-Subscribe:**
    -   The `AsyncEventBus` acts as a central message broker.
    -   Components (agents, `app_core`, UI handlers) publish events to the bus.
    -   Interested components subscribe to specific event types to react to them.
    -   This decouples components and allows for flexible communication patterns.
-   **Service Locator / Discovery (AgentResolver):** The `AgentResolver` is responsible for finding and loading agent implementations from the filesystem based on configuration, abstracting the agent creation process.
-   **Configuration as Code (YAML):** Agent definitions and their initial parameters are managed declaratively in a YAML file, promoting separation of configuration from code.
-   **Modular Design:** Enforced by PocketFlow's Node/Flow structure, the separation of tools, the event-driven nature, and the discoverable agent modules.

## New Agent System Architecture Details

The refactored agent system revolves around an event-driven model and filesystem-based discovery:

1.  **Event Bus (`AsyncEventBus`):**
    *   Located in [`pocket_commander/event_bus.py`](pocket_commander/event_bus.py:1).
    *   Provides `publish()` and `subscribe()` methods for asynchronous event handling.
    *   Ensures decoupled communication between different parts of the application, particularly between agents and the `app_core` or UI components.

2.  **Core Event Types (`pocket_commander/events.py`):**
    *   `AppInputEvent`: Published when the user provides input to the application. Agents subscribe to this to receive tasks or data.
    *   `AgentOutputEvent`: Published by agents when they produce a result, message, or request for action (e.g., tool use). The `app_core` or UI handlers subscribe to this.
    *   `AgentLifecycleEvent`: Published to manage agent state (e.g., `START`, `STOP`, `INITIALIZED`). Agents might listen for their own lifecycle events or others.
    *   Other specific events can be defined as needed for more granular communication.

3.  **Agent Configuration (`AgentConfig` & `pocket_commander.conf.yaml`):**
    *   `AgentConfig` Pydantic model in [`pocket_commander/types.py`](pocket_commander/types.py:1) defines the structure for an agent's configuration.
    *   In [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1), agents are defined under an `agents` key. Each agent entry includes:
        *   `slug`: A unique identifier for the agent.
        *   `path`: The Python module path to the agent's code (e.g., `pocket_commander.core_agents.main_agent`).
        *   `class_name` (for Node-based agents) or `composition_function_name` (for Flow-based agents): The specific class or function to load.
        *   `description`: A human-readable description.
        *   `init_args`: A dictionary of arguments to pass to the agent's constructor or composition function (e.g., `llm_profile`, `tool_names`).

4.  **Agent Discovery and Loading (`AgentResolver`):**
    *   Located in [`pocket_commander/agent_resolver.py`](pocket_commander/agent_resolver.py:1).
    *   Scans directories specified in `agent_discovery_folders` (from [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1)) for Python modules.
    *   Loads agent classes or composition functions based on the `AgentConfig` entries.
    *   Instantiates agents with their specified `init_args`.

5.  **Agents as PocketFlow Implementations:**
    *   Agents are now either `pocketflow.base.AsyncNode` subclasses or functions that compose PocketFlow `Flows`.
    *   They interact with the system by subscribing to relevant events (like `AppInputEvent` to get tasks) and publishing events (like `AgentOutputEvent` to return results or `ToolCallEvent` to request tool execution).
    *   Their `__init__` method (or composition function) typically takes `AppServices` (which includes the `event_bus`) and other `init_args` from the YAML configuration.

## Folder Conventions

### `pocket_commander/nodes/`
Contains individual, reusable PocketFlow `AsyncNode` implementations. These are often building blocks for more complex agent logic.

### `pocket_commander/flows/`
Defines PocketFlow `Flows`, which orchestrate sequences or graphs of `AsyncNode`s. Agent logic can be encapsulated within a flow.

### `pocket_commander/core_agents/`
This new directory houses the primary, refactored agent implementations (e.g., [`main_agent.py`](pocket_commander/core_agents/main_agent.py:1), [`composer_agent.py`](pocket_commander/core_agents/composer_agent.py:1), [`tool_agent.py`](pocket_commander/core_agents/tool_agent.py:1)). These modules contain the agent's PocketFlow Node/Flow definition.

### `pocket_commander/utils/`
Utility modules and helper functions.

### `pocket_commander/tools/`
Modules defining specific "tools" callable by agents.

### `pocket_commander/commands/`
Contains the core components of the (now potentially less central) agent-specific command system. Its role might evolve or diminish with the event-driven architecture.

### `pocket_commander/event_bus.py`
Defines the `AsyncEventBus` class.

### `pocket_commander/events.py`
Defines core Pydantic event models for the Pub/Sub system.

### `pocket_commander/agent_resolver.py`
Defines the `AgentResolver` for discovering and loading agents.

### `pocket_commander/app_core.py`
Manages the application lifecycle, event bus integration, and agent switching. Heavily modified to support the new event-driven agent system.

### `pocket_commander/config_loader.py`
Responsible for loading and parsing [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1), including the new agent configurations. Heavily modified.