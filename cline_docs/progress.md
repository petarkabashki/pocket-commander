# Progress

## What works
- The system has a basic structure for nodes and flows.
- The `tool_enabled_llm_node.py` file contains logic for LLM calls with tool support, including executing tools.
- Some tools like `get_weather`, `get_stock_price`, and `search_web` are defined.
- **NEW:** An interactive terminal interface (`pocket_commander/terminal_interface.py`) using `prompt-toolkit` and `rich`.
  - Supports built-in commands: `/help`, `/commands`, `/modes`, `/mode <name>`, `/exit`.
  - Modes are configurable in `pocket_commander.conf.yaml` under `terminal_modes`.
  - Modes are loaded dynamically from `pocket_commander/modes/<mode_name>/`.
  - Each mode (e.g., `main`, `composer`) has its own flow that handles user input.
  - Mode switching is functional.
  - Initial `main` and `composer` modes implemented with basic echo functionality.

## What's left to build
- Refactor utility functions from `pocket_commander/nodes/tool_enabled_llm_node.py` to a new file in the `utils` folder.
- Create/update documentation regarding the conventions for `nodes`, `flows`, and `utils` folders (partially addressed with `systemPatterns.md` updates for modes and terminal).
- Address the coroutine issue with the `get_stock_price` tool (as noted in `activeContext.md`).
- Develop more sophisticated flows for the `main` and `composer` modes beyond simple echo.
- Implement actual PocketFlow graph execution within the mode flows (currently placeholder `handle_input` methods).

## Progress status
- **COMPLETED:** Implemented the core terminal interface with mode support.
- Next steps could involve addressing the items in "What's left to build", particularly making the mode flows more functional by integrating actual PocketFlow logic.