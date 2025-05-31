# pocket_commander/modes/tool_agent/tool_agent_flow.py
import copy
from pocket_commander.pocketflow import AsyncFlow, AsyncFlowManager, BaseNode 
from pocket_commander.nodes.initial_query_node import InitialQueryNode
from pocket_commander.nodes.tool_enabled_llm_node import ToolEnabledLLMNode
from pocket_commander.nodes.print_final_answer_node import PrintFinalAnswerNode

# Define the create_tool_enabled_flow function (adapted from the original tool_flow.py)
def create_tool_enabled_flow(shared_data_template, terminal_app_instance=None):
    initial_query = InitialQueryNode()
    llm_agent = ToolEnabledLLMNode(max_retries=2, wait=1)
    # Pass terminal_app_instance for direct printing by PrintFinalAnswerNode
    final_answer_printer = PrintFinalAnswerNode(terminal_app_instance=terminal_app_instance, prints_directly=True)

    # Define the flow connections
    initial_query >> llm_agent
    llm_agent - "llm_decide_next" >> llm_agent
    llm_agent - "answer_provided" >> final_answer_printer
    llm_agent - "error" >> final_answer_printer # Fallback for errors

    # The AsyncFlow now takes the shared_data_template
    return AsyncFlow(start=initial_query, shared_data_template=shared_data_template)


class ToolAgentMode:
    def __init__(self, mode_config, terminal_app_instance):
        self.mode_config = mode_config
        self.terminal_app = terminal_app_instance
        self.logger = self.terminal_app.console # Assuming console is the logger

        # Define the initial structure for shared_data for this mode
        self.shared_data_template = {
            "query": None,
            "context": self.mode_config.get("initial_context", ""), 
            "messages": [], # For conversation history
            "final_answer": None,
            "tool_result": None, # For results from tool executions
        }
        
        # Create the PocketFlow instance for this mode
        self.agent_pocket_flow = create_tool_enabled_flow(self.shared_data_template, self.terminal_app)

        self.terminal_app.display_output(
            f"Tool Agent Mode initialized. Description: {self.mode_config.get('description', 'Interactive tool-enabled agent.')}",
            style="dim"
        )

    async def handle_input(self, user_input: str):
        current_shared_data = copy.deepcopy(self.shared_data_template)
        # To maintain conversation history across multiple handle_input calls:
        # current_shared_data["messages"] = self.shared_data_template["messages"] # This would make messages persistent
        # For a fresh message list per input, the deepcopy is fine.
        # If messages are to be appended, then self.shared_data_template["messages"] should be updated after each run.

        current_shared_data["query"] = user_input 

        flow_manager = AsyncFlowManager(self.agent_pocket_flow)
        
        try:
            await flow_manager.run(current_shared_data) 
            
            final_answer_node_instance = self.agent_pocket_flow.get_node_by_class(PrintFinalAnswerNode)
            node_prints_directly = False
            if final_answer_node_instance and hasattr(final_answer_node_instance, 'prints_directly'):
                node_prints_directly = final_answer_node_instance.prints_directly

            if not node_prints_directly and "final_answer" in current_shared_data and current_shared_data["final_answer"] is not None:
                self.terminal_app.display_output(
                    f"Agent: {current_shared_data['final_answer']}", style="bold green"
                )
            
            # If conversation history is maintained:
            # self.shared_data_template["messages"] = current_shared_data.get("messages", [])


        except Exception as e:
            self.logger.print(f"Error in Tool Agent Mode flow: {e}", style="bold red")
            self.terminal_app.display_output(
                "An error occurred while processing your request.", style="bold red"
            )

# Factory function required by the mode loading mechanism
def create_tool_agent_mode(mode_config, terminal_app_instance):
    return ToolAgentMode(mode_config, terminal_app_instance)