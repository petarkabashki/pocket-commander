# Plan v8.3: Fully Functional Composition for Application Core and Agents

This plan outlines a purely functional composition architecture for Pocket Commander, encompassing both the application core and individual agents. It emphasizes clear I/O abstractions, declarative command registration, and state management within closures.

## Core Principles

1.  **Centralized I/O Initialization**:
    *   `TerminalInteractionFlow` is instantiated in `main.py`. It is the primary source for `output_handler: AbstractOutputHandler` and `prompt_func: PromptFunc`.
2.  **`AppServices` Container**:
    *   A simple data structure (e.g., `typing.TypedDict` or `dataclasses.dataclass`) to pass essential services: `output_handler`, `prompt_func`, `raw_app_config` (loaded from YAML), and potentially a shared logger.
3.  **Command Definition**:
    *   `CommandDefinition` objects store metadata for each command: `name`, `description`, the `async` command function itself, `parameters: List[ParameterDefinition]`, and `aliases`. This structure is used for both global and agent-specific commands.
4.  **Agent Composition**:
    *   Each agent is defined by a "agent composition function" (e.g., `create_main_agent_logic` located in a file like `pocket_commander/agents/main_agent_logic.py`).
    *   This function:
        *   Receives `agent_config: Dict` (specific to that agent, from the main app config) and `app_services: AppServices`.
        *   Defines the agent's list of `CommandDefinition`s.
        *   Defines a "non-command processor function" (an `async` function) for that agent.
        *   Returns a tuple: `(agent_input_handler_func: Callable, command_definitions: List[CommandDefinition])`.
            *   `agent_input_handler_func(raw_input_str: str, command_input: AbstractCommandInput, app_services_for_agent: AppServices)`: An `async` function that processes input *for this specific agent*. It uses the provided `app_services_for_agent` to build `CommandContext` for its commands or to pass to its non-command processor.
5.  **Application Core Composition (`create_application_core`)**:
    *   This is the top-level composition function, called once from `main.py`.
    *   It's defined in a new file, e.g., `pocket_commander/app_core.py`.
    *   Receives `initial_app_services: AppServices`.
    *   Manages an `application_state` dictionary (mutable, captured in a closure). This state includes:
        *   `app_services: AppServices` (the services passed in, including `raw_app_config`).
        *   `global_commands: Dict[str, CommandDefinition]`.
        *   `active_agent_name: Optional[str]`.
        *   `active_agent_handler: Optional[Callable]` (the `agent_input_handler_func` for the current agent).
        *   `active_agent_commands: List[CommandDefinition]`.
    *   Defines global command functions (e.g., `/exit`, `/help`, `/agents`, `/agent <name>`).
        *   The `/agent <name>` command's function will call a helper function (also within the `create_application_core` closure) to manage agent switching. This helper will:
            *   Use `application_state['app_services']['raw_app_config']` to find the target agent's configuration and module path.
            *   Dynamically import and call the target agent's composition function (passing `agent_config` from `raw_app_config` and `application_state['app_services']`).
            *   Update `application_state['active_agent_handler']`, `application_state['active_agent_commands']`, and `application_state['active_agent_name']`.
    *   Populates `application_state['global_commands']` with `CommandDefinition`s for these global commands.
    *   Attempts to load the default initial agent using the agent switching helper.
    *   Returns a single `async` function: `top_level_app_input_handler(raw_input_str: str, command_input: AbstractCommandInput)`. This handler operates on the `application_state` (which is in its closure).
6.  **`top_level_app_input_handler`**:
    *   This is the main entry point for each piece of user input, called by `TerminalInteractionFlow`.
    *   It uses the `application_state` (from its closure).
    *   It first tries to match and execute a global command from `application_state['global_commands']`.
        *   Global commands receive a `CommandContext` built using `application_state['app_services']`.
    *   If no global command matches and `application_state['active_agent_handler']` exists, it calls:
        `await application_state['active_agent_handler'](raw_input_str, command_input, application_state['app_services'])`.
7.  **Main Application Loop (`main.py`)**:
    *   Initializes `TerminalInteractionFlow`.
    *   Loads the raw application configuration (e.g., from `pocket_commander.conf.yaml`).
    *   Creates the initial `app_services` instance (with `output_handler` and `prompt_func` from `TerminalInteractionFlow`, and the loaded `raw_app_config`).
    *   Calls `top_level_input_processor = create_application_core(app_services)`.
    *   `TerminalInteractionFlow`'s main input loop calls this `top_level_input_processor` for each user input.

## Detailed Plan Phases

### Phase 1: Define Core Data Structures and I/O Abstractions
1.  **`AbstractCommandInput`** (`pocket_commander/commands/io.py`):
    *   Ensure methods: `get_command_word() -> Optional[str]`, `get_remaining_input() -> str`.
    *   Consider `get_arguments_as_dict() -> Dict[str, Any]` or similar for structured argument access if needed by the parser.
2.  **`AbstractOutputHandler`** (`pocket_commander/commands/io.py`):
    *   Verify methods: `send_message`, `send_error`, `send_data`.
3.  **`PromptFunc` Type Definition** (`pocket_commander/commands/io.py`):
    *   `from typing import Callable, Awaitable, Optional, Any; PromptFunc = Callable[[str, Optional[str]], Awaitable[str]]`.
4.  **`ParameterDefinition` and `CommandDefinition`** (`pocket_commander/commands/definition.py`):
    *   Define using Pydantic or dataclasses (see Plan v8.1 for structure).
5.  **`CommandContext`** (`pocket_commander/commands/core.py`):
    *   Ensure constructor accepts: `input: AbstractCommandInput`, `output: AbstractOutputHandler`, `prompt_func: PromptFunc`, `agent_name: str`, `terminal_app: Any` (the `app_services` or a specific part of it if preferred for context), and `loop: asyncio.AbstractEventLoop`.
6.  **`AppServices` TypedDict/Dataclass**:
    *   Define in a common types location (e.g., `pocket_commander/types.py`):
      ```python
      from typing import TypedDict, Callable, Awaitable, Optional, Any, Dict
      from .commands.io import AbstractOutputHandler, PromptFunc
      # Potentially a Logger type from logging module

      class AppServices(TypedDict):
          output_handler: AbstractOutputHandler
          prompt_func: PromptFunc
          raw_app_config: Dict[str, Any]
          # logger: Logger 
      ```

### Phase 2: Implement Agent Composition Logic
7.  **Agent Composition Function Structure**:
    *   For each agent, create a module (e.g., `pocket_commander/agents/main_agent_logic.py`).
    *   This module contains:
        *   Standalone `async` command functions.
        *   An `async` non-command processor function.
        *   The agent composition function (e.g., `create_main_agent_logic`) that accepts `(agent_config: Dict, app_services: AppServices)` and returns `(agent_input_handler_func, List[CommandDefinition])`.
        *   The returned `agent_input_handler_func` takes `(raw_input_str, command_input, app_services_for_agent)` and orchestrates command/non-command logic for that agent.
8.  **Argument Parsing Utility** (`pocket_commander/commands/parser.py`):
    *   Implement `async def parse_arguments(command_input: AbstractCommandInput, param_definitions: List[ParameterDefinition]) -> Dict[str, Any]`. Handles type casting, defaults, required checks, and raises errors on failure.

### Phase 3: Implement Application Core Composition Logic
9.  **Create `pocket_commander/app_core.py`**:
    *   Define `create_application_core(initial_app_services: AppServices) -> Callable[[str, AbstractCommandInput], Awaitable[Any]]`.
    *   Implement the logic described in "Core Principles" point #5, including:
        *   `application_state` dictionary (closure).
        *   Internal `_switch_to_agent` helper function.
        *   Definitions for global command functions.
        *   Population of `application_state['global_commands']`.
        *   Initial agent loading.
        *   Definition and return of `top_level_app_input_handler`.

### Phase 4: Update Main Application Entry Point and I/O Flow
10. **Update `pocket_commander/main.py`**:
    *   Follow "Core Principles" point #7: Instantiate `TerminalInteractionFlow`, load config, create `app_services`, call `create_application_core`, and pass the returned handler to `TerminalInteractionFlow`.
11. **Update `TerminalInteractionFlow`** (`pocket_commander/flows/terminal_interaction_flow.py`):
    *   Constructor: `__init__(self, process_input_callback: Callable[[str, AbstractCommandInput], Awaitable[Any]])`.
    *   Main loop: `await self.process_input_callback(user_input_str, command_input_obj)`.
    *   Implement `async def request_dedicated_input(self, prompt_message: str, style: Optional[str] = None) -> str:` for the `prompt_func`.

### Phase 5: Documentation and Review
12. **Update Documentation**:
    *   Thoroughly document the fully functional architecture: `AppServices`, `create_application_core`, `application_state` management, agent composition functions, and the data flow.
    *   Update `cline_docs/systemPatterns.md`, `cline_docs/techContext.md`, and `cline_docs/pocketflow-guides.md`.
13. **Review and Test**:
    *   Extensive testing of all components: global commands, agent switching, agent-specific commands, non-command processing, argument parsing, interactive prompts, and error handling.

## Mermaid Diagram (v8.3 - Fully Functional Composition)

```mermaid
graph TD
    UserRawInput[User Raw Input] --> TIF[TerminalInteractionFlow];
    TIF -- Creates --> ACI_Instance[AbstractCommandInput];
    TIF -- Provides --> AOH_Instance[AbstractOutputHandler];
    TIF -- Provides --> PF_Instance[PromptFunc];
    
    subgraph main.py
        direction LR
        LoadConfig[Load pocket_commander.conf.yaml] --> RawAppConfig;
        TIF_Instance[TIF Instance] --> AOH_Instance_Ref["AOH from TIF"];
        TIF_Instance --> PF_Instance_Ref["PF from TIF"];
        RawAppConfig & AOH_Instance_Ref & PF_Instance_Ref --> AppSvcInstance[Initial AppServices Instance];
        AppSvcInstance --> CallCreateAppCore["create_application_core(AppSvcInstance)"];
        CallCreateAppCore -- Returns --> TopLevelHandlerFunc["top_level_app_input_handler (captures app_state)"];
        TopLevelHandlerFunc --> TIF_Init["TIF initialized with TopLevelHandlerFunc"];
    end

    TIF -- For each input --> CallTopLevelHandler["TopLevelHandlerFunc(raw_input, ACI_Instance)"];

    subgraph "app_core.py: create_application_core (Closure)"
        AppState["application_state (dictionary in closure) <br> - app_services <br> - global_commands <br> - active_agent_handler <br> - active_agent_commands <br> - active_agent_name"];
        DefineGlobalCmds["Define Global Command Functions (e.g., _cmd_agent)"];
        DefineSwitchAgent["Define _switch_to_agent(agent_name, app_state_ref) helper <br> (Imports & calls Agent Composition Func, updates app_state_ref)"];
        DefineGlobalCmds --> PopulateGlobalCmds["Populate AppState.global_commands with CommandDefinitions"];
        InitialAgentLoad["Load Default Agent using _switch_to_agent"];
        
        ReturnHandler["Return top_level_app_input_handler"];
        AppState -.-> ReturnHandler;
        PopulateGlobalCmds -.-> ReturnHandler;
        InitialAgentLoad -.-> ReturnHandler;
    end
    
    subgraph "top_level_app_input_handler Logic (Uses AppState from Closure)"
        CallTopLevelHandler --> TryGlobalCmd["Try Global Command from AppState.global_commands"];
        TryGlobalCmd -- Match --> ExecGlobalCmd["Execute Global Command Func (ctx uses AppState.app_services)"];
        ExecGlobalCmd -- (e.g. /agent) --> CallSwitchAgent["Call _switch_to_agent (updates AppState)"];
        TryGlobalCmd -- No Match & AppState.active_agent_handler exists --> CallActiveAgentHandler["AppState.active_agent_handler(raw, ACI, AppState.app_services)"];
        ExecGlobalCmd --> OutputResult1[Result];
        CallActiveAgentHandler --> OutputResult2[Result];
    end

    subgraph "Example Agent: main_agent_logic.py"
        AgentCompFunc["create_main_agent_logic(agent_cfg, app_services)"];
        AgentCompFunc -- Defines --> MainCmdDefs["List[CommandDefinition] for Main Agent"];
        AgentCompFunc -- Defines --> MainNonCmdProcessor["_main_non_command_processor_func"];
        AgentCompFunc -- Returns --> MainAgentHandlerAndDefs["(main_agent_input_handler, MainCmdDefs)"];
        
        subgraph "main_agent_input_handler Logic"
            CallActiveAgentHandler -- If Main Agent Active --> MainAgentInputHandlerInternal["main_agent_input_handler(raw, ACI, app_services)"];
            MainAgentInputHandlerInternal -- Uses --> MainCmdDefs_Lookup["Lookup in MainCmdDefs map"];
            MainCmdDefs_Lookup -- Match --> ParseMainCmdArgs["Parse Args for Main Command"];
            ParseMainCmdArgs --> ExecMainCmd["Execute Main Command Func (ctx uses app_services)"];
            MainCmdDefs_Lookup -- No Match --> ExecMainNonCmd["Execute _main_non_command_processor(..., app_services)"];
        end
    end
    
    _switch_to_agent -.-> AgentCompFunc;

    style TIF fill:#f9f,stroke:#333,stroke-width:2px;
    style AppSvcInstance fill:#ccf,stroke:#333,stroke-width:1px;
    style CallCreateAppCore fill:#cfc,stroke:#333,stroke-width:1px;
    style AppState fill:#fcf,stroke:#333,stroke-width:1px;
    style AgentCompFunc fill:#ffc,stroke:#333,stroke-width:1px;
```

This plan (v8.3) provides a highly decoupled, functional, and testable architecture for Pocket Commander's core logic and agent handling.