# Tech Context

## Technologies used
-   **Python:** The core programming language.
-   **PocketFlow:** The framework used for building the agentic AI workflow engine. This dictates the use of Nodes and Flows for structuring agent logic.
-   **`asyncio`:** For asynchronous programming, enabling efficient I/O-bound operations and responsive agents.
-   **`aiohttp`:** (Likely used for asynchronous HTTP requests by tools or core components, though not explicitly stated as a primary framework component).
-   **`prompt-toolkit`:** For creating the interactive terminal user interface.
-   **`rich`:** For styling and formatting output in the terminal.
-   **`PyYAML`:** For parsing YAML configuration files (e.g., `pocket_commander.conf.yaml`).
-   **Internal Command System (`pocket_commander.commands`):**
    -   `CommandMetadata` and `CommandContext` for command definition and execution.
    -   `@command` decorator for registering commands within modes.
    -   Abstract I/O (`AbstractCommandInput`, `AbstractOutputHandler`) and terminal-specific implementations (`TerminalCommandInput`, `TerminalOutputHandler`) for flexible command interaction.

## Development setup
-   **Poetry:** For dependency management and packaging.
-   **VSCode:** As the recommended Integrated Development Environment (IDE).
-   **Conda Environment:** The project is expected to run within a Conda environment, typically named `py312`.

### Running the Application
To run Pocket Commander:
1.  Activate the Conda environment: `conda activate py312`
2.  From the project root directory (`pocket-commander/pocket_commander`), run the application as a module using a single command line:
    `conda activate py312 && python -m pocket_commander.main`

## Technical constraints
-   **Asynchronous by Design:** The system must leverage `asyncio` for all potentially blocking operations to maintain responsiveness. This extends to mode-specific commands, which must be `async def`.
-   **PocketFlow Adherence:** Development should follow the patterns and principles of the PocketFlow framework (Nodes, Flows) where applicable. The new command system is designed to integrate with mode flows.
-   **Modular and Self-Contained Tools & Commands:** Tools and mode-specific commands should be designed as independent, reusable modules/functions where possible.
-   **Extensibility:** The architecture must support easy addition of new tools, flows, agent capabilities, and mode-specific commands. The command system's abstracted I/O aims to facilitate this.