from typing import Protocol, Dict, Any, Callable, Coroutine, List, Optional, TypeVar, TYPE_CHECKING, Type # Added Type
from dataclasses import dataclass, field
from enum import Enum

from pocket_commander.pocketflow.base import BaseNode # For type hinting Node/Flow classes
from pocket_commander.event_bus import ZeroMQEventBus # Moved import here

if TYPE_CHECKING: # Added this block
    from pocket_commander.tools.registry import ToolRegistry
    # ZeroMQEventBus import moved out

#%% For Command System
class AbstractCommandInput(Protocol):
    async def get_next_token(self, prompt: str = "") -> str: ...
    async def request_input(self, prompt: str = "") -> str: ...

class AbstractOutputHandler(Protocol):
    def print(self, message: Any = "", end: str = "\n", **kwargs: Any) -> None: ...
    def display_markdown(self, markdown_text: str) -> None: ...
    # Add more methods as needed, e.g., for tables, progress bars, etc.

PromptFunc = Callable[[str], Coroutine[Any, Any, str]]

@dataclass
class ParameterDefinition:
    name: str
    param_type: type
    description: Optional[str] = None
    is_required: bool = True # Changed from required to is_required for consistency
    default: Optional[Any] = None
    # For choices/enum like behavior, if type is string
    choices: Optional[List[str]] = None
    # For flags (boolean parameters that are true if present)
    is_flag: bool = False


@dataclass
class CommandDefinition:
    name: str
    description: str
    handler: Callable[..., Coroutine[Any, Any, None]] # The async function
    parameters: List[ParameterDefinition] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    category: str = "General"
    # Could add more metadata like usage examples, etc.

@dataclass
class CommandContext:
    """Holds the context for a command's execution."""
    command_input: AbstractCommandInput # Corrected from input to command_input
    output_handler: AbstractOutputHandler
    app_services: 'AppServices' # Forward reference
    # Potentially add current_agent_slug, etc.

#%% For Application Core / Agent Composition
@dataclass
class AppServices:
    """Container for shared application services."""
    raw_app_config: Dict[str, Any] # Should ideally be AppConfig type from config_loader
    output_handler: AbstractOutputHandler # This might become part of AgUIClient interaction
    prompt_func: PromptFunc # This might become part of AgUIClient interaction
    global_tool_registry: 'ToolRegistry'
    event_bus: ZeroMQEventBus # Changed from string literal to direct type
    current_log_level: str = "INFO"

    get_current_agent_slug: Optional[Callable[[], Optional[str]]] = None # Return Optional[str]
    get_available_agents: Optional[Callable[[], List[str]]] = None
    # get_all_command_definitions removed as agents don't register commands with app_core anymore
    request_agent_switch: Optional[Callable[[str], Coroutine[Any, Any, bool]]] = None
    _application_state_DO_NOT_USE_DIRECTLY: Optional[Dict[str, Any]] = field(default=None, repr=False)


# Old AgentConfig and related type aliases are removed as they are part of the system being replaced.
# AgentInputHandler = Callable[[str, CommandContext], Coroutine[Any, Any, None]]
# AgentCompositionFunction = Callable[[AppServices, 'AgentConfig'], Coroutine[Any, Any, tuple[AgentInputHandler, List[CommandDefinition]]]]

@dataclass
class AgentConfig:
    """
    Configuration for a single agent, resolved from YAML.
    Holds the direct target for instantiation (a class or a composition function)
    and its necessary arguments.
    """
    slug: str
    path: str  # Resolved absolute path to the agent's Python file
    description: Optional[str] = None
    
    # Stores the actual resolved class or function
    # One of these will be populated by the AgentResolver
    target_class: Optional[Type['BaseNode']] = None # Type hint with PocketFlow's BaseNode or a union
    target_composition_function: Optional[Callable[..., 'BaseNode']] = None # Or Callable[..., Coroutine[Any,Any,BaseNode]] if async

    is_class_target: bool = True # True if target_class is set, False if target_composition_function

    init_args: Dict[str, Any] = field(default_factory=dict) # Arguments for __init__ or composition_function
    
    # Store the original raw config for this agent for any other specific settings
    raw_config: Dict[str, Any] = field(default_factory=dict, repr=False)


#%% For PocketFlow Nodes (example, might need refinement)
T_Input = TypeVar("T_Input")
T_Output = TypeVar("T_Output")

class Node(Protocol[T_Input, T_Output]):
    async def process(self, item: T_Input, flow_state: Dict[str, Any]) -> T_Output:
        ...

class FlowStateEvent(Enum):
    NODE_START = "NODE_START"
    NODE_COMPLETE = "NODE_COMPLETE"
    NODE_ERROR = "NODE_ERROR"
    FLOW_START = "FLOW_START"
    FLOW_COMPLETE = "FLOW_COMPLETE"
    FLOW_ERROR = "FLOW_ERROR"

FlowEventListener = Callable[[FlowStateEvent, str, Dict[str, Any]], Coroutine[Any, Any, None]]

# ToolCallRequest and ToolCallResult are removed as they are superseded by ag_ui.types