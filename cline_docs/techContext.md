# Tech Context

## Technologies used
-   **Python:** The core programming language.
-   **PocketFlow:** The framework used for building the agentic AI workflow engine. Agents are PocketFlow `AsyncNode` or `Flow` implementations.
-   **`asyncio`:** For asynchronous programming, enabling efficient I/O-bound operations and responsive agents. Central to the event-driven architecture.
-   **`aiohttp`:** (Likely used for asynchronous HTTP requests by tools or core components).
-   **`prompt-toolkit`:** For creating the interactive terminal user interface, used by `TerminalAgUIClient`.
-   **`rich`:** For styling and formatting output in the terminal, used by `TerminalAgUIClient`.
-   **`PyYAML`:** For parsing YAML configuration files (e.g., [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1)).
-   **Pydantic:** Used for data validation and settings management, notably for `AgentConfig` ([`pocket_commander/types.py`](pocket_commander/types.py:1)), event models ([`pocket_commander/events.py`](pocket_commander/events.py:1) and [`pocket_commander/ag_ui/events.py`](pocket_commander/ag_ui/events.py:1)), and `ag_ui` types ([`pocket_commander/ag_ui/types.py`](pocket_commander/ag_ui/types.py:1)).

## Key Modules & Components
-   **Event Bus:** [`pocket_commander/event_bus.py`](pocket_commander/event_bus.py:1) - Contains the `AsyncEventBus`.
-   **Event Definitions:**
    -   [`pocket_commander/events.py`](pocket_commander/events.py:1): Defines core Pydantic models for application events like `AppInputEvent`, `AgentLifecycleEvent`, and re-exports `ag_ui.events`.
    -   [`pocket_commander/ag_ui/events.py`](pocket_commander/ag_ui/events.py:1): Defines the Agent User Interaction (ag_ui) event protocol.
-   **UI Client Architecture:**
    -   [`pocket_commander/ag_ui/client.py`](pocket_commander/ag_ui/client.py:1): Defines `AbstractAgUIClient`.
    -   [`pocket_commander/ag_ui/terminal_client.py`](pocket_commander/ag_ui/terminal_client.py:1): Implements `TerminalAgUIClient` for terminal-based interaction.
-   **Agent Resolver:** [`pocket_commander/agent_resolver.py`](pocket_commander/agent_resolver.py:1) - Handles discovery and loading of agent code.
-   **Agent Configuration & Types:**
    -   [`pocket_commander/types.py`](pocket_commander/types.py:1): Defines `AgentConfig` and other shared Pydantic types.
    -   [`pocket_commander/ag_ui/types.py`](pocket_commander/ag_ui/types.py:1): Defines types for the `ag_ui` protocol (e.g., `Message`, `ToolCall`).
-   **Core Agent Implementations:** Located in `pocket_commander/core_agents/`
    -   [`pocket_commander/core_agents/main_agent.py`](pocket_commander/core_agents/main_agent.py:1)
    -   [`pocket_commander/core_agents/composer_agent.py`](pocket_commander/core_agents/composer_agent.py:1)
    -   [`pocket_commander/core_agents/tool_agent.py`](pocket_commander/core_agents/tool_agent.py:1)
-   **Application Core:** [`pocket_commander/app_core.py`](pocket_commander/app_core.py:1) - Manages application state, event bus integration, agent lifecycle, global command handling (via `AppInputEvent`), and dispatch to agents.
-   **Configuration Loader:** [`pocket_commander/config_loader.py`](pocket_commander/config_loader.py:1) - Parses [`pocket_commander.conf.yaml`](pocket_commander.conf.yaml:1).
-   **Main Entry Point:** [`pocket_commander/main.py`](pocket_commander/main.py:1) - Initializes `AppCore`, `TerminalAgUIClient`, and starts the application.

## Development setup
-   **Poetry:** For dependency management and packaging.
-   **VSCode:** As the recommended Integrated Development Environment (IDE).
-   **Conda Environment:** The project is expected to run within a Conda environment, typically named `py312`.

### Running the Application
1.  Activate the Conda environment: `conda activate py312`
2.  From the project root directory (`pocket-commander/pocket_commander`), run the application as a module:
    `python -m pocket_commander.main`
    (Ensure `conda activate py312` is run first if not already active in the terminal session)

## Technical constraints
-   **Asynchronous by Design:** The system must leverage `asyncio`.
-   **PocketFlow Adherence:** Development of agents should follow PocketFlow patterns.
-   **Event-Driven Communication:** All major interactions (UI to core, core to agent, agent to UI) occur via the `AsyncEventBus`. UI interactions specifically use `AppInputEvent` (UI -> Core) and the `ag_ui.events` protocol (Core/Agent -> UI).
-   **Modular and Discoverable Agents:** Agents are self-contained and configurable.
-   **Abstracted UI:** The `AbstractAgUIClient` allows for different UI implementations.
-   **Extensibility:** The architecture must support easy addition of new tools, agents, and event types.