# Plan: Creating the "Tool Agent" Agent

This document outlines the plan to transform the existing `pocket_commander/flows/tool_flow.py` into a new, fully integrated "Tool Agent" agent within the Pocket Commander system.

## Rationale for Approach: Composition

The chosen approach is **composition**. The new `ToolAgentAgent` class will *contain* and *use* an `AsyncFlow` instance derived from the logic in `tool_flow.py`.

Reasons:
-   `tool_flow.py` (via `create_tool_enabled_flow`) provides a complete, runnable PocketFlow `AsyncFlow` object.
-   An agent's role is to manage user interaction and orchestrate a PocketFlow. The agent *has a* flow, rather than *being a* flow.
-   This maintains a clear separation of concerns:
    -   The agent class handles `TerminalApp` interactions and conversation lifecycle.
    -   The `AsyncFlow` instance encapsulates the agentic operations.
-   Direct inheritance from `AsyncFlow` would be a structural mismatch. Mixins are better for adding shared, specific behaviors, not for incorporating a complete, self-contained flow.

## Phase 1: Python Implementation

### 1. Create New Agent Directory Structure
-   Create directory: `pocket_commander/agents/tool_agent/`
-   Create empty file: `pocket_commander/agents/tool_agent/__init__.py`
-   Create main flow file: `pocket_commander/agents/tool_agent/tool_agent_flow.py`

### 2. Implement `ToolAgentAgent` in `tool_agent_flow.py`

This file houses the core logic for the new agent.
-   It defines a `create_tool_enabled_flow` function (adapted from the original `tool_flow.py`) that constructs an `AsyncFlow` using `InitialQueryNode`, `ToolEnabledLLMNode`, and `PrintFinalAnswerNode`.
-   It defines the `ToolAgentAgent` class:
    -   `__init__`: Initializes `agent_config`, `terminal_app_instance`, `logger`, a `shared_data_template` (including context from `agent_config`), and creates the `agent_pocket_flow` using `create_tool_enabled_flow`.
    -   `handle_input`: Takes user input, prepares `current_shared_data`, runs the `agent_pocket_flow` via an `AsyncFlowManager`, and handles displaying the final answer if not printed directly by `PrintFinalAnswerNode`. Includes basic error handling.
-   It defines a factory function `create_tool_agent_agent(agent_config, terminal_app_instance)` that returns an instance of `ToolAgentAgent`.

### 3. Implement `__init__.py` for the Agent
File: `pocket_commander/agents/tool_agent/__init__.py`
-   This file makes the directory a Python package.
-   It imports `create_tool_agent_agent` from `.tool_agent_flow`.
-   It defines the `get_flow(agent_config, terminal_app_instance)` function, which is called by the terminal interface to load the agent, and returns the result of `create_tool_agent_agent`.

### 4. Refactor `PrintFinalAnswerNode`
File: `pocket_commander/nodes/print_final_answer_node.py`
-   The `PrintFinalAnswerNode` is modified to be more flexible.
-   Its `__init__` method accepts `terminal_app_instance` and `prints_directly` parameters.
-   The `exec_async` method (part of the `AsyncNode` structure along with `prep_async` and `post_async`) handles processing the final answer. If `prints_directly` is true and `terminal_app_instance` is available, it displays the output directly. Otherwise, it ensures the `final_answer` is correctly set in `shared_data` for the agent to handle.
-   The `post_async` method updates the `messages` in `shared_data` with a system note about the answer processing.

## Phase 2: YAML Configuration

Update the project's main configuration file: `pocket_commander.conf.yaml`. Add a new entry under `terminal_agents` for the "tool-agent".

```yaml
# In pocket_commander.conf.yaml

# ... (llm-profiles section remains the same) ...

terminal_agents:
  main:
    flow_module: pocket_commander.agents.main
    llm_profile: dev
    description: "Default interaction agent."
  composer:
    flow_module: pocket_commander.agents.composer
    llm_profile: anthro
    description: "Agent for composing complex prompts or documents."
  tool-agent: # New agent configuration
    flow_module: pocket_commander.agents.tool_agent
    llm_profile: default # Or any other suitable profile
    description: "Interactive tool-enabled agent for complex tasks."
    # Specific configurations for this agent can be added here
    # and accessed via 'self.agent_config' in ToolAgentAgent's __init__
    initial_context: "You are a helpful and resourceful AI assistant, ready to use tools."
    # Note: 'roleDefinition', 'whenToUse', 'groups', 'customInstructions' as seen in .rooagents
    # are not standard for project-defined agents in pocket_commander.conf.yaml.
    # Such behavioral definitions are typically part of the agent's Python logic or its LLM prompts.
```

## Phase 3: Testing

1.  Ensure all dependencies are installed/updated.
2.  Run Pocket Commander.
3.  Verify the "Tool Agent" agent appears in the list of available agents (e.g., via a `/agents` command if available, or by checking logs).
4.  Switch to the agent: `/agent tool-agent`.
5.  Test with various queries:
    -   Simple questions (to see if LLM responds directly).
    -   Queries that should trigger configured tools (this depends on how `ToolEnabledLLMNode` is set up to discover and use tools).
    -   Queries that might involve multi-step reasoning.
6.  Check for errors in the terminal and logs.
7.  Verify that the `PrintFinalAnswerNode` behavior (direct printing vs. agent printing) is as expected based on its configuration in `tool_agent_flow.py`.

This plan provides a structured approach to developing and integrating the new "Tool Agent" agent.