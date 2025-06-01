from typing import Any, Optional, Type, Callable, List, Dict
from pydantic import BaseModel, Field

class ToolParameterDefinition(BaseModel):
    """
    Data structure to hold metadata for a single tool parameter.
    """
    name: str
    description: str
    param_type: Type[Any]  # Store the actual Python type
    type_str: str          # String representation for LLM (e.g., "string", "integer", "boolean")
    is_required: bool
    default_value: Optional[Any] = None

    class Config:
        arbitrary_types_allowed = True # To allow Type[Any]

class ToolDefinition(BaseModel):
    """
    Data structure to hold all metadata for a tool.
    """
    name: str
    description: str
    func: Callable[..., Any]  # The actual async tool function
    parameters: List[ToolParameterDefinition]
    # Optional: for richer LLM schema generation if needed later
    # parameters_schema: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True  # To allow Callable