import yaml
import os
import warnings
import copy
import time
import asyncio
import inspect # For extracting metadata
from ..pocketflow import *


# Define a simple flow
from ..nodes.initial_query_node import InitialQueryNode
from ..nodes.print_final_answer_node import PrintFinalAnswerNode
from ..nodes.tool_enabled_llm_node import ToolEnabledLLMNode

def create_tool_enabled_flow(shared_data):
    initial_query = InitialQueryNode()
    llm_agent = ToolEnabledLLMNode(max_retries=2, wait=1) # Allow retries for LLM calls/tool execution
    final_answer_printer = PrintFinalAnswerNode()

    # Define the flow:
    # 1. Start with the initial query
    initial_query >> llm_agent

    # 2. If the LLM decides to call a tool or needs to decide again after a tool, loop back to the LLM agent
    llm_agent - "llm_decide_next" >> llm_agent

    # 3. If the LLM provides a final answer, go to the node that prints it
    llm_agent - "answer_provided" >> final_answer_printer

    # 4. Handle potential errors (e.g., LLM output parsing failure)
    # In a real app, you might have a dedicated error handling node
    llm_agent - "error" >> final_answer_printer # Fallback to printing whatever is available or an error message

    return AsyncFlow(start=initial_query)


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()
    # Ensure you have a pocket_openskad.conf.yaml and environment variables set up.
    # Example pocket_openskad.conf.yaml content:
    # llm-profiles:
    #   default:
    #     provider: gemini
    #     model: gemini-1.5-flash-latest # or gpt-4o for openai, claude-3-opus-20240229 for anthropic
    #     api_key_name: GOOGLE_API_KEY # or OPENAI_API_KEY, ANTHROPIC_API_KEY

    # Set a dummy API key for demonstration if not using a real one
    # In a real scenario, you'd set this via environment variables or a secure config.
    # os.environ["GOOGLE_API_KEY"] = "YOUR_GEMINI_API_KEY_HERE" # Replace with your actual key

    shared_data = {
        "query": None, # Will be set by InitialQueryNode
        "context": "",
        "messages": [], # Now using 'messages' for conversation history
        "final_answer": None,
        "tool_result": None,
        # "action_history": [], # Removed
        # "last_llm_thinking": "" # Removed
    }

    print("Starting the tool-enabled LLM flow...")
    tool_flow = create_tool_enabled_flow()


    async def _orchestrate_flow():
        # Create a flow manager to orchestrate the flow
        flow_manager = AsyncFlowManager(await tool_flow)
        # Run the flow to process all nodes
        await flow_manager.run(shared_data)

    asyncio.run(_orchestrate_flow())

    print("\n--- Flow Execution Summary ---")
    print(f"Final Answer: {shared_data.get('final_answer', 'N/A')}")
    print("Conversation History (Messages):")
    for msg in shared_data.get("messages", []):
        print(f"  {msg['role'].upper()}: {msg['content']}")
