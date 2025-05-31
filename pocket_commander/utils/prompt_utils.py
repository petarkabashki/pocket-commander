import inspect
import re
from typing import List, Dict, Any, Optional, Callable

from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage, ToolMessage

def get_parameter_type_str(param: inspect.Parameter) -> str:
    """Helper to get a string representation of a parameter's type hint."""
    if param.annotation == inspect.Parameter.empty:
        return "Any"
    if hasattr(param.annotation, '__name__'):
        return param.annotation.__name__
    return str(param.annotation)


def generate_tool_prompt_section(tools: Dict[str, Callable[..., Any]]) -> str:
    """
    Generates the tool description and YAML instruction prompt section for a given set of tools.
    """
    tool_doc_parts = []
    for tool_name, tool_func in tools.items():
        docstring = inspect.getdoc(tool_func)
        description = "No description available."
        param_details_str = "    # No parameters defined for this tool." # Default if no params

        if docstring:
            description = docstring.splitlines()[0].strip()
            # Try to parse parameters from docstring first
            param_lines_from_doc = [line.strip() for line in docstring.splitlines() if line.strip().startswith("- ")] # Basic check

            parsed_params_from_doc = []
            # More robust parsing from docstring if needed
            # This section can be enhanced based on specific docstring formats
            temp_params_list = []
            param_section_started = False
            for line in docstring.splitlines():
                line = line.strip()
                if line.lower().startswith("parameters:") or line.lower().startswith("args:") or line.lower().startswith("arguments:"):
                    param_section_started = True
                    continue
                if param_section_started:
                    if line.startswith("- "): # Start of a new param
                        temp_params_list.append(line)
                    elif temp_params_list and (line.startswith("  ") or line.startswith("\t") or not line.strip()): # Continuation or empty line
                        if line.strip(): # only append if not just an empty line separating params
                             temp_params_list[-1] += " " + line
                    else: # End of params section or unexpected format
                        param_section_started = False


            for param_entry in temp_params_list:
                match = re.match(r"^\s*(?:-\s*)?(\w+)\s*(?:\((.*?)\))?:\s*(.*)", param_entry)
                if match:
                    name, type_hint, desc = match.groups()
                    type_str = type_hint.strip() if type_hint else "unknown"
                    parsed_params_from_doc.append(f"      {name} ({type_str}): {desc.strip()}")
            
            if parsed_params_from_doc:
                param_details_str = "\n".join(parsed_params_from_doc)
            else: # Fallback to inspect.signature if docstring parsing fails or no params in doc
                sig = inspect.signature(tool_func)
                if sig.parameters:
                    params_from_sig = []
                    for name, param in sig.parameters.items():
                        param_type = get_parameter_type_str(param)
                        # Try to find param description in docstring body if not in a structured list
                        param_desc_match = re.search(rf"{name}\s*:\s*(.*)", docstring, re.IGNORECASE)
                        param_desc = param_desc_match.group(1).strip() if param_desc_match else f"Description of {name}."
                        params_from_sig.append(f"      {name} ({param_type}): {param_desc}")
                    if params_from_sig:
                        param_details_str = "\n".join(params_from_sig)
        else: # No docstring, use inspect.signature
            sig = inspect.signature(tool_func)
            if sig.parameters:
                params_from_sig = []
                for name, param in sig.parameters.items():
                    param_type = get_parameter_type_str(param)
                    params_from_sig.append(f"      {name} ({param_type}): Description of {name}.")
                if params_from_sig:
                    param_details_str = "\n".join(params_from_sig)

        tool_doc_parts.append(
            f"  - name: \"{tool_name}\"\n"
            f"    description: \"{description}\"\n"
            f"    parameters: \n{param_details_str}"
        )
    
    tool_list_str = "\n".join(tool_doc_parts)

    yaml_tool_call_example = """```yaml
tool_call:
  name: "tool_name_here"
  arguments:
    parameter_name_1: "value1"
    parameter_name_2: "value2"
```"""

    prompt = f"""You have access to the following tools:
{tool_list_str}

If you decide to use a tool to answer the user's request, your response MUST consist ONLY of a YAML block formatted exactly as shown below.
Do not include any other text, explanations, or conversational filler before or after the YAML block.
The YAML block should start with '```yaml' and end with '```'.

Example of a tool call YAML structure:
{yaml_tool_call_example}

If you do not need to use a tool, or if the user's request is a simple greeting or statement not requiring a tool, respond with your answer as plain text.
After any tools are called and their results are provided to you, you MUST then synthesize all the information (from the tool results and the conversation history) to provide a final, comprehensive, natural language answer to the user's original query. Do not attempt to call more tools unless absolutely necessary to fulfill the user's request and the required information is not yet available.
Now, consider the user's request and the conversation history.
"""
    return prompt
