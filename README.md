# Pocket Commander

Pocket Commander is an **extendable agentic AI workflow engine**, built upon the **PocketFlow framework**. Its primary purpose is to provide a solid and flexible foundation for developers to **create and deploy custom agentic automation tools**. It moves beyond the concept of a simple personal assistant to become a platform for building sophisticated AI agents.

## Core Concepts

*   **Agentic AI Workflow Engine:** Pocket Commander orchestrates complex, multi-step tasks performed by AI agents.
*   **PocketFlow Framework:** Leverages the PocketFlow framework to define, manage, and execute these workflows using a system of interconnected "Nodes" (processing units) and "Flows" (sequences of Nodes).
*   **Extensible Tooling:** Features a flexible tool-based architecture, allowing easy integration of new capabilities (e.g., data fetching, API interaction, custom logic).
*   **Foundation for Custom Automation:** Designed as a starting point for building specialized AI-powered automation solutions without needing to build core agentic infrastructure from scratch.

## Features

*   **Natural Language Understanding:** Interprets user queries to initiate and guide agentic workflows.
*   **PocketFlow Integration:** Deeply utilizes the PocketFlow framework for defining, managing, and executing workflows.
*   **Modular Tool-Based Architecture:** Allows for easy integration and extension of agent capabilities through custom tools.
*   **Asynchronous Operations:** Built with `asyncio` for efficient, non-blocking task execution, enabling responsive AI agents.
*   **Interactive Terminal Interface:** Provides a user-friendly command-line experience for development, testing, and direct interaction with agents and their workflows.
*   **Configurable Agents & Workflows:** Supports configuration via YAML files, allowing users to define agents, toolsets, and agent behaviors.
*   **Clear and Modular Architecture:** Designed to be easy to understand and extend, facilitating the creation of custom agentic tools.

## Technologies Used

*   Python
*   PocketFlow
*   `asyncio`
*   `aiohttp` (if still used, to be verified)
*   `prompt-toolkit`
*   `rich`
*   `PyYAML`
*   ZeroMQ (for event bus, based on file names like `zeromq_event_bus.py`)

## Getting Started

### Prerequisites

*   Python 3.8+ (Verify specific version if possible, e.g., py312 from custom instructions)
*   Poetry (for dependency management)

### Installation

1.  Clone the repository:
    ```bash
    git clone <repository-url>
    cd pocket-commander
    ```
2.  Install dependencies using Poetry:
    ```bash
    poetry install
    ```
    (As per custom instructions, consider `conda activate py312` if applicable before poetry commands)

### Running the Application

To start the interactive terminal:
```bash
poetry run python -m pocket_commander.main
```
(As per custom instructions, consider `conda activate py312` first: `conda activate py312 && poetry run python -m pocket_commander.main`)

## Project Structure

The project follows a modular structure, aligned with PocketFlow principles:

*   `pocket_commander/nodes/`: Contains individual processing units (Nodes), the building blocks of PocketFlows (e.g., `initial_query_node.py`, `tool_enabled_llm_node.py`).
*   `pocket_commander/flows/`: Defines PocketFlows, which are sequences or graphs of interconnected Nodes orchestrating agent behavior (e.g., `tool_flow.py`).
*   `pocket_commander/tools/`: Houses specific tools callable by agents within the workflows (e.g., `fetch_tool.py`, `greet_tool.py`).
*   `pocket_commander/agents/`: Implements different operational agents and their logic (e.g., `composer/composer_flow.py`, `main/main_agent_logic.py`).
*   `pocket_commander/core_agents/`: Contains core agent implementations (e.g., `main_agent.py`, `composer_agent.py`).
*   `pocket_commander/utils/`: Contains shared utility modules and helper functions (e.g., `call_llm.py`, `logging_utils.py`).
*   `pocket_commander/ag_ui/`: Contains components for the agent user interface, including the terminal client (e.g., `terminal_client.py`).
*   `pocket_commander/commands/`: Manages command definitions, parsing, and I/O for the terminal interface.
*   `pocket_commander/pocketflow/`: Core PocketFlow framework components (e.g., `async_flow_manager.py`, `base.py`).
*   `pocket_commander/event_bus.py`, `pocket_commander/zeromq_event_bus.py`: Implementation of the event bus system.
*   `pocket_commander/main.py`: Entry point for the application.
*   `pocket_commander.conf.yaml`: Configuration file for the application.
*   `cline_docs/`: Contains documentation for Cline, the AI assistant working on this project, detailing its understanding of Pocket Commander.
*   `docs/`: Contains design documents, plans, and guides related to the project.

## Contributing

Details on contributing to this project will be added soon.

## License

This project is licensed under the MIT License - see the LICENSE file for details (to be created).
