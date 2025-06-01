#%%
# pocket_commander/commands/parser.py
import inspect
import shlex
from typing import Any, Dict, List, Optional, Type, Union, get_origin, get_args

from pocket_commander.commands.definition import ParameterDefinition
from pocket_commander.commands.io import AbstractCommandInput

class ArgumentParsingError(ValueError):
    """Custom exception for argument parsing errors."""
    pass

async def parse_arguments(
    command_input: AbstractCommandInput,
    param_definitions: List[ParameterDefinition]
) -> Dict[str, Any]:
    """
    Parses arguments from the command input based on parameter definitions.

    This is a sophisticated parser that aims to handle:
    - Positional arguments.
    - Type casting.
    - Required checks.
    - Default values.
    - Variadic positional arguments (*args).
    - Boolean flags (e.g., --enable-feature).
    - Named arguments (e.g., --option value).

    Args:
        command_input: The input object providing access to raw input string.
        param_definitions: A list of ParameterDefinition objects for the command.

    Returns:
        A dictionary mapping parameter names to their parsed values.

    Raises:
        ArgumentParsingError: If parsing fails due to type mismatches,
                              missing required arguments, or other issues.
    """
    parsed_args: Dict[str, Any] = {}
    # Use shlex to split arguments respecting quotes
    try:
        input_tokens = shlex.split(command_input.get_remaining_input())
    except ValueError as e:
        raise ArgumentParsingError(f"Error splitting input: {e}. Check for unmatched quotes.") from e
    
    token_idx = 0
    param_def_idx = 0

    # Iterate through parameter definitions to match them with input tokens
    while param_def_idx < len(param_definitions):
        param_def = param_definitions[param_def_idx]
        
        # --- Handle Variadic Positional Arguments (*args) ---
        if param_def.name.startswith('*'): # Convention: *args_name
            actual_name = param_def.name[1:]
            # Consume all remaining positional tokens
            remaining_tokens = input_tokens[token_idx:]
            
            # Type cast each token if a specific list item type is provided (e.g., List[int])
            list_item_type = str # Default to string if not further specified
            if get_origin(param_def.param_type) is list and get_args(param_def.param_type):
                list_item_type = get_args(param_def.param_type)[0]

            try:
                parsed_args[actual_name] = [
                    _cast_value(token, list_item_type, param_def.name) for token in remaining_tokens
                ]
            except ValueError as e:
                raise ArgumentParsingError(str(e)) from e
            
            token_idx = len(input_tokens) # All tokens consumed
            param_def_idx += 1
            continue

        # --- Handle Boolean Flags and Named Arguments ---
        # This parser prioritizes positional arguments based on param_definitions order.
        # For a more robust CLI-style parser with named flags anywhere, a different approach
        # (e.g., pre-parsing all named flags) would be needed.
        # This version assumes named flags/options are handled if not matched positionally.

        # --- Handle Positional Arguments ---
        if token_idx < len(input_tokens):
            token = input_tokens[token_idx]
            
            # Simple boolean flag check (e.g. --flag or no-flag)
            if param_def.param_type is bool:
                if token.lower() in [f"--{param_def.name}", f"-{param_def.name}", param_def.name]: # if token is like --verbose
                    parsed_args[param_def.name] = True
                    token_idx +=1
                    param_def_idx +=1
                    continue
                elif token.lower() in [f"--no-{param_def.name}", f"--no{param_def.name}"]:
                    parsed_args[param_def.name] = False
                    token_idx +=1
                    param_def_idx +=1
                    continue
                # If bool param is required and not found as a flag, it might be expecting True/False literal
                # or rely on default. If it's just a flag, it should not be 'required' in the typical sense.

            try:
                parsed_args[param_def.name] = _cast_value(token, param_def.param_type, param_def.name)
                token_idx += 1
            except ValueError as e:
                # If casting fails, it might be a named argument or an error
                # For now, we assume positional or error.
                if param_def.required and param_def.default is None:
                    raise ArgumentParsingError(str(e)) from e
                # If not required or has default, we'll let the later check handle it
                parsed_args[param_def.name] = param_def.default # Tentatively set default
        
        param_def_idx += 1


    # --- Check for Missing Required Arguments and Apply Defaults ---
    for param_def in param_definitions:
        actual_name = param_def.name[1:] if param_def.name.startswith('*') else param_def.name
        
        if actual_name not in parsed_args:
            if param_def.required and param_def.default is None:
                # Special handling for boolean flags that are 'required'
                # Typically, a boolean flag isn't "required" in the sense of needing a value,
                # but rather its presence or absence signifies True/False.
                # If it's defined as bool and required, and not found, assume False unless default is True.
                if param_def.param_type is bool:
                     parsed_args[actual_name] = False # Or param_def.default if it could be True
                else:
                    raise ArgumentParsingError(f"Missing required argument: '{actual_name}'")
            elif param_def.default is not None:
                parsed_args[actual_name] = param_def.default
            elif param_def.param_type is bool: # If a boolean flag is not present, it's false by default
                 parsed_args[actual_name] = False


    # --- Check for Unconsumed Tokens (Extra Arguments) ---
    # This basic parser doesn't explicitly handle unexpected extra positional arguments
    # if no *args parameter is defined.
    # A more advanced parser might raise an error here if token_idx < len(input_tokens)
    # and no variadic parameter was present.
    if token_idx < len(input_tokens) and not any(p.name.startswith('*') for p in param_definitions):
        raise ArgumentParsingError(f"Unexpected arguments: {' '.join(input_tokens[token_idx:])}")

    return parsed_args

def _cast_value(value_str: str, target_type: Type, param_name: str) -> Any:
    """Casts a string value to the target type."""
    origin_type = get_origin(target_type)
    
    if origin_type is Union: # Handles Optional[T] which is Union[T, NoneType]
        args = get_args(target_type)
        if type(None) in args: # It's an Optional
            non_none_types = [t for t in args if t is not type(None)]
            if not non_none_types: # Should not happen with valid Optional
                return None 
            # Try casting to the first non-None type
            # For more complex Unions, more logic would be needed
            try:
                return _cast_value(value_str, non_none_types[0], param_name)
            except ValueError: # If casting fails, and it's optional, allow None if value_str is empty or specific
                if value_str.lower() in ["none", "null", ""]: # Or other "None-like" strings
                    return None
                raise
        else: # Other Union types, attempt casting to each type
            for t_arg in args:
                try:
                    return _cast_value(value_str, t_arg, param_name)
                except ValueError:
                    continue
            raise ArgumentParsingError(f"Argument '{param_name}': Value '{value_str}' does not match any type in Union {target_type}")


    if target_type is bool:
        low_val = value_str.lower()
        if low_val in ["true", "yes", "1", "on"]:
            return True
        elif low_val in ["false", "no", "0", "off"]:
            return False
        raise ArgumentParsingError(f"Argument '{param_name}': Cannot cast '{value_str}' to boolean.")
    if target_type is int:
        try:
            return int(value_str)
        except ValueError:
            raise ArgumentParsingError(f"Argument '{param_name}': Cannot cast '{value_str}' to integer.") from None
    if target_type is float:
        try:
            return float(value_str)
        except ValueError:
            raise ArgumentParsingError(f"Argument '{param_name}': Cannot cast '{value_str}' to float.") from None
    if target_type is str:
        return value_str
    
    # For list, tuple, dict - shlex usually handles basic structure if input is well-formed
    # but direct casting from a single string token to these types is complex.
    # This parser assumes individual tokens are being cast.
    # For e.g. List[int], the variadic handling does item-wise casting.
    if origin_type is list and get_args(target_type): # e.g. List[int]
        # This case is more for type-hinting a single argument that should be a list
        # e.g. --items 1,2,3.  The current token-by-token parsing doesn't directly support this
        # without custom splitting logic for that token.
        # For now, we'll assume if List[T] is a param_type for a single token, it's an error
        # unless it's handled by variadic args.
        raise ArgumentParsingError(f"Argument '{param_name}': Direct casting of a single token to {target_type} is not supported. Use *args for multiple values.")

    # Fallback for any other types or custom types (might require __init__(str) or a from_str method)
    try:
        if callable(target_type) and not isinstance(target_type, type): # e.g. a function type hint
             raise ArgumentParsingError(f"Argument '{param_name}': Function types are not directly parsable.")
        return target_type(value_str)
    except Exception as e: # Broad catch, as custom types can raise anything
        raise ArgumentParsingError(f"Argument '{param_name}': Error casting '{value_str}' to {target_type.__name__}: {e}") from e