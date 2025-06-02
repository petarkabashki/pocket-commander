# Pocket Commander

Pocket Commander is an extendable agentic AI workflow engine, built upon the **PocketFlow framework**. It serves as a robust foundation for developing and deploying custom agentic automation tools. Instead of being just a personal assistant, it provides the core infrastructure to create sophisticated AI agents capable of performing complex tasks by understanding natural language queries and leveraging a flexible tool-based architecture.

## Core Concepts

*   **Agentic AI Workflow Engine:** Pocket Commander orchestrates sequences of operations (workflows) carried out by AI agents.
*   **PocketFlow Framework:** Leverages the lightweight and powerful PocketFlow framework for defining and managing these workflows.
*   **Extensible Tooling:** Easily integrate custom tools to expand the capabilities of your AI agents.
*   **Foundation for Custom Automation:** Designed to be a starting point for building specialized agentic solutions tailored to specific needs.

## Features

*   **Natural Language Understanding:** Interprets user queries to trigger and guide agentic workflows.
*   **Modular Tool-Based Architecture:** Extensible functionality through a system of easily integrated tools.
*   **Asynchronous Operations:** Built with `asyncio` for efficient, non-blocking task execution, crucial for responsive AI agents.
*   **Interactive Terminal Interface:** Provides a user-friendly command-line experience using `prompt-toolkit` and `rich` for development, testing, and interaction.
*   **Configurable Agents:** Supports different operational agents, allowing for various agent configurations and behaviors.
*   **Workflow Management:** Utilizes PocketFlow to define, manage, and execute complex sequences of actions.

## Technologies Used

*   Python
*   PocketFlow
*   `asyncio`
*   `aiohttp`
*   `prompt-toolkit`
*   `rich`
*   `PyYAML`

## Getting Started

### Prerequisites

*   Python 3.8+
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

### Running the Application

To start the interactive terminal:
```bash
poetry run python -m pocket_commander.main
```

## Project Structure

The project follows a modular structure, aligned with PocketFlow principles:

*   `pocket_commander/nodes/`: Contains individual processing units (Nodes), the building blocks of PocketFlows.
*   `pocket_commander/flows/`: Defines PocketFlows, which are sequences or graphs of interconnected Nodes orchestrating agent behavior.
*   `pocket_commander/tools/`: Houses specific tools callable by agents within the workflows (e.g., `get_stock_price`).
*   `pocket_commander/agents/`: Implements different operational agents for the terminal interface, each potentially running a distinct master Flow.
*   `pocket_commander/utils/`: Contains shared utility modules and helper functions.
*   `pocket_commander/main.py`: Entry point for the application.
*   `pocket_commander/terminal_interface.py`: Core logic for the interactive terminal.
*   `pocket_commander.conf.yaml`: Configuration file for the application, including terminal agents and other settings.
*   `cline_docs/`: Contains documentation for Cline, the AI assistant working on this project, detailing its understanding of Pocket Commander.

## Contributing

Details on contributing to this project will be added soon.

## License

This project is licensed under the MIT License - see the LICENSE file for details (to be created).
