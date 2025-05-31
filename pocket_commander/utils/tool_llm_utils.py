import yaml
import json # Still needed for initial parsing if LLM sends JSON, but we instruct YAML
import asyncio
import inspect
import logging

# Adjust imports based on the new location in the utils folder
from .call_llm import call_llm
from ..tools.tools import get_weather, get_stock_price
from ..tools.web_tools import search_web
from .prompt_utils import generate_tool_prompt_section

# Configure logging for this utility module
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] # Ensures logs go to stdout/stderr
)
logger = logging.getLogger(__name__)

# A dictionary to map tool names to their callable functions
AVAILABLE_TOOLS = {
    "search_web": search_web,
    "get_weather": get_weather,
    "get_stock_price": get_stock_price,
}

# Generate the complete tool usage instruction prompt part.
TOOL_USAGE_INSTRUCTIONS_PROMPT = generate_tool_prompt_section(AVAILABLE_TOOLS)

# --- Execute Tool (Async) ---
async def execute_tool_async(tool_name: str, tool_input_dict: dict) -> str:
    """
    Execute a tool asynchronously with the given input.
    :param tool_name: The name of the tool to execute.
    :param tool_input_dict: The dictionary of inputs to the tool.
    """
    logger.info(f"Executing tool: {tool_name} with input: {tool_input_dict}")
    if tool_name in AVAILABLE_TOOLS:
        tool_function = AVAILABLE_TOOLS[tool_name]
        try:
            if inspect.iscoroutinefunction(tool_function):
                logger.info(f"Tool {tool_name} is a coroutine function. Executing directly.")
                result = await tool_function(**tool_input_dict)
            else:
                logger.info(f"Tool {tool_name} is a synchronous function. Executing in thread.")
                result = await asyncio.to_thread(tool_function, **tool_input_dict)
            logger.info(f"Tool {tool_name} executed successfully. Result: {result}")
            return str(result) # Ensure result is string for consistent processing
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            return f"Error: Could not execute tool {tool_name}. Reason: {e}"
    else:
        logger.warning(f"Tool {tool_name} not found.")
        return f"Error: Tool {tool_name} not found."

# --- LLM Call with Tool Support (Async) ---
async def llm_call_with_tool_support_async(
    initial_messages: list,
    max_tool_attempts: int = 3
):
    """
    Manages an LLM conversation that can decide to use tools.
    Uses YAML for tool communication.
    """
    logger.info(f"Starting LLM call with tool support. Max attempts: {max_tool_attempts}")

    system_prompt = f"""You are a helpful assistant.
{TOOL_USAGE_INSTRUCTIONS_PROMPT}
Ensure your response for a tool call is ONLY the YAML block, and for a direct answer, it is ONLY the plain text answer.
"""
    current_messages = [{"role": "system", "content": system_prompt}] + initial_messages
    logger.debug(f"Initial messages for LLM: {current_messages}")

    for attempt in range(max_tool_attempts):
        logger.info(f"LLM call attempt {attempt + 1}/{max_tool_attempts}")
        # Assuming call_llm is synchronous, run in a thread
        response_text = await asyncio.to_thread(call_llm, current_messages)
        logger.debug(f"Raw LLM response: \n{response_text}")

        try:
            # Attempt to parse YAML response for tool call
            # LLMs might wrap YAML in ```yaml ... ```
            cleaned_response_text = response_text.strip()
            if cleaned_response_text.startswith("```yaml"):
                cleaned_response_text = cleaned_response_text[7:]
                if cleaned_response_text.endswith("```"):
                    cleaned_response_text = cleaned_response_text[:-3]
                cleaned_response_text = cleaned_response_text.strip()

            logger.debug(f"Attempting to parse LLM response as YAML. Cleaned text for YAML load: '{cleaned_response_text}'")
            tool_call_data = yaml.safe_load(cleaned_response_text)
            logger.debug(f"Parsed YAML data (tool_call_data): {tool_call_data}")

            # Check for the nested 'tool_call' structure
            if isinstance(tool_call_data, dict) and \
               "tool_call" in tool_call_data and \
               isinstance(tool_call_data["tool_call"], dict) and \
               "name" in tool_call_data["tool_call"] and \
               "arguments" in tool_call_data["tool_call"] and \
               isinstance(tool_call_data["tool_call"]["arguments"], dict):

                tool_name = tool_call_data["tool_call"]["name"]
                tool_input_dict = tool_call_data["tool_call"]["arguments"]
                logger.info(f"LLM decided to use tool: {tool_name} with input: {tool_input_dict}")

                tool_result = await execute_tool_async(tool_name, tool_input_dict)
                logger.info(f"Result from tool '{tool_name}': {tool_result}")

                current_messages.append({"role": "assistant", "content": cleaned_response_text}) # LLM's tool request (YAML)
                current_messages.append({"role": "user", "content": f"Tool '{tool_name}' result: {tool_result}"})
                logger.debug(f"Messages after tool execution: {current_messages}")

                if attempt == max_tool_attempts - 1:
                    logger.warning("Max tool attempts reached, LLM still trying to use tools. Forcing final answer generation.")
                    final_prompt_messages = current_messages + [
                        {"role": "system", "content": "You have reached the maximum tool use attempts. Please provide the final answer to the user based on the information gathered so far."}
                    ]
                    final_answer = await asyncio.to_thread(call_llm, final_prompt_messages)
                    logger.info(f"Final answer after max tool attempts: {final_answer}")
                    current_messages.append({"role": "assistant", "content": final_answer})
                    return final_answer, current_messages
            else:
                # If YAML is valid but not a tool call, or not a dict, assume it's the final answer.
                logger.info("LLM response is valid YAML but not a recognized tool call, or not a dictionary. Treating as final text answer.")
                current_messages.append({"role": "assistant", "content": response_text}) # Store original response
                return response_text, current_messages
        except yaml.YAMLError:
            # If not valid YAML, assume it's the final answer
            logger.info("LLM response is not valid YAML. Treating as final text answer.")
            current_messages.append({"role": "assistant", "content": response_text})
            return response_text, current_messages
        except Exception as e:
            logger.error(f"Unexpected error processing LLM response: {e}", exc_info=True)
            current_messages.append({"role": "assistant", "content": f"Error processing response: {e}"})
            return f"Error processing response: {e}", current_messages


    logger.warning("Max tool attempts reached. Generating a fallback response.")
    # If loop finishes, it means max_tool_attempts were made trying to use tools,
    # but the last attempt didn't result in a direct answer (it was another tool call that hit max_attempts).
    # We need to make one last call to LLM to synthesize an answer.
    final_fallback_prompt_messages = current_messages + [
        {"role": "system", "content": "You have reached the maximum tool use attempts. Please provide the final answer to the user based on the information gathered so far, or state that you couldn't complete the request."}
    ]
    final_fallback_answer = await asyncio.to_thread(call_llm, final_fallback_prompt_messages)
    logger.info(f"Final fallback answer after max tool attempts: {final_fallback_answer}")
    current_messages.append({"role": "assistant", "content": final_fallback_answer})
    return final_fallback_answer, current_messages