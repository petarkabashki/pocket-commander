# Agent System Refactor Plan (Pub/Sub Architecture)

This document outlines the plan to refactor the agent system in Pocket Commander. The new architecture will make agents (PocketFlow Nodes or Flows) discoverable from the filesystem, configurable via YAML, and will use a Pub/Sub mechanism for interaction with the application core.

## 1. Define New Agent Configuration Schema

*   **File:** [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml)
*   **Changes:**
    *   Add a top-level key `agent_discovery_folders: List[str]` for specifying directories to scan for agent files.
    *   The `agents:` section will map an agent `slug` (unique identifier) to its configuration dictionary:
        *   `path: str`: Path to the Python file containing the agent definition (Node class, Flow class, or flow composition function). Relative paths are to the project root or discovery folders.
        *   `class_name: Optional[str]`: The specific name of the Node or Flow class within the file. If omitted, naming conventions (see Item 2) will apply.
        *   `composition_function_name: Optional[str]`: The name of a function that returns an instantiated and configured Flow or Node. This can be used as an alternative to direct class instantiation.
        *   `init_args: Optional[Dict[str, Any]]`: A dictionary of arguments to be passed to the agent class's `__init__` method or to the `composition_function_name`. This is where parameters like `llm_profile`, `tool_names` (for an agent-specific tool registry), or other custom agent parameters will be defined.
        *   `description: Optional[str]`: A human-readable description of the agent.

*   **File:** [`pocket_commander/types.py`](pocket_commander/types.py)
*   **Changes:**
    *   Update or create an `AgentConfig` Pydantic model to reflect the new YAML schema. This model will store the parsed configuration, including the resolved target for instantiation (the class object or composition function) after discovery and parsing.

## 2. Implement Agent Discovery & Resolution Service

*   **New Component:** An `AgentResolver` service (e.g., a class in `pocket_commander/agent_resolver.py`).
*   **Responsibilities:**
    *   Accepts an agent slug and its raw YAML configuration.
    *   Resolves the `path` to the agent's Python file (handling relative/absolute paths and discovery folders).
    *   Loads the Python module from the resolved `path` using `importlib`.
    *   **Target Identification Logic:**
        1.  If `composition_function_name` is provided in the config, retrieves that specific function from the module.
        2.  Else if `class_name` is provided, retrieves that specific class (which must be a subclass of `BaseNode`, `AsyncNode`, `Flow`, or `AsyncFlow`).
        3.  Else (neither `composition_function_name` nor `class_name` is provided), applies naming conventions in the following order of precedence:
            *   Looks for a class named exactly `Agent` (must be a Node/Flow subclass).
            *   Looks for a class whose name matches the filename in CamelCase (e.g., `MyAgentNode` in `my_agent_node.py`, must be a Node/Flow subclass).
            *   Looks for a flow composition function named `create_flow` or `create_{filename}_flow` (e.g., `create_my_agent_flow` in `my_agent.py`).
    *   Handles errors if no suitable target (class or function) is found in the module, or if ambiguities arise (e.g., multiple conventions met) without explicit configuration.
    *   Caches loaded modules and resolved agent targets (classes/functions) to optimize subsequent lookups.
    *   This service will be utilized by `config_loader.py` during the parsing of agent configurations.

## 3. Implement Asyncio Event Bus & Core Events

*   **New Component:** `AsyncEventBus` class (e.g., in `pocket_commander/event_bus.py`).
    *   Core methods: `async def subscribe(self, event_type: Type[BaseEvent], handler_coroutine: Callable[[BaseEvent], Awaitable[None]])` and `async def publish(self, event: BaseEvent)`.
    *   Manages a dictionary of event types to lists of subscriber coroutines.
*   **New Module:** Define core Pydantic models for events (e.g., in `pocket_commander/events.py`). All events should inherit from a `BaseEvent` model.
    *   `AppInputEvent(raw_text: str, command_input: AbstractCommandInput)`: Published when non-global input is received.
    *   `AgentOutputEvent(message: str, style: Optional[str] = None)`: Published by agents to send messages to the UI.
    *   `AgentLifecycleEvent(agent_name: str, lifecycle_type: Literal["activating", "deactivating"])`: Published by `app_core` when an agent's state changes.
    *   `RequestPromptEvent(prompt_message: str, is_sensitive: bool, response_event_type: str, correlation_id: str)`: Published by agents needing dedicated user input. `response_event_type` indicates which event to listen for with the answer.
    *   `PromptResponseEvent(response_event_type: str, response_text: str, correlation_id: str)`: Published by the input mechanism in response to `RequestPromptEvent`.
*   **Integration:** An instance of `AsyncEventBus` will be created and added to the `AppServices` dictionary, making it available to various components.

## 4. Refactor Agent Loading & Interaction in `app_core.py`

*   **`_switch_to_agent` function:**
    *   Publishes an `AgentLifecycleEvent` (type="deactivating") for the currently active agent (if any) via the event bus.
    *   Retrieves the resolved `AgentConfig` for the new agent (this config now contains the target class or composition function, thanks to the `AgentResolver`).
    *   **Instantiation/Setup:**
        *   If the target in `AgentConfig` is a composition function: Calls this function, passing `AppServices` (which includes the event bus) and the `init_args` from the agent's configuration. The function is expected to return a fully instantiated and configured Node or Flow object.
        *   If the target is a class: Instantiates this class, passing `AppServices` and the `init_args`.
        *   **Tool Registry:** If `tool_names` are specified in the agent's `init_args`, `_switch_to_agent` will create an agent-specific `ToolRegistry` instance (using `create_agent_tool_registry` from [`pocket_commander/tools/registry.py`](pocket_commander/tools/registry.py:150)). This dedicated registry instance will be passed to the agent's `__init__` method or composition function (likely as part of the `init_args` dictionary or as a specific parameter if the agent's signature is designed to accept it).
    *   The instantiated agent (Node/Flow) is responsible for subscribing to relevant events (e.g., `AppInputEvent`, `AgentLifecycleEvent`) via the event bus (available in `AppServices`) during its `__init__` process or a dedicated setup method (e.g., `async def initialize_agent(self, app_services: AppServices)`).
    *   Publishes an `AgentLifecycleEvent` (type="activating") for the new agent via the event bus.
    *   The `application_state["active_agent_commands"]` list will be removed or will always be empty, as agents no longer register commands with `app_core`.
*   **`top_level_app_input_handler` function:**
    *   Continues to handle global commands (e.g., those prefixed with `/`).
    *   If the input is not a recognized global command, it publishes an `AppInputEvent` containing the raw input string and `command_input` object to the event bus. The active agent (if any) will pick this up.
*   The global `/help` command will only list global commands. Agent-specific help/usage information will be provided by the agent itself in response to direct input (e.g., user typing "help" to the agent).

## 5. Define Agent (Node/Flow/Composition Function) Responsibilities for Pub/Sub

*   **Class-based Agents (Nodes/Flows):**
    *   Their `__init__` method should accept `AppServices` (which provides access to the event bus) and any other necessary `init_args` (such as an agent-specific `ToolRegistry` instance).
    *   During initialization or a dedicated setup phase, they must subscribe to relevant events on the bus:
        *   `AppInputEvent`: The handler for this event will contain the agent's core logic for processing user input. The agent is responsible for parsing this input itself.
        *   `AgentLifecycleEvent`: To manage its own setup when "activating" and cleanup when "deactivating".
*   **Composition Function-based Agents:**
    *   The composition function will accept `AppServices` and `init_args`.
    *   It must return an instantiated Node or Flow. This returned object should be internally configured to perform the necessary event subscriptions and handling as described for class-based agents.
*   **All Agents (General Behavior):**
    *   Publish `AgentOutputEvent` to the event bus to send messages/feedback to the user interface.
    *   Publish `RequestPromptEvent` if they require dedicated, single-line input from the user.
    *   Do *not* publish commands or attempt to register them with `app_core`.

## 6. Refactor `config_loader.py`

*   The `parse_agent_configs` function will be updated:
    *   It will iterate through the `agents` section of the raw YAML configuration.
    *   For each agent entry, it will use the `AgentResolver` service (from Item 2) to determine the target class or composition function and to resolve the full file path.
    *   It will populate the `AgentConfig` Pydantic model with this resolved information, along with `init_args` and other metadata.
    *   The collection of these populated `AgentConfig` objects will then be available to `app_core.py`.

## 7. Update `TerminalInteractionFlow` and I/O Handlers

*   **`TerminalOutputHandler` (in `pocket_commander/commands/terminal_io.py`):**
    *   Will subscribe to `AgentOutputEvent` from the event bus. Its handler will take the event's message and style and display it using `rich`.
*   **`request_dedicated_input` function (used by `prompt_func` in `AppServices`):**
    *   When called, it will generate a unique `correlation_id`.
    *   It will publish a `RequestPromptEvent` (including the `prompt_message`, `is_sensitive`, `correlation_id`, and a specific `response_event_type` like `f"prompt_response_{correlation_id}"`).
    *   It will then subscribe to this specific `response_event_type` (or a general `PromptResponseEvent` and filter by `correlation_id`) and `await` the corresponding `PromptResponseEvent` to get the user's input text.

## 8. Refactor Existing Agents (main, composer, tool-agent)

*   The current agent logic located in `pocket_commander/agents/` (e.g., `main_agent_logic.py`) will be refactored.
*   Each will become a separate Python file containing either:
    *   A Node or Flow class that inherits from the appropriate PocketFlow base and implements the event-driven interaction model described in Item 5.
    *   A flow composition function that returns such a configured Node/Flow.
*   These new agent files will be placed in a suitable location (e.g., a new top-level `core_agents/` directory, or within one of the `agent_discovery_folders`).
*   The [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml) file will be updated to load these refactored agents using the new configuration schema (Item 1).
*   These agents will be responsible for their own input parsing and will not register commands with the core application.

## 9. Update Documentation

*   **`cline_docs/`:**
    *   Update `systemPatterns.md` to describe the new agent discovery mechanism, the Pub/Sub architecture for agent interaction, and the removal of agent-defined commands from `app_core`.
    *   Update `techContext.md` to mention the new event bus and event types.
*   **[`docs/pocketflow-guides.md`](docs/pocketflow-guides.md):**
    *   Add a new section detailing how to create new agents:
        *   Writing agent logic as a PocketFlow Node or Flow class.
        *   Alternatively, using a flow composition function.
        *   How agents should interact with the event bus (subscribing to `AppInputEvent`, publishing `AgentOutputEvent`, etc.).
        *   How to configure these new agents in `pocket_commander.conf.yaml`, including specifying `path`, `class_name` (or relying on conventions), `composition_function_name`, and `init_args` (like `tool_names`).
        *   Explaining that agents parse their own input and do not register commands with the core application.

This plan provides a comprehensive approach to refactoring the agent system towards a more flexible, discoverable, and decoupled architecture.