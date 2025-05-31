# Tech Context

## Technologies used
-   **Python:** The core programming language.
-   **PocketFlow:** The framework used for building the agentic AI workflow engine. This dictates the use of Nodes and Flows for structuring agent logic.
-   **`asyncio`:** For asynchronous programming, enabling efficient I/O-bound operations and responsive agents.
-   **`aiohttp`:** (Likely used for asynchronous HTTP requests by tools or core components, though not explicitly stated as a primary framework component).
-   **`prompt-toolkit`:** For creating the interactive terminal user interface.
-   **`rich`:** For styling and formatting output in the terminal.
-   **`PyYAML`:** For parsing YAML configuration files (e.g., `pocket_commander.conf.yaml`).

## Development setup
-   **Poetry:** For dependency management and packaging.
-   **VSCode:** As the recommended Integrated Development Environment (IDE).

## Technical constraints
-   **Asynchronous by Design:** The system must leverage `asyncio` for all potentially blocking operations to maintain responsiveness, a key requirement for agentic systems.
-   **PocketFlow Adherence:** Development should follow the patterns and principles of the PocketFlow framework (Nodes, Flows).
-   **Modular and Self-Contained Tools:** Tools integrated into the system should be designed as independent, reusable modules.
-   **Extensibility:** The architecture must support easy addition of new tools, flows, and agent capabilities.