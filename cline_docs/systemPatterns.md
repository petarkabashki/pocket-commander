# System Patterns

## How the system is built
The system is built using Python with a focus on asynchronous operations.

## Key technical decisions
Key technical decisions include using `asyncio` for concurrency and a tool-based architecture for extending functionality.

## Architecture patterns
The architecture pattern is event-driven.

## Folder Conventions

### `pocket_commander/nodes/`
This directory contains individual, reusable processing units called "Nodes". Each node typically encapsulates a specific piece of logic or a step in a larger workflow. For example, a node might be responsible for fetching data, calling an LLM, or processing user input. Nodes are designed to be composed into "Flows".

### `pocket_commander/flows/`
This directory defines "Flows", which are sequences or graphs of interconnected Nodes. Flows orchestrate the execution of multiple nodes to accomplish more complex tasks. For instance, a flow might combine a query input node, an LLM processing node, and an output node to create a conversational agent.

### `pocket_commander/utils/`
This directory houses utility modules and helper functions that provide shared functionality across different parts of the application. This can include things like LLM communication helpers (e.g., `call_llm.py`, `tool_llm_utils.py`), prompt generation utilities (`prompt_utils.py`), or any other common logic that doesn't fit neatly into a specific node or flow but is used by them. Keeping utilities here promotes code reuse and separation of concerns.

### `pocket_commander/tools/`
This directory is for modules that define specific "tools" that can be called by the LLM or other parts of the system. Each tool should be a self-contained unit that performs a specific action, like fetching weather data, getting stock prices, or searching the web.
### `pocket_commander/terminal_interface.py`
This file contains the core logic for the interactive terminal application. It utilizes `prompt-toolkit` for handling user input, command parsing, and session management, and `rich` for formatted output. The `TerminalApp` class within this file is responsible for loading mode configurations, managing mode switching, and dispatching user input to either built-in commands or the active mode's flow.

### `pocket_commander/modes/`
This directory houses different "Modes" for the terminal interface. Each mode represents a distinct operational context, typically backed by a specific PocketFlow.
- Each subdirectory within `pocket_commander/modes/` (e.g., `pocket_commander/modes/main/`) is a Python package representing a single mode.
- The `__init__.py` file of a mode package (e.g., `pocket_commander/modes/main/__init__.py`) must export a `get_flow(mode_config, terminal_app_instance)` function. This function is responsible for returning an instantiated flow object that can handle input for that mode.
- The flow itself (e.g., `main_flow.py`) defines the PocketFlow graph (nodes, connections, etc.) and implements a method (e.g., `async def handle_input(self, user_input: str)`) to process terminal input and use `terminal_app_instance.display_output()` for sending messages back to the user.
- Modes are configured in `pocket_commander.conf.yaml` under the `terminal_modes` key, specifying their `flow_module` path, an optional `llm_profile`, and a `description`.