import asyncio
import functools
import inspect
from typing import Callable, Optional, List, Dict, Any, Type, Union

from pocket_commander.tools.definition import ToolDefinition, ToolParameterDefinition
from pocket_commander.tools.registry import global_tool_registry
from pocket_commander.utils.docstring_parser import parse_docstring

# Python type to JSON schema type string mapping
TYPE_STR_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    Any: "any", # For parameters with no type hint
}

def _get_param_type_str(param_type: Type[Any]) -> str:
    """Converts a Python type to its string representation for LLM/JSON schema."""
    origin_type = getattr(param_type, '__origin__', None)
    
    if origin_type is Union: # Handles Optional[T] which is Union[T, NoneType]
        args = getattr(param_type, '__args__', ())
        non_none_args = [arg for arg in args if arg is not type(None)]
        if len(non_none_args) == 1:
            # This is Optional[T], so use the type T
            return _get_param_type_str(non_none_args[0])
        else:
            # This is a more complex Union, e.g., Union[str, int]
            # For simplicity, returning "any". Could be "oneOf" in JSON schema.
            return "any" 
    if origin_type is list or origin_type is List:
        return "array"
    if origin_type is dict or origin_type is Dict:
        return "object"
    
    return TYPE_STR_MAP.get(param_type, "any")


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    param_descriptions: Optional[Dict[str, str]] = None,
):
    """
    Decorator to mark an async function as a tool, extract its metadata,
    and register it with the global_tool_registry.

    Args:
        name (Optional[str]): The name of the tool. If None, the function name is used.
        description (Optional[str]): A description of the tool. If None,
                                     it's extracted from the docstring summary.
        param_descriptions (Optional[Dict[str, str]]): Descriptions for specific parameters,
                                                       overriding docstring descriptions.
                                                       Keys are parameter names.
    """
    _param_descriptions_override = param_descriptions or {}

    def decorator(func: Callable[..., Any]):
        if not asyncio.iscoroutinefunction(func):
            raise TypeError(
                f"Tool '{func.__name__}' must be an async function (defined with 'async def')."
            )

        actual_tool_name = name or func.__name__
        
        docstring = inspect.getdoc(func)
        parsed_docstring_info = parse_docstring(docstring)
        
        tool_desc = description or parsed_docstring_info.get("summary", f"Tool: {actual_tool_name}")
        
        sig = inspect.signature(func)
        parameter_definitions: List[ToolParameterDefinition] = []

        for param_name, param_obj in sig.parameters.items():
            # Infer type
            param_type_actual = param_obj.annotation
            if param_type_actual == inspect.Parameter.empty:
                param_type_actual = Any # Default if no type hint

            param_type_str = _get_param_type_str(param_type_actual)

            # Infer description
            param_desc = _param_descriptions_override.get(param_name)
            if param_desc is None: # Check docstring if not overridden
                param_doc_info = parsed_docstring_info.get("params", {}).get(param_name, {})
                param_desc = param_doc_info.get("description", f"Parameter '{param_name}'")


            # Infer required status
            is_required = param_obj.default == inspect.Parameter.empty
            # Further check for Optional[T] or Union[T, None]
            origin_type = getattr(param_type_actual, '__origin__', None)
            if origin_type is Union:
                args = getattr(param_type_actual, '__args__', ())
                if type(None) in args:
                    is_required = False
            
            # Infer default value
            default_val = param_obj.default if param_obj.default != inspect.Parameter.empty else None

            # Get the actual type for Pydantic model (e.g., int from Optional[int])
            actual_pydantic_type = param_type_actual
            if origin_type is Union:
                args = getattr(param_type_actual, '__args__', ())
                non_none_args = [arg for arg in args if arg is not type(None)]
                if len(non_none_args) == 1:
                    actual_pydantic_type = non_none_args[0]
                # If it's a more complex Union (e.g., Union[str, int]),
                # Pydantic might still have issues with Type[Any].
                # For now, this handles Optional[T].
                # If other Unions are used and cause issues, this might need refinement
                # or ToolParameterDefinition.param_type might need to be broader.

            parameter_definitions.append(
                ToolParameterDefinition(
                    name=param_name,
                    description=param_desc,
                    param_type=actual_pydantic_type, # Use the unwrapped type
                    type_str=param_type_str,
                    is_required=is_required,
                    default_value=default_val,
                )
            )

        tool_def = ToolDefinition(
            name=actual_tool_name,
            description=tool_desc,
            func=func,  # Store the original undecorated async function
            parameters=parameter_definitions
        )
        
        # Attach metadata to the original function for potential introspection
        # setattr(func, '_tool_definition', tool_def) # Or to wrapper if preferred

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # The wrapper itself doesn't need to do much beyond calling the original function
            # as the metadata is for external use (registry, LLM).
            return await func(*args, **kwargs)

        # Attach metadata to the wrapper, as this is what gets returned and potentially inspected later
        # if not registering globally here.
        setattr(wrapper, '_tool_definition', tool_def)
        
        # Register with the global registry at decoration time (module import time)
        global_tool_registry.register_tool_definition(tool_def)
        
        return wrapper
    return decorator