## Plan: Implementing the `@tool` Annotation System

**I. Introduction & Goals**

This plan outlines the development of a new `@tool` annotation system for Pocket Commander. The primary goals are:

1.  **Provide Structured Metadata for LLMs:** Generate detailed descriptions of tools, including their purpose, parameters (name, type, description, required/optional status), suitable for LLM consumption.
2.  **Automate Tool Registration:** Simplify the process of making tools available to the system.
3.  **Flexible Parameter Definition:** Infer tool parameters from Python type hints and docstrings, while allowing for explicit overrides via decorator arguments.
4.  **Combined Discovery Mechanism:** Support both explicit registration of tools and automatic scanning of designated directories, with explicit registration taking precedence.

This system will enhance the ability of LLM-driven agents within Pocket Commander to understand and utilize available tools effectively.

**II. Core Components**

We will create the following key components:

*   **A. `ToolParameterDefinition`:** A data structure (likely a Pydantic model or dataclass) to hold metadata for a single tool parameter.
*   **B. `ToolDefinition`:** A data structure to hold all metadata for a tool, including its name, description, the callable function, and a list of `ToolParameterDefinition` objects.
*   **C. `@tool` Decorator:** The Python decorator that will be applied to tool functions to gather metadata and mark them for registration.
*   **D. `ToolRegistry`:** A central class or module responsible for storing, managing, discovering, and providing access to registered `ToolDefinition` objects.

**III. Detailed Implementation Plan**

**A. `ToolParameterDefinition` Data Structure**

*   **Location:** `pocket_commander/tools/definition.py` (new file)
*   **Structure:**
    ```python
    from typing import Any, Optional, Type
    from pydantic import BaseModel, Field

    class ToolParameterDefinition(BaseModel):
        name: str
        description: str
        param_type: Type[Any] # Store the actual Python type
        type_str: str # String representation for LLM (e.g., "string", "integer", "boolean")
        is_required: bool
        default_value: Optional[Any] = None # If a default is provided
    ```

**B. `ToolDefinition` Data Structure**

*   **Location:** `pocket_commander/tools/definition.py`
*   **Structure:**
    ```python
    from typing import Callable, List, Any, Dict
    from pydantic import BaseModel

    class ToolDefinition(BaseModel):
        name: str
        description: str
        func: Callable[..., Any] # The actual async tool function
        parameters: List[ToolParameterDefinition]
        # Optional: for richer LLM schema generation
        # parameters_schema: Dict[str, Any] = Field(default_factory=dict) 

        class Config:
            arbitrary_types_allowed = True # To allow Callable
    ```

**C. `@tool` Decorator Logic**

*   **Location:** `pocket_commander/tools/decorators.py` (new file, or could augment existing if preferred, but new is cleaner)
*   **1. Signature and Basic Structure:**
    ```python
    # pocket_commander/tools/decorators.py
    import asyncio
    import functools
    import inspect
    from typing import Callable, Optional, List, Dict, Any, Type, Union # Added Union
    from pocket_commander.tools.definition import ToolDefinition, ToolParameterDefinition
    # Placeholder for a docstring parser utility
    # from pocket_commander.utils.docstring_parser import parse_docstring 

    def tool(
        name: Optional[str] = None,
        description: Optional[str] = None,
        param_descriptions: Optional[Dict[str, str]] = None,
        # Potentially add more overrides if needed, e.g., param_types_override
    ):
        """
        Decorator to mark an async function as a tool, extract its metadata,
        and prepare it for registration.
        """
        _param_descriptions = param_descriptions or {}

        def decorator(func: Callable[..., Any]):
            if not asyncio.iscoroutinefunction(func):
                raise TypeError(
                    f"Tool '{func.__name__}' must be an async function (defined with 'async def')."
                )

            actual_name = name or func.__name__
            
            # --- Metadata Extraction Logic (detailed next) ---
            parsed_docstring = {} # Replace with actual parsing
            # Example: parsed_docstring = parse_docstring(inspect.getdoc(func))
            
            tool_desc = description or parsed_docstring.get("summary", f"Tool: {actual_name}") 
            
            sig = inspect.signature(func)
            parameters_defs = []

            for param_name, param_obj in sig.parameters.items():
                param_type_actual = param_obj.annotation if param_obj.annotation != inspect.Parameter.empty else Any
                
                type_str_map = {
                    str: "string",
                    int: "integer",
                    float: "number",
                    bool: "boolean",
                    list: "array",
                    dict: "object",
                }
                param_type_str = type_str_map.get(param_type_actual, "any")
                if hasattr(param_type_actual, '__origin__') and param_type_actual.__origin__ is list:
                    param_type_str = "array" 
                elif hasattr(param_type_actual, '__origin__') and param_type_actual.__origin__ is dict:
                    param_type_str = "object"

                param_desc = _param_descriptions.get(param_name, "") 
                # if not param_desc and "params" in parsed_docstring:
                #    param_desc = parsed_docstring["params"].get(param_name, {}).get("description", "")

                is_required = param_obj.default == inspect.Parameter.empty
                if hasattr(param_type_actual, '__origin__') and param_type_actual.__origin__ is Union: # Check for Optional[T] or T | None
                    if type(None) in param_type_actual.__args__:
                        is_required = False
                        # Optionally adjust param_type_actual to be the non-None type for LLM schema
                        # param_type_actual = next(t for t in param_type_actual.__args__ if t is not type(None))
                
                default_val = param_obj.default if param_obj.default != inspect.Parameter.empty else None

                parameters_defs.append(
                    ToolParameterDefinition(
                        name=param_name,
                        description=param_desc,
                        param_type=param_type_actual,
                        type_str=param_type_str,
                        is_required=is_required,
                        default_value=default_val,
                    )
                )
            # --- End Parameter Inference ---

            tool_definition = ToolDefinition(
                name=actual_name,
                description=tool_desc,
                func=func, 
                parameters=parameters_defs
            )
            
            setattr(wrapper, '_tool_definition', tool_definition)
            # from pocket_commander.tools.registry import global_tool_registry
            # global_tool_registry.register_tool_definition(tool_definition)

            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)
            
            return wrapper
        return decorator
    ```
*   **2. Metadata Extraction (Docstring Parsing):**
    *   Utilize `inspect.getdoc(func)` to get the function's docstring.
    *   Implement or use a library (e.g., `docstring_parser`) to parse Google-style docstrings. This will extract:
        *   The main tool description (from the summary and extended summary).
        *   Parameter descriptions (from the "Args:" section).
        *   Return description (if needed for LLMs).
    *   This parsed information will serve as the default, overridden by decorator arguments.
    *   **Location for parser:** Could be `pocket_commander/utils/docstring_parser.py` (new file).
*   **3. Parameter Inference (Type Hints & Docstrings):**
    *   Use `inspect.signature(func)` to get parameter names, type hints (`param.annotation`), and default values (`param.default`).
    *   **Name:** From `param.name`.
    *   **Type:**
        *   Python type: `param.annotation`.
        *   String representation for LLM: Map Python types (str, int, bool, float, list, dict, `typing.List`, `typing.Dict`, `typing.Optional`, `typing.Union`) to JSON Schema-like types ("string", "integer", "boolean", "number", "array", "object").
    *   **Description:** From parsed docstring (Args section), overridden by `param_descriptions` in the decorator.
    *   **Required/Optional:**
        *   If `param.default` is `inspect.Parameter.empty`, it's generally required.
        *   If `param.annotation` is `Optional[T]` or `T | None`, it's optional.
        *   If a default value is present, it's optional.
    *   **Default Value:** From `param.default` if not `inspect.Parameter.empty`.
*   **4. Handling Overrides:**
    *   Decorator arguments (`name`, `description`, `param_descriptions`) will take precedence over inferred values from docstrings or function name/type hints.
*   **5. Storing Metadata:**
    *   The extracted and processed metadata will be compiled into a `ToolDefinition` object.
    *   This `ToolDefinition` object will be attached to the decorated function (e.g., `wrapper._tool_definition = tool_def`) so the `ToolRegistry` can discover it later during scanning, or the decorator can directly call a registration method on the `ToolRegistry`.

**D. `ToolRegistry` Logic**

*   **Location:** `pocket_commander/tools/registry.py` (new file)
*   **Structure:**
    ```python
    # pocket_commander/tools/registry.py
    import inspect
    import importlib
    import pkgutil
    import os
    from typing import Dict, List, Optional, Callable, Any
    from pocket_commander.tools.definition import ToolDefinition

    class ToolRegistry:
        def __init__(self):
            self._tools: Dict[str, ToolDefinition] = {} # name -> ToolDefinition

        def register_tool_definition(self, tool_def: ToolDefinition, allow_override: bool = False):
            if not allow_override and tool_def.name in self._tools:
                # Handle conflict: log warning, raise error, or skip
                print(f"Warning: Tool '{tool_def.name}' already registered. Skipping duplicate.")
                return
            self._tools[tool_def.name] = tool_def
            print(f"Tool '{tool_def.name}' registered.")

        def register_tool_func(self, tool_func: Callable[..., Any], allow_override: bool = False):
            if hasattr(tool_func, '_tool_definition'):
                tool_def = getattr(tool_func, '_tool_definition')
                if isinstance(tool_def, ToolDefinition):
                    self.register_tool_definition(tool_def, allow_override=allow_override)
                else:
                    print(f"Warning: Function '{tool_func.__name__}' has '_tool_definition' but it's not a ToolDefinition instance.")
            else:
                print(f"Warning: Function '{tool_func.__name__}' is not a decorated tool or metadata is missing.")


        def scan_and_register_tools(self, package_path: str, base_module_path: str = ""):
            """
            Scans a package for modules and registers tools found within.
            package_path: Filesystem path to the package directory.
            base_module_path: Dotted module path corresponding to the package_path 
                              (e.g., "pocket_commander.tools.plugins")
            """
            print(f"Scanning for tools in package: {package_path} (module base: {base_module_path})")
            for (_, module_name, _) in pkgutil.walk_packages([package_path]):
                if base_module_path:
                    full_module_name = f"{base_module_path}.{module_name}"
                else: 
                    full_module_name = module_name
                
                try:
                    module = importlib.import_module(full_module_name)
                    for name, obj in inspect.getmembers(module):
                        if inspect.isfunction(obj) and hasattr(obj, '_tool_definition'):
                            tool_def = getattr(obj, '_tool_definition')
                            if isinstance(tool_def, ToolDefinition):
                                self.register_tool_definition(tool_def, allow_override=False) 
                except Exception as e:
                    print(f"Error importing or scanning module {full_module_name}: {e}")

        def get_tool(self, name: str) -> Optional[ToolDefinition]:
            return self._tools.get(name)

        def list_tools(self) -> List[ToolDefinition]:
            return list(self._tools.values())

        def get_all_tools_metadata_for_llm(self) -> List[Dict[str, Any]]:
            """Formats all tool definitions into a list of dicts suitable for LLM."""
            llm_tools = []
            for tool_def in self._tools.values():
                params_for_llm = {}
                required_params = []
                for p_def in tool_def.parameters:
                    params_for_llm[p_def.name] = {
                        "type": p_def.type_str,
                        "description": p_def.description,
                    }
                    if p_def.default_value is not None:
                         params_for_llm[p_def.name]["default"] = p_def.default_value
                    if p_def.is_required:
                        required_params.append(p_def.name)
                
                llm_tools.append({
                    "type": "function", 
                    "function": {
                        "name": tool_def.name,
                        "description": tool_def.description,
                        "parameters": {
                            "type": "object",
                            "properties": params_for_llm,
                            "required": required_params,
                        },
                    }
                })
            return llm_tools

    global_tool_registry = ToolRegistry()
    ```
*   **1. Storage:** A dictionary `_tools: Dict[str, ToolDefinition]` mapping tool names to their definitions.
*   **2. Explicit Registration:**
    *   `register_tool_definition(tool_def: ToolDefinition, allow_override: bool = False)`: Adds a `ToolDefinition` directly.
    *   `register_tool_func(tool_func: Callable, allow_override: bool = False)`: Takes a decorated function, extracts its `_tool_definition`, and registers it.
    *   Handles name conflicts. Explicit registration should generally take precedence.
*   **3. Directory Scanning:**
    *   `scan_and_register_tools(package_path: str, base_module_path: str)`:
        *   Uses `pkgutil.walk_packages` and `importlib.import_module`.
        *   Uses `inspect.getmembers` to find functions with `_tool_definition`.
        *   Registers found `ToolDefinition` objects, with lower precedence.
*   **4. Retrieval:**
    *   `get_tool(name: str) -> Optional[ToolDefinition]`
    *   `list_tools() -> List[ToolDefinition]`

**IV. LLM Integration**

*   The `ToolRegistry` will have `get_all_tools_metadata_for_llm() -> List[Dict[str, Any]]`.
*   This method formats `ToolDefinition` objects into a schema suitable for LLMs (e.g., OpenAI's function calling).
    *   Example parameter schema:
        ```json
        {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "The city and state, e.g. San Francisco, CA"
            },
            "unit": {
              "type": "string",
              "enum": ["celsius", "fahrenheit"],
              "description": "Temperature unit"
            }
          },
          "required": ["location"]
        }
        ```
*   This formatted list is passed to the LLM.

**V. File Structure**

```
pocket_commander/
├── tools/
│   ├── __init__.py
│   ├── definition.py       # ToolDefinition, ToolParameterDefinition
│   ├── decorators.py       # @tool decorator
│   ├── registry.py         # ToolRegistry, global_tool_registry
│   ├── tools.py            # Existing tools, to be decorated with @tool
│   └── web_tools.py        # Existing tools, to be decorated with @tool
│   └── plugins/            # Optional: Example directory for scanned tools
│       ├── __init__.py
│       └── example_plugin_tool.py
├── utils/
│   ├── __init__.py
│   └── docstring_parser.py # (New) Utility for parsing docstrings
# ... other files and folders
```

**VI. Example Usage**

*   **Defining a tool:**
    ```python
    # pocket_commander/tools/weather_tool.py 
    from pocket_commander.tools.decorators import tool
    from typing import Optional

    @tool(
        name="get_current_weather", 
        description="Fetches the current weather for a specified location.",
        param_descriptions={"unit": "The temperature unit, celsius or fahrenheit."}
    )
    async def get_weather(location: str, unit: Optional[str] = "celsius"):
        """
        Fetches the current weather conditions for a given city.

        Args:
            location (str): The city name (e.g., "London", "Paris, FR").
                            This is a required parameter.
            unit (Optional[str]): The unit for temperature, either "celsius" or "fahrenheit".
                                  Defaults to "celsius".
        """
        # ... actual tool logic ...
        return f"Weather in {location} is X degrees {unit}"
    ```

*   **Registering tools (e.g., in `pocket_commander/tools/__init__.py`):**
    ```python
    # pocket_commander/tools/__init__.py
    # Option 1: Decorator registers to global_tool_registry at import time
    # Then, simply import modules containing decorated tools:
    from . import tools # Assuming tools.py contains @tool decorated functions
    from . import web_tools 
    # Potentially scan plugin directories here too
    # from .registry import global_tool_registry, ToolRegistry # Expose if needed
    # from .decorators import tool # Expose if needed

    # Option 2: Manual registration after import (if decorator only attaches metadata)
    # from .registry import global_tool_registry
    # from . import tools as core_tools
    # global_tool_registry.register_tool_func(core_tools.get_weather) 
    ```
    The simplest approach is for the `@tool` decorator to directly register with `global_tool_registry` upon decoration (i.e., at module import time).

*   **Using the registry:**
    ```python
    from pocket_commander.tools.registry import global_tool_registry

    llm_tool_schemas = global_tool_registry.get_all_tools_metadata_for_llm()
    
    tool_to_run = global_tool_registry.get_tool("get_current_weather")
    if tool_to_run:
        # result = await tool_to_run.func(location="London", unit="celsius")
        pass 
    ```

**VII. Mermaid Diagram for Flow**

```mermaid
graph TD
    A[Developer writes async function] -- Decorates with --> B[@tool(...)];
    B -- Extracts metadata from --> F1[Type Hints];
    B -- Extracts metadata from --> F2[Docstring];
    B -- Uses --> F3[Decorator Args (Overrides)];
    B -- Creates --> C[ToolDefinition Object];
    C -- Attaches to function or Directly Registers with --> D[Global ToolRegistry];
    
    subgraph ToolRegistry Operations
        D -- Explicitly registers --> E1[tool_def via register_tool_definition()];
        D -- Scans directory & imports modules --> E2[scan_and_register_tools()];
        E2 -- Discovers decorated funcs (via attached metadata) --> D;
    end

    D -- Provides --> G[List of ToolDefinition for LLM];
    G -- Formatted for --> H[LLM (e.g., OpenAI API)];
    H -- Decides to use tool --> I[Pocket Commander Core];
    I -- Uses ToolRegistry to get --> J[ToolDefinition by name];
    J -- Contains --> K[Actual async tool function];
    I -- Calls --> K;

    style B fill:#f9f,stroke:#333,stroke-width:2px
    style D fill:#ccf,stroke:#333,stroke-width:2px
```

**VIII. Next Steps & Considerations**

1.  **Docstring Parser:** Implement or select a robust docstring parsing utility (e.g., `docstring_parser` library).
2.  **Refine Type Mapping:** Ensure comprehensive mapping from Python types to LLM/JSON Schema types.
3.  **Error Handling:** Implement robust error handling in decorator and registry.
4.  **Testing:** Thoroughly test all components.
5.  **Integration with `tool_enabled_llm_node.py`:** Use `get_all_tools_metadata_for_llm()` and `get_tool()` for LLM interaction.
6.  **Circular Dependencies:** Manage potential import cycles if the decorator directly uses the global registry.
7.  **Asynchronous Registry Operations:** Consider if any registry operations need to be `async`.