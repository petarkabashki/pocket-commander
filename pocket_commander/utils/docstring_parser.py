from typing import Dict, Any, Optional

def parse_docstring(docstring: Optional[str]) -> Dict[str, Any]:
    """
    Parses a Google-style docstring.
    
    This is a placeholder implementation. A more robust parser should be used,
    e.g., the 'docstring_parser' library.

    Expected output structure:
    {
        "summary": "Brief description.",
        "extended_summary": "More detailed description.",
        "params": {
            "param_name1": {"description": "Desc of param1", "type_name": "str", "is_optional": False},
            "param_name2": {"description": "Desc of param2", "type_name": "int", "is_optional": True},
        },
        "returns": {"description": "What the function returns.", "type_name": "str"}
    }
    """
    if not docstring:
        return {}

    # Basic mock parsing for demonstration
    summary = docstring.strip().split('\n\n')[0].split('\nArgs:')[0].strip()
    
    parsed_params = {}
    if "\nArgs:" in docstring:
        args_section = docstring.split("\nArgs:")[1].split("\nReturns:")[0]
        for line in args_section.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                # Example: "param_name (str): Description."
                # Example: "param_name (str, optional): Description. Defaults to X."
                name_type_part, desc_part = line.split(":", 1)
                param_name = name_type_part.split(" (")[0].strip()
                
                type_name = "Any" # Default
                if " (" in name_type_part and ")" in name_type_part:
                    type_info_str = name_type_part.split(" (", 1)[1].split(")",1)[0]
                    type_name = type_info_str.split(",")[0].strip() # "str" from "str, optional"

                parsed_params[param_name] = {
                    "description": desc_part.strip(),
                    "type_name": type_name, # This is just illustrative from docstring, type hints are primary
                    "is_optional": "optional" in name_type_part.lower()
                }
            except ValueError:
                # Line doesn't match expected format, skip
                pass


    return {
        "summary": summary,
        "extended_summary": "", # Placeholder
        "params": parsed_params,
        "returns": {} # Placeholder
    }