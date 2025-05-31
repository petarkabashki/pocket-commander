import json # For parsing in test block, and for LLM communication (though YAML is preferred)
import asyncio
import logging
from ..pocketflow import AsyncNode # Base class for nodes

# Import the main LLM call logic from the new utility file
from ..utils.tool_llm_utils import llm_call_with_tool_support_async

# Configure logging for this node
# Standard logging setup
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] # Ensures logs go to stdout/stderr
)
logger = logging.getLogger(__name__)

class ToolEnabledLLMNode(AsyncNode):
    def __init__(self, max_tool_attempts=3, max_retries=1, wait=0): # PocketFlow max_retries defaults to 1 (no retry)
        super().__init__(max_retries=max_retries, wait=wait)
        self.max_tool_attempts = max_tool_attempts
        logger.info(f"ToolEnabledLLMNode initialized. Max tool attempts: {self.max_tool_attempts}, Max retries: {self.max_retries}, Wait: {self.wait}s")

    async def prep_async(self, shared):
        """
        Prepares the input for the LLM call.
        Expects 'query' and optionally 'messages' in shared store.
        """
        logger.debug(f"Prep: Current shared state: {shared}")
        query = shared.get('query')
        if not query:
            logger.error("Prep: 'query' not found in shared store.")
            raise ValueError("'query' is required in shared store for ToolEnabledLLMNode.")

        # Initialize messages if not present or not a list
        messages = shared.get('messages', [])
        if not isinstance(messages, list):
            logger.warning(f"Prep: 'messages' in shared store was not a list (type: {type(messages)}). Resetting to empty list with query.")
            messages = []

        # Ensure the current user query is the last user message if not already part of a sequence
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != query:
             # If messages is empty, or last message is not the current user query, add it.
            messages.append({"role": "user", "content": query})
            logger.debug(f"Prep: Added/updated user query to messages list.")
        
        logger.info(f"Prep: Prepared messages for query: '{query}'")
        # Pass along the prepared messages and max_tool_attempts
        return {"messages": messages, "max_tool_attempts": self.max_tool_attempts}

    async def exec_async(self, prep_res):
        """
        Executes the LLM call with tool support using the prepared messages.
        """
        messages = prep_res["messages"]
        max_attempts = prep_res["max_tool_attempts"]
        logger.info(f"Exec: Starting LLM call with tool support. Max tool attempts: {max_attempts}")
        
        final_answer, updated_messages = await llm_call_with_tool_support_async(
            initial_messages=messages, # Pass only user/assistant/tool messages, system prompt added by helper
            max_tool_attempts=max_attempts
        )
        logger.info(f"Exec: LLM call completed. Final answer: '{final_answer}'")
        return {"final_answer": final_answer, "updated_messages": updated_messages}

    async def post_async(self, shared, prep_res, exec_res):
        """
        Post-processes the result, updating the shared store.
        """
        logger.debug(f"Post: Current shared state before update: {shared}")
        final_answer = exec_res.get("final_answer", "Error: No final answer found.")
        updated_messages = exec_res.get("updated_messages", [])

        shared['final_answer'] = final_answer
        shared['messages'] = updated_messages # Update messages with the full conversation history

        logger.info(f"Post: Updated shared store with final_answer: '{final_answer}' and conversation history.")
        logger.debug(f"Post: Final shared state: {shared}")
        
        # Decide the next action based on whether a final answer was successfully generated.
        if "Error:" in final_answer : # Basic error check
            logger.warning("Post: Final answer indicates an error. Routing to 'error' if defined, else 'default'.")
            return "error_occurred" # Or a more specific error action
        return "answer_provided" # Default action for success

# Example of how this node might be used in a flow (conceptual)
if __name__ == '__main__':
    # This is for basic testing of the node structure, not a full flow run.
    async def run_test():
        logger.info("--- Starting ToolEnabledLLMNode Test ---")
        
        # Mock PocketFlow shared store
        shared_data = {
            'query': "What's the weather like in London and what is the current price of NVDA stock?",
            # 'query': "What is the Nobel Prize in Physics 2024 and current time in London?",
            # 'query': "Tell me a joke.", # Test non-tool use
            'messages': [] # Start with empty message history
        }

        node = ToolEnabledLLMNode(max_tool_attempts=3)

        try:
            # Simulate node execution steps
            logger.info("--- Testing prep_async ---")
            prep_result = await node.prep_async(shared_data)
            logger.info(f"prep_async result: {prep_result}")

            logger.info("--- Testing exec_async ---")
            # In a real flow, call_llm would be a real LLM call.
            # For this test, ensure call_llm in utils.call_llm can handle being called
            # or mock it if it makes external calls you want to avoid in this test.
            exec_result = await node.exec_async(prep_result)
            logger.info(f"exec_async result: {exec_result}")

            logger.info("--- Testing post_async ---")
            next_action = await node.post_async(shared_data, prep_result, exec_result)
            logger.info(f"post_async next_action: {next_action}")

            logger.info(f"Final shared_data: {json.dumps(shared_data, indent=2)}")

        except Exception as e:
            logger.error(f"Error during node test: {e}", exc_info=True)
        
        logger.info("--- ToolEnabledLLMNode Test Finished ---")

    # To run the test:
    # Ensure call_llm in pocket_commander/utils/call_llm.py is set up
    # (e.g., it's a mock or configured with an API key if it makes real calls)
    # Then run this script.
    # Example mock call_llm in pocket_commander/utils/call_llm.py for testing:
    # MOCK_LLM_RESPONSES = [
    #     # First call: decides to use get_weather for London
    #     """```yaml
    #     tool_name: get_weather
    #     tool_input:
    #       city: London
    #     ```""",
    #     # Second call: after weather, decides to use get_stock_price for NVDA
    #     """```yaml
    #     tool_name: get_stock_price
    #     tool_input:
    #       symbol: NVDA
    #     ```""",
    #     # Third call: provides final answer
    #     "The weather in London is partly cloudy, 15°C. The stock price for NVDA is $120.50."
    # ]
    # MOCK_LLM_CALL_COUNT = 0
    # def call_llm(messages: list):
    #     global MOCK_LLM_CALL_COUNT
    #     print(f"Mock LLM called with messages: {messages[-2:]}") # print last few messages
    #     response = MOCK_LLM_RESPONSES[MOCK_LLM_CALL_COUNT % len(MOCK_LLM_RESPONSES)]
    #     MOCK_LLM_CALL_COUNT += 1
    #     return response
    
    asyncio.run(run_test())