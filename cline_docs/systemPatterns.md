# System Patterns

## How the system is built
The system is built using Python, with a strong emphasis on asynchronous operations (`asyncio`). It is fundamentally an **agentic AI workflow engine** based on the **PocketFlow framework**.

## Key technical decisions
-   **PocketFlow Framework:** Adoption of PocketFlow for defining and managing agentic workflows. This involves using "Nodes" as individual processing units and "Flows" to orchestrate these nodes.
-   **Asynchronous Operations (`asyncio`):** Essential for building responsive and efficient AI agents that can handle multiple tasks or I/O-bound operations concurrently.
-   **Tool-Based Architecture:** Functionality is extended through modular, self-contained "tools" that agents can utilize within their workflows.
-   **Interactive Terminal Interface:** Using `prompt-toolkit` and `rich` for a developer-friendly CLI to interact with and test the system.

## Architecture patterns
-   **Agentic Workflow Engine:** The core pattern is an engine that executes predefined or dynamically generated workflows. These workflows consist of sequences of actions performed by AI agents.
-   **Event-Driven:** While not explicitly detailed as the primary pattern, the system likely incorporates event-driven principles, especially with `asyncio` and the way agents might react to inputs or tool outputs.
-   **Modular Design:** Enforced by PocketFlow's Node/Flow structure and the separation of tools, modes, and utilities.

## Folder Conventions

### `pocket_commander/nodes/`
This directory contains individual, reusable processing units called "Nodes," which are the fundamental building blocks of PocketFlows. Each node encapsulates a specific piece of logic or a step in an agentic workflow (e.g., fetching data, calling an LLM, processing user input). Nodes are designed to be composed into "Flows."

### `pocket_commander/flows/`
This directory defines "Flows," which are sequences or graphs of interconnected Nodes, as per the PocketFlow framework. Flows orchestrate the execution of multiple nodes to accomplish complex tasks or define the behavior of an AI agent. For instance, a flow might combine a query input node, an LLM processing node (which could decide to use a tool), a tool execution node, and an output node to create a sophisticated agentic interaction.

### `pocket_commander/utils/`
This directory houses utility modules and helper functions that provide shared functionality across different parts of the application, supporting the nodes, flows, and tools. This can include things like LLM communication helpers, prompt generation utilities, or any other common logic.

### `pocket_commander/tools/`
This directory is for modules that define specific "tools" that can be called by agents within a PocketFlow. Each tool should be a self-contained unit that performs a specific action (e.g., fetching financial data, interacting with an API, performing a web search).

### `pocket_commander/terminal_interface.py`
This file contains the core logic for the interactive terminal application. It utilizes `prompt-toolkit` for handling user input and `rich` for formatted output. The `TerminalApp` class manages mode configurations (each mode potentially running a different master PocketFlow) and dispatches user input.

### `pocket_commander/modes/`
This directory houses different "Modes" for the terminal interface. Each mode represents a distinct operational context for an agent or a set of agentic workflows, typically backed by a specific master PocketFlow.
-   Each subdirectory (e.g., `pocket_commander/modes/main/`) is a Python package representing a single mode.
-   The `__init__.py` of a mode package must export a `get_flow(mode_config, terminal_app_instance)` function, returning an instantiated PocketFlow object for that mode.
-   The flow itself (e.g., `main_flow.py`) defines the PocketFlow graph and how it processes terminal input.
-   Modes are configured in `pocket_commander.conf.yaml`.