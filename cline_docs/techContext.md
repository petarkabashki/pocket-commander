# Tech Context

## Technologies used
-   **Python:** The core programming language.
-   **PocketFlow:** The framework used for building the agentic AI workflow engine. Agents are PocketFlow `AsyncNode` or `Flow` implementations.
-   **`asyncio`:** For asynchronous programming, enabling efficient I/O-bound operations and responsive agents. Central to the event-driven architecture.
-   **`aiohttp`:** (Likely used for asynchronous HTTP requests by tools or core components).
-   **`prompt-toolkit`:** For creating the interactive terminal user interface.
-   **`rich`:** For styling and formatting output in the terminal.
-   **`PyYAML`:** For parsing YAML configuration files (e.g., [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1)).
-   **Pydantic:** Used for data validation and settings management, notably for `AgentConfig` ([`pocket_commander/types.py`](pocket_commander/types.py:1)) and event models ([`pocket_commander/events.py`](pocket_commander/events.py:1)).

## Key Modules & Components (New Agent System)
-   **Event Bus:** [`pocket_commander/event_bus.py`](pocket_commander/event_bus.py:1) - Contains the `AsyncEventBus` for Pub/Sub communication.
-   **Event Definitions:** [`pocket_commander/events.py`](pocket_commander/events.py:1) - Defines core Pydantic models for events like `AppInputEvent`, `AgentOutputEvent`, `AgentLifecycleEvent`.
-   **Agent Resolver:** [`pocket_commander/agent_resolver.py`](pocket_commander/agent_resolver.py:1) - Handles discovery and loading of agent code from the filesystem.
-   **Agent Configuration & Types:** [`pocket_commander/types.py`](pocket_commander/types.py:1) - Defines `AgentConfig` and other shared Pydantic types.
-   **Core Agent Implementations:** Located in `pocket_commander/core_agents/`
    -   [`pocket_commander/core_agents/main_agent.py`](pocket_commander/core_agents/main_agent.py:1)
    -   [`pocket_commander/core_agents/composer_agent.py`](pocket_commander/core_agents/composer_agent.py:1)
    -   [`pocket_commander/core_agents/tool_agent.py`](pocket_commander/core_agents/tool_agent.py:1)
-   **Application Core:** [`pocket_commander/app_core.py`](pocket_commander/app_core.py:1) - Manages application state, event bus integration, agent lifecycle, and input handling. Significantly refactored.
-   **Configuration Loader:** [`pocket_commander/config_loader.py`](pocket_commander/config_loader.py:1) - Parses [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1), including the new agent configurations. Significantly refactored.

## Development setup
-   **Poetry:** For dependency management and packaging.
-   **VSCode:** As the recommended Integrated Development Environment (IDE).
-   **Conda Environment:** The project is expected to run within a Conda environment, typically named `py312`.

### Running the Application
To run Pocket Commander:
1.  Activate the Conda environment: `conda activate py312`
2.  From the project root directory (`pocket-commander/pocket_commander`), run the application as a module:
    `python -m pocket_commander.main`
    (Ensure `conda activate py312` is run first if not already active in the terminal session)

## Technical constraints
-   **Asynchronous by Design:** The system must leverage `asyncio` for all potentially blocking operations. The event bus and agent interactions are fully asynchronous.
-   **PocketFlow Adherence:** Development of agents should follow the patterns and principles of the PocketFlow framework (Nodes, Flows).
-   **Event-Driven Communication:** Interaction between agents, and between agents and the core application, primarily occurs via the `AsyncEventBus`.
-   **Modular and Discoverable Agents:** Agents should be self-contained modules, discoverable and configurable via YAML.
-   **Extensibility:** The architecture must support easy addition of new tools, agents (as PocketFlow Nodes/Flows), and event types.