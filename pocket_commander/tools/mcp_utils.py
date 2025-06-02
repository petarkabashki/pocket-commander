from typing import Any, Dict, Callable, List, Coroutine
import asyncio

from mcp import ClientSession, types # type: ignore

from pocket_commander.tools.definition import ToolDefinition, ToolParameterDefinition

# TODO: Move this to a proper configuration system
MCP_SERVER_ADDRESSES = {
    "example-mcp-server": "http://localhost:8000", # Example, adjust as needed
    "another-mcp-server": "https://mcp.example.com",
    # Add other known MCP server addresses here
}

async def mcp_tool_caller(
    server_name: str, 
    tool_name: str, 
    arguments: Dict[str, Any]
) -> Any:
    """
    Generic caller for MCP (Model Context Protocol) tools using the SDK.

    This function is responsible for dispatching a tool call to the specified MCP server
    with the given arguments using the agent-context-protocol-sdk.

    Args:
        server_name: The name of the MCP server.
        tool_name: The name of the tool to call on the MCP server.
        arguments: A dictionary of arguments to pass to the MCP tool.

    Returns:
        The result from the MCP tool execution.
        
    Raises:
        ValueError: If the server_name is not found in MCP_SERVER_ADDRESSES.
        types.Error # TODO: Verify this is the correct MCP SDK error base class: If the SDK raises an error during communication.
        Exception: For other general errors.
    """
    target_address = MCP_SERVER_ADDRESSES.get(server_name)
    if not target_address:
        raise ValueError(f"Unknown MCP server name: {server_name}. Configure it in MCP_SERVER_ADDRESSES.")

    print(f"[MCP Call SDK] Attempting to call tool '{tool_name}' on server '{server_name}' ({target_address}) with arguments: {arguments}")

    try:
        # Consult SDK documentation for actual client usage and method names
        async with ClientSession(target_address=target_address) as client: # type: ignore # TODO: Verify ClientSession constructor for HTTP target
            # Assuming the SDK has a method like use_tool or similar.
            # The exact method and response structure would depend on the SDK's API.
            # For example:
            # response = await client.use_tool(tool_name=tool_name, arguments=arguments)
            # return response.result # Or however the SDK provides the tool's output

            # Attempt to call the MCP tool using the SDK.
            # The parameter 'input' for arguments is assumed based on common SDK patterns.
            # The actual method for extracting the result from the response (e.g., response.payload)
            # needs to be verified against the agent-context-protocol-sdk documentation.
            response = await client.use_tool(tool_name=tool_name, input=arguments) # type: ignore

            # TODO: End-user to verify against a live MCP server that `response.payload` (or other attribute)
            # correctly extracts the tool output from agent-context-protocol-sdk.
            # Common attributes could be 'payload', 'data', 'result', or the response itself might be the output.
            if hasattr(response, 'payload'):
                return response.payload # type: ignore
            elif hasattr(response, 'result'): # Keep existing checks as fallbacks
                return response.result # type: ignore
            elif hasattr(response, 'data'):
                return response.data # type: ignore
            else:
                # If no common attribute is found, return the whole response object.
                # This allows for inspection and may be the intended behavior if the tool
                # output is the response object itself.
                return response

    except types.Error as e: # TODO: Verify this is the correct MCP SDK error base class # Catch specific SDK errors
        print(f"[MCP Call SDK] MCP Client Error for tool '{tool_name}' on '{server_name}': {e}")
        # Depending on desired error handling, you might return a structured error
        # or re-raise the exception. For now, re-raising.
        raise
    except Exception as e: # Catch other potential errors (network, etc.)
        print(f"[MCP Call SDK] General Error for tool '{tool_name}' on '{server_name}': {e}")
        # Similar to above, re-raising.
        raise

def create_mcp_tool_definition(
    mcp_server_name: str,
    mcp_tool_name: str,
    mcp_tool_description: str,
    mcp_tool_parameters: List[ToolParameterDefinition]
) -> ToolDefinition:
    """
    Creates a Pocket Commander ToolDefinition for a given MCP tool.

    This function wraps the generic `mcp_tool_caller` to create a specific
    callable function that matches the ToolDefinition interface. The MCP tool's
    metadata (name, description, parameters) is used to construct the ToolDefinition.

    Args:
        mcp_server_name: The name of the MCP server providing the tool.
        mcp_tool_name: The original name of the tool on the MCP server.
        mcp_tool_description: A description of what the MCP tool does.
        mcp_tool_parameters: A list of ToolParameterDefinition objects, derived
                             from the MCP tool's schema.

    Returns:
        A ToolDefinition object that can be registered in Pocket Commander's tool registry.
    """
    
    # Create the specific asynchronous function that will be called by Pocket Commander.
    # This function will invoke the generic mcp_tool_caller with the correct
    # server_name and tool_name bound.
    async def specific_mcp_tool_func(**kwargs: Any) -> Any:
        """Dynamically generated wrapper for a specific MCP tool."""
        return await mcp_tool_caller(
            server_name=mcp_server_name,
            tool_name=mcp_tool_name,
            arguments=kwargs
        )

    # Sanitize server and tool names for use in Pocket Commander tool name
    safe_server_name = mcp_server_name.replace('-', '_').replace('.', '_')
    safe_tool_name = mcp_tool_name.replace('-', '_').replace('.', '_')
    
    # Construct a unique and descriptive name for the tool within Pocket Commander
    pc_tool_name = f"mcp_{safe_server_name}_{safe_tool_name}"
    
    # Enhance the description to indicate it's an MCP tool
    pc_tool_description = f"[MCP Tool on '{mcp_server_name}'] {mcp_tool_description}"

    return ToolDefinition(
        name=pc_tool_name,
        description=pc_tool_description,
        func=specific_mcp_tool_func, # This is an async function
        parameters=mcp_tool_parameters
    )

# Example usage (for testing or direct registration, actual registration might happen elsewhere):
#
# async def example_register_mcp_tools():
#     from pocket_commander.tools.registry import register_tool # Assuming this exists
#
#     # This data would typically come from discovering MCP servers and their tool schemas
#     sample_mcp_tool_info = {
#         "server_name": "example-mcp-server",
#         "tool_name": "get-user-data",
#         "description": "Fetches user data based on user ID.",
#         "parameters_schema": [ # This is a simplified schema
#             {"name": "user_id", "description": "The ID of the user.", "type": "string", "required": True},
#             {"name": "include_details", "description": "Whether to include detailed information.", "type": "boolean", "required": False, "default": False}
#         ]
#     }
#
#     # Convert MCP schema parameters to ToolParameterDefinition
#     # This conversion logic would need to map MCP types to Python types and string representations
#     parsed_parameters = []
#     for param_schema in sample_mcp_tool_info["parameters_schema"]:
#         param_type = str # Default
#         type_str = param_schema["type"]
#         if type_str == "string":
#             param_type = str
#         elif type_str == "integer":
#             param_type = int
#         elif type_str == "boolean":
#             param_type = bool
#         
#         parsed_parameters.append(
#             ToolParameterDefinition(
#                 name=param_schema["name"],
#                 description=param_schema["description"],
#                 param_type=param_type,
#                 type_str=type_str,
#                 is_required=param_schema["required"],
#                 default_value=param_schema.get("default")
#             )
#         )
#
#     mcp_tool_def = create_mcp_tool_definition(
#         mcp_server_name=sample_mcp_tool_info["server_name"],
#         mcp_tool_name=sample_mcp_tool_info["tool_name"],
#         mcp_tool_description=sample_mcp_tool_info["description"],
#         mcp_tool_parameters=parsed_parameters
#     )
#
#     # register_tool(mcp_tool_def) # Actual registration
#     print(f"Created MCP ToolDefinition: {mcp_tool_def.name}")
#     # To test the caller:
#     # result = await mcp_tool_def.func(user_id="123", include_details=True)
#     # print(f"Test call result: {result}")

# if __name__ == '__main__':
#     # Example of how to test the functions if run directly (requires an event loop)
#     async def main_test():
#         await example_register_mcp_tools()
#
#     asyncio.run(main_test())