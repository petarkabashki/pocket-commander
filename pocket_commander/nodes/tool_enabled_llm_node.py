import json # For parsing in test block, and for LLM communication
import asyncio
import logging
import yaml # Added for YAML parsing
import inspect # Added for tool inspection
from typing import Dict, Callable, List, Any # Added for type hinting

from ..pocketflow import AsyncNode # Base class for nodes
from ..utils.call_llm import call_llm # Changed import
# Updated import to the new function that uses ToolDefinition
from ..utils.prompt_utils import generate_tool_prompt_section_from_defs 
from ..tools.registry import global_tool_registry, ToolRegistry # Import registry
from ..tools.definition import ToolDefinition # Import ToolDefinition for type hinting

# Configure logging for this node
# Standard logging setup
logging.basicConfig(
    level=logging.INFO, # Changed to INFO for less verbose default logging
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] # Ensures logs go to stdout/stderr
)
logger = logging.getLogger(__name__)

class ToolEnabledLLMNode(AsyncNode):
    def __init__(self,
                 tool_registry: ToolRegistry = None, # Changed from available_tools
                 llm_profile_name: str = "default",
                 call_llm_func: Callable = None,
                 max_tool_attempts=3,
                 max_retries=1, # PocketFlow max_retries defaults to 1 (no retry)
                 wait=0):
        super().__init__(max_retries=max_retries, wait=wait)
        self.tool_registry = tool_registry if tool_registry else global_tool_registry # Use provided or global
        self.llm_profile_name = llm_profile_name
        self.call_llm_func = call_llm_func if call_llm_func else call_llm # Use provided or default
        self.max_tool_attempts = max_tool_attempts
        
        # Log registered tools from the registry
        registered_tool_names = [tool_def.name for tool_def in self.tool_registry.list_tools()]
        logger.info(
            f"ToolEnabledLLMNode initialized. "
            f"Tools from registry: {registered_tool_names}, "
            f"LLM Profile: {self.llm_profile_name}, "
            f"call_llm_func: {'provided' if call_llm_func else 'default'}, "
            f"Max tool attempts: {self.max_tool_attempts}, "
            f"Max retries: {self.max_retries}, Wait: {self.wait}s"
        )

    async def _execute_tool_async(self, tool_name: str, tool_input_dict: dict) -> str:
        """
        Execute a tool asynchronously with the given input using self.tool_registry.
        """
        logger.info(f"Executing tool: {tool_name} with input: {tool_input_dict}")
        tool_def = self.tool_registry.get_tool(tool_name)
        
        if tool_def:
            tool_function = tool_def.func # Get the callable from ToolDefinition
            try:
                if inspect.iscoroutinefunction(tool_function):
                    logger.debug(f"Tool {tool_name} is a coroutine function. Executing directly.")
                    result = await tool_function(**tool_input_dict)
                else:
                    logger.debug(f"Tool {tool_name} is a synchronous function. Executing in thread.")
                    result = await asyncio.to_thread(tool_function, **tool_input_dict)
                logger.info(f"Tool {tool_name} executed successfully. Result: {result}")
                return str(result) # Ensure result is string for consistent processing
            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
                return f"Error: Could not execute tool {tool_name}. Reason: {e}"
        else:
            registered_tool_names = [td.name for td in self.tool_registry.list_tools()]
            logger.warning(f"Tool {tool_name} not found in tool_registry. Available: {registered_tool_names}")
            return f"Error: Tool {tool_name} not found."

    async def prep_async(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepares the input for the LLM call.
        Expects 'query' and optionally 'messages' in shared store.
        """
        # logger.debug(f"Prep: Current shared state: {shared}")
        query = shared.get('query')
        if not query:
            logger.error("Prep: 'query' not found in shared store.")
            raise ValueError("'query' is required in shared store for ToolEnabledLLMNode.")

        messages = shared.get('messages', [])
        if not isinstance(messages, list):
            logger.warning(f"Prep: 'messages' in shared store was not a list (type: {type(messages)}). Resetting to empty list with query.")
            messages = []

        # Ensure the current user query is the last user message if not already part of a sequence
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != query:
            messages.append({"role": "user", "content": query})
            logger.debug(f"Prep: Added/updated user query to messages list.")
        
        logger.info(f"Prep: Prepared messages for query: '{query}'")
        return {"messages": messages, "max_tool_attempts": self.max_tool_attempts}

    async def exec_async(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes the LLM call with tool support using the prepared messages.
        Manages an LLM conversation that can decide to use tools.
        Uses YAML for tool communication.
        """
        initial_messages = prep_res["messages"]
        max_attempts = prep_res["max_tool_attempts"]
        logger.info(f"Exec: Starting LLM call with tool support. Max tool attempts: {max_attempts}, LLM Profile: {self.llm_profile_name}")

        # Get all tool definitions from the registry
        all_tool_defs = self.tool_registry.list_tools()
        tool_usage_instructions = generate_tool_prompt_section_from_defs(all_tool_defs)
        
        system_prompt_content = f"""You are a helpful assistant.
{tool_usage_instructions}
Ensure your response for a tool call is ONLY the YAML block, and for a direct answer, it is ONLY the plain text answer.
""" # Removed the duplicate "Ensure your response..." line from the original.
        # Ensure system prompt is the first message and only one system prompt exists
        current_messages = [msg for msg in initial_messages if msg.get("role") != "system"]
        current_messages.insert(0, {"role": "system", "content": system_prompt_content})
        
        logger.debug(f"Initial messages for LLM (with system prompt): {current_messages}")

        for attempt in range(max_attempts):
            logger.info(f"LLM call attempt {attempt + 1}/{max_attempts}")
            
            response_text = await asyncio.to_thread(self.call_llm_func, current_messages, profile_name=self.llm_profile_name)
            logger.debug(f"Raw LLM response: \n{response_text}")

            try:
                cleaned_response_text = response_text.strip()
                if cleaned_response_text.startswith("```yaml"):
                    cleaned_response_text = cleaned_response_text[7:]
                    if cleaned_response_text.endswith("```"):
                        cleaned_response_text = cleaned_response_text[:-3]
                    cleaned_response_text = cleaned_response_text.strip()

                logger.debug(f"Attempting to parse LLM response as YAML. Cleaned text for YAML load: '{cleaned_response_text}'")
                tool_call_data = yaml.safe_load(cleaned_response_text)
                logger.debug(f"Parsed YAML data (tool_call_data): {tool_call_data}")

                if isinstance(tool_call_data, dict) and \
                   "tool_call" in tool_call_data and \
                   isinstance(tool_call_data["tool_call"], dict) and \
                   "name" in tool_call_data["tool_call"] and \
                   "arguments" in tool_call_data["tool_call"] and \
                   isinstance(tool_call_data["tool_call"]["arguments"], dict):

                    tool_name = tool_call_data["tool_call"]["name"]
                    tool_input_dict = tool_call_data["tool_call"]["arguments"]
                    logger.info(f"LLM decided to use tool: {tool_name} with input: {tool_input_dict}")

                    tool_result = await self._execute_tool_async(tool_name, tool_input_dict)
                    logger.info(f"Result from tool '{tool_name}': {tool_result}")

                    current_messages.append({"role": "assistant", "content": cleaned_response_text}) # LLM's tool request (YAML)
                    current_messages.append({"role": "user", "content": f"Tool '{tool_name}' result: {tool_result}"}) # Simulate tool result as user message
                    logger.debug(f"Messages after tool execution: {current_messages[-2:]}") # Log last two messages

                    if attempt == max_attempts - 1:
                        logger.warning("Max tool attempts reached, LLM still trying to use tools. Forcing final answer generation.")
                        final_prompt_messages = current_messages + [
                            {"role": "system", "content": "You have reached the maximum tool use attempts. Please provide the final answer to the user based on the information gathered so far."}
                        ]
                        final_answer = await asyncio.to_thread(self.call_llm_func, final_prompt_messages, profile_name=self.llm_profile_name)
                        logger.info(f"Final answer after max tool attempts: {final_answer}")
                        current_messages.append({"role": "assistant", "content": final_answer})
                        return {"final_answer": final_answer, "updated_messages": current_messages}
                else:
                    logger.info("LLM response is valid YAML but not a recognized tool call, or not a dictionary. Treating as final text answer.")
                    current_messages.append({"role": "assistant", "content": response_text})
                    return {"final_answer": response_text, "updated_messages": current_messages}
            except yaml.YAMLError:
                logger.info("LLM response is not valid YAML. Treating as final text answer.")
                current_messages.append({"role": "assistant", "content": response_text})
                return {"final_answer": response_text, "updated_messages": current_messages}
            except Exception as e:
                logger.error(f"Unexpected error processing LLM response: {e}", exc_info=True)
                current_messages.append({"role": "assistant", "content": f"Error processing response: {e}"})
                return {"final_answer": f"Error processing response: {e}", "updated_messages": current_messages}

        logger.warning("Max tool attempts reached. Generating a fallback response.")
        final_fallback_prompt_messages = current_messages + [
            {"role": "system", "content": "You have reached the maximum tool use attempts. Please provide the final answer to the user based on the information gathered so far, or state that you couldn't complete the request."}
        ]
        final_fallback_answer = await asyncio.to_thread(self.call_llm_func, final_fallback_prompt_messages, profile_name=self.llm_profile_name)
        logger.info(f"Final fallback answer after max tool attempts: {final_fallback_answer}")
        current_messages.append({"role": "assistant", "content": final_fallback_answer})
        return {"final_answer": final_fallback_answer, "updated_messages": current_messages}

    async def post_async(self, shared: Dict[str, Any], prep_res: Dict[str, Any], exec_res: Dict[str, Any]) -> str:
        """
        Post-processes the result, updating the shared store.
        """
        # logger.debug(f"Post: Current shared state before update: {shared}")
        final_answer = exec_res.get("final_answer", "Error: No final answer found.")
        updated_messages = exec_res.get("updated_messages", [])

        shared['final_answer'] = final_answer
        shared['messages'] = updated_messages # Update messages with the full conversation history

        logger.info(f"Post: Updated shared store with final_answer: '{final_answer}' and conversation history.")
        # logger.debug(f"Post: Final shared state: {shared}")
        
        if "Error:" in final_answer :
            logger.warning("Post: Final answer indicates an error. Routing to 'error_occurred'.")
            return "error_occurred"
        return "answer_provided"

# Example of how this node might be used in a flow (conceptual)
if __name__ == '__main__':
    # Mock tools for testing - these would now be registered in global_tool_registry
    # For this test, we'll manually add them to a local registry instance if needed,
    # or rely on the global one if it's populated by tools/__init__.py
    
    # Ensure tools are registered for the test if not already by __init__.py
    # This part needs to align with how tools are actually made available to the node.
    # For a standalone test, we might need to explicitly register mock tools.

    from pocket_commander.tools.definition import ToolParameterDefinition
    from pocket_commander.tools.mcp_utils import create_mcp_tool_definition # For potential MCP tool test

    # Clear and set up a local registry for testing if needed, or assume global_tool_registry is set up.
    # For this example, let's assume global_tool_registry is used and populated by tools/__init__.py
    # If tools/__init__.py doesn't register test tools, we'd do it here.
    
    # Example: if we needed to register a mock 'get_weather' tool for testing:
    async def get_weather_mock_func(city: str, unit: str = "celsius"):
        await asyncio.sleep(0.1)
        if city.lower() == "london": return f"Weather in London: 15°{unit.upper()[0]}, Partly cloudy."
        if city.lower() == "paris": return f"Weather in Paris: 18°{unit.upper()[0]}, Sunny."
        return f"Weather data not available for {city}."

    weather_params = [
        ToolParameterDefinition(name="city", description="The city name.", param_type=str, type_str="string", is_required=True),
        ToolParameterDefinition(name="unit", description="Temperature unit (celsius or fahrenheit).", param_type=str, type_str="string", is_required=False, default_value="celsius")
    ]
    weather_tool_def = ToolDefinition(name="get_weather", description="Gets the current weather for a city.", func=get_weather_mock_func, parameters=weather_params)
    if not global_tool_registry.get_tool("get_weather"): # Avoid re-registering if already done by __init__
        global_tool_registry.register_tool_definition(weather_tool_def)
        logger.info("Mock 'get_weather' tool registered for test.")


    async def get_stock_price_mock_func(symbol: str):
        if symbol.upper() == "NVDA": return "NVDA stock price: $120.50"
        if symbol.upper() == "AAPL": return "AAPL stock price: $170.20"
        return f"Stock price not available for {symbol}."

    stock_params = [ToolParameterDefinition(name="symbol", description="The stock symbol.", param_type=str, type_str="string", is_required=True)]
    stock_tool_def = ToolDefinition(name="get_stock_price", description="Gets the current stock price for a symbol.", func=get_stock_price_mock_func, parameters=stock_params)
    if not global_tool_registry.get_tool("get_stock_price"):
        global_tool_registry.register_tool_definition(stock_tool_def)
        logger.info("Mock 'get_stock_price' tool registered for test.")

    # Assuming brave_web_search is registered by tools/__init__.py
    # If not, we would register a mock for it here as well.
    # For example:
    # brave_search_params = [
    #     ToolParameterDefinition(name="query", description="Search query", param_type=str, type_str="string", is_required=True),
    #     ToolParameterDefinition(name="count", description="Number of results", param_type=int, type_str="integer", is_required=False, default_value=3)
    # ]
    # async def brave_web_search_mock_func(query: str, count: int = 3):
    #     return f"Brave search results for '{query}' (mock, {count} items): [Result 1, Result 2, ...]"
    #
    # # Create ToolDefinition for the MCP tool via create_mcp_tool_definition
    # # This is slightly different as it uses the mcp_utils helper
    # mcp_brave_search_def = create_mcp_tool_definition(
    #     mcp_server_name="brave-search-mock", # Mock server name for testing
    #     mcp_tool_name="brave_web_search",
    #     mcp_tool_description="Mock Brave web search.",
    #     mcp_tool_parameters=brave_search_params # These would be ToolParameterDefinitions
    # )
    # # We need to ensure the func in this definition is the mock one for local testing
    # mcp_brave_search_def.func = brave_web_search_mock_func 
    # if not global_tool_registry.get_tool(mcp_brave_search_def.name):
    #      global_tool_registry.register_tool_definition(mcp_brave_search_def)
    #      logger.info(f"Mock MCP tool '{mcp_brave_search_def.name}' registered for test.")


    def mock_call_llm_sync(messages: List[Dict[str, str]], profile_name: str = "default"):
        logger.info(f"Mock LLM (sync) called with profile: {profile_name} and {len(messages)} messages.")
        # logger.debug(f"Mock LLM messages: {messages}") # Can be very verbose

        latest_content = ""
        if messages:
            if messages[-1].get("role") == "system" and "provide the final answer" in messages[-1].get("content", "").lower():
                for i in range(len(messages) - 2, -1, -1):
                    if messages[i].get("role") == "user":
                        latest_content = messages[i].get("content","").lower()
                        break
            elif messages[-1].get("role") == "user": 
                latest_content = messages[-1].get("content","").lower()
            else: 
                for msg in reversed(messages):
                    if msg.get("role") == "user":
                        latest_content = msg.get("content","").lower()
                        break
        
        logger.info(f"Mock LLM processing latest relevant content: '{latest_content[:200]}...'")

        # Test with Brave Search
        if "search the web for pocket commander" in latest_content:
            logger.info("Mock LLM: Detected Brave Search query. Responding with brave_web_search tool call.")
            # Note: The tool name will be 'mcp_brave_search_brave_web_search' due to create_mcp_tool_definition
            # Ensure this matches how it's registered in tools/__init__.py or the test setup.
            # The actual name from tools/__init__.py is 'mcp_brave-search_brave_web_search'
            # Let's use the one from tools/__init__.py for consistency if it's expected to be there.
            # The actual name is 'mcp_brave_search_brave_web_search' (underscores)
            
            # Check if the actual brave search tool is registered
            tool_name_to_call = "mcp_brave_search_brave_web_search" # from tools/__init__.py
            if not global_tool_registry.get_tool(tool_name_to_call):
                 # Fallback to a generic mock name if the specific one isn't there (e.g. if tools/__init__ didn't run or register it)
                 logger.warning(f"Tool '{tool_name_to_call}' not found in registry for mock LLM. Check registration in tools/__init__.py or test setup.")
                 # This part of the mock LLM might need adjustment based on actual registered names.
                 # For now, let's assume it *is* registered as 'mcp_brave_search_brave_web_search'
            
            return f"""```yaml
tool_call:
  name: "{tool_name_to_call}"
  arguments:
    query: "pocket commander AI"
    count: 2
```"""
        elif f"tool '{'mcp_brave_search_brave_web_search'}' result:" in latest_content:
            logger.info("Mock LLM: Detected Brave Search result. Responding with final answer.")
            return "Based on the web search, Pocket Commander is an agentic AI workflow engine."


        if "what's the weather like in london" in latest_content and "price of nvda stock" in latest_content:
            logger.info("Mock LLM: Detected initial query. Responding with weather tool call.")
            return """```yaml
tool_call:
  name: get_weather
  arguments:
    city: London
    unit: celsius
```"""
        elif "tool 'get_weather' result:" in latest_content and "london" in latest_content:
            logger.info("Mock LLM: Detected weather tool result. Responding with stock tool call.")
            return """```yaml
tool_call:
  name: get_stock_price
  arguments:
    symbol: NVDA
```"""
        elif "tool 'get_stock_price' result:" in latest_content and "nvda" in latest_content:
            logger.info("Mock LLM: Detected stock tool result. Responding with final answer.")
            weather_res = "Weather in London: 15°C, Partly cloudy." 
            stock_res = "NVDA stock price: $120.50"
            return f"Okay, I have the information. {weather_res} And {stock_res}"
        
        logger.warning(f"Mock LLM: No specific condition met for content. Providing a generic final answer.")
        return "This is a mock LLM final textual response based on the conversation history."

    async def run_node_test(query_to_test: str, test_name: str):
        logger.info(f"--- Starting ToolEnabledLLMNode Test: {test_name} ---")
        
        shared_data = {
            'query': query_to_test,
            'messages': [] 
        }

        # Node will use global_tool_registry by default now
        node = ToolEnabledLLMNode(
            llm_profile_name="default", 
            call_llm_func=mock_call_llm_sync, 
            max_tool_attempts=3
        )
        
        logger.info(f"Test query: '{query_to_test}'")
        logger.info("The test will use the mock 'mock_call_llm_sync' for LLM calls.")
        logger.info(f"Tools available in global_tool_registry for this test: {[t.name for t in global_tool_registry.list_tools()]}")


        try:
            logger.info("--- Testing prep_async ---")
            prep_result = await node.prep_async(shared_data)
            logger.info(f"prep_async result: {prep_result}")

            logger.info("--- Testing exec_async ---")
            exec_result = await node.exec_async(prep_result)
            logger.info(f"exec_async result: {exec_result}")

            logger.info("--- Testing post_async ---")
            next_action = await node.post_async(shared_data, prep_result, exec_result)
            logger.info(f"post_async next_action: {next_action}")

            logger.info(f"Final shared_data for '{test_name}': {json.dumps(shared_data, indent=2)}")

        except Exception as e:
            logger.error(f"Error during node test '{test_name}': {e}", exc_info=True)
        
        logger.info(f"--- ToolEnabledLLMNode Test Finished: {test_name} ---")

    async def main_test_runner():
        # Test 1: Original weather and stock query
        await run_node_test(
            query_to_test="What's the weather like in London and what is the current price of NVDA stock?",
            test_name="Weather and Stock"
        )
        
        # Test 2: Brave Search query
        # Ensure the mcp_brave_search_brave_web_search tool is correctly registered in tools/__init__.py
        # or manually registered in the test setup above if tools/__init__.py is not run/effective here.
        if global_tool_registry.get_tool("mcp_brave_search_brave_web_search"):
            await run_node_test(
                query_to_test="Search the web for pocket commander AI.",
                test_name="Brave Search MCP Tool"
            )
        else:
            logger.error("Skipping 'Brave Search MCP Tool' test because 'mcp_brave_search_brave_web_search' is not registered.")


    # This import needs to happen *after* potential test registrations if tools/__init__.py isn't solely relied upon.
    # However, for the actual application, tools/__init__.py should handle all registrations.
    # For testing, it's tricky if __main__ runs before tools/__init__ has fully populated global_tool_registry.
    # A better test setup might involve a dedicated test registry or ensuring tools are loaded.
    # For now, we assume tools/__init__.py runs when pocket_commander.nodes is imported.
    try:
        import pocket_commander.tools # This should trigger tools/__init__.py
        logger.info("Successfully imported pocket_commander.tools, hoping __init__.py ran.")
    except ImportError as e:
        logger.error(f"Could not import pocket_commander.tools: {e}. Tool registration in __init__.py might not have occurred.")

    asyncio.run(main_test_runner())