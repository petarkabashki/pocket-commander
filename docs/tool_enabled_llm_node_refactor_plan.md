# Refactoring Plan: `ToolEnabledLLMNode`

**Objective:** Make `ToolEnabledLLMNode` self-sufficient by internalizing tool-handling logic, directly using the core `call_llm` utility, and allowing instance-specific toolsets.

## Phase 1: Internalize Core Tooling Logic

1.  **Handle `available_tools` and `_execute_tool_async`:**
    *   The `ToolEnabledLLMNode.__init__` method will accept a new parameter `available_tools: Dict[str, Callable]`. This dictionary will be stored as `self.available_tools`. If no tools are provided, it could default to an empty dictionary.
    *   The logic from the `execute_tool_async` function (previously in `pocket_commander/utils/tool_llm_utils.py`) will be moved into `ToolEnabledLLMNode` as a private helper method (e.g., `async def _execute_tool_async(self, tool_name: str, tool_input_dict: dict)`). This method will use `self.available_tools`.

2.  **Integrate Prompt Construction:**
    *   `ToolEnabledLLMNode` will call `generate_tool_prompt_section` from `pocket_commander/utils/prompt_utils.py` within its `exec_async` method, passing `self.available_tools` to it.
    *   The system prompt (previously constructed within `llm_call_with_tool_support_async` in `pocket_commander/utils/tool_llm_utils.py`) will be constructed within the `exec_async` method of `ToolEnabledLLMNode`. This system prompt will incorporate the output of `generate_tool_prompt_section(self.available_tools)`.

3.  **Adapt `exec_async` Method:**
    *   This method will be significantly expanded to include the tool interaction loop.
    *   **Direct LLM Calls:** It will call `call_llm` from `pocket_commander/utils/call_llm.py` directly. Since `call_llm` is synchronous, it will be invoked using `await asyncio.to_thread(call_llm, current_messages, profile_name=self.llm_profile_name)`.
    *   **Tool Loop Logic:**
        *   Iterate up to `self.max_tool_attempts`.
        *   Construct messages including the system prompt and current conversation history.
        *   Call the LLM.
        *   Parse the LLM response for a YAML tool call (stripping ` ```yaml ` fences).
        *   If a valid tool call is found:
            *   Invoke the internal `_execute_tool_async` method.
            *   Append the assistant's tool request (YAML) and the user-role tool result to the message history.
            *   Continue the loop if `max_tool_attempts` is not reached.
            *   If `max_tool_attempts` is reached after a tool call, make a final LLM call instructing it to synthesize an answer.
        *   If the response is not a tool call (or YAML parsing fails), treat it as the final answer.
    *   The method will return the `final_answer` and the complete `updated_messages` list.

4.  **Update `__init__` Method:**
    *   Add a new parameter `llm_profile_name: str = "default"` to the `__init__` method to specify which LLM profile `call_llm` should use. Store this as `self.llm_profile_name`.
    *   Add the `available_tools: Dict[str, Callable]` parameter as described in point 1.

5.  **`prep_async` Method:**
    *   This method's current logic for preparing the initial `messages` list from `shared.get('query')` and `shared.get('messages', [])` remains largely suitable. It will continue to return `{"messages": messages, "max_tool_attempts": self.max_tool_attempts}`.

6.  **`post_async` Method:**
    *   This method's existing logic for updating the shared store with `final_answer` and `updated_messages` should still be appropriate.

## Phase 2: Refinement, Cleanup, and Testing

1.  **Imports:**
    *   Update imports in `pocket_commander/nodes/tool_enabled_llm_node.py` to include `call_llm` from `..utils.call_llm`, `generate_tool_prompt_section` from `..utils.prompt_utils`, and standard libraries like `yaml`, `json`, `inspect`, `asyncio`, `logging`, `Callable`, `Dict`.
    *   Remove the import of `llm_call_with_tool_support_async` from `..utils.tool_llm_utils`.

2.  **Cleanup `pocket_commander/utils/tool_llm_utils.py`:**
    *   Remove the `llm_call_with_tool_support_async` function.
    *   Remove `AVAILABLE_TOOLS` and `execute_tool_async` as their logic will be moved/adapted into the node.
    *   The `TOOL_USAGE_INSTRUCTIONS_PROMPT` global variable will no longer be needed there.
    *   This utility file might become very lean or potentially be removed if all its unique functionality is absorbed and not used elsewhere.

3.  **Testing:**
    *   Thoroughly update and run the test block within `pocket_commander/nodes/tool_enabled_llm_node.py`. Mocking `call_llm` will be essential for reliable unit testing without actual API calls.

## Visual Plan (Mermaid Diagram)

```mermaid
graph TD
    subgraph Original Structure
        direction LR
        TELN_Old(["ToolEnabledLLMNode\n(pocket_commander/nodes/tool_enabled_llm_node.py)"])
        ToolLLMUtils(["tool_llm_utils.py"])
        LLM_TS_Util(["llm_call_with_tool_support_async()\n(in tool_llm_utils.py)"])
        ExecTool_Util_Old(["execute_tool_async()\n(in tool_llm_utils.py)"])
        Tools_Old(["AVAILABLE_TOOLS\n(in tool_llm_utils.py)"])
        CallLLM_Util_Old(["call_llm()\n(utils/call_llm.py)"])
        PromptUtil_Old(["generate_tool_prompt_section()\n(utils/prompt_utils.py)"])

        TELN_Old -- calls --> LLM_TS_Util
        ToolLLMUtils --> LLM_TS_Util
        ToolLLMUtils --> ExecTool_Util_Old
        ToolLLMUtils --> Tools_Old
        LLM_TS_Util -- calls --> CallLLM_Util_Old
        LLM_TS_Util -- uses --> PromptUtil_Old
        LLM_TS_Util -- calls --> ExecTool_Util_Old
        ExecTool_Util_Old -- uses --> Tools_Old
    end

    subgraph New Structure
        direction LR
        TELN_New(["ToolEnabledLLMNode\n(pocket_commander/nodes/tool_enabled_llm_node.py)"])
        TELN_New_ExecAsync(["exec_async()\n(tool loop, YAML parsing)"])
        TELN_New_HelperExecTool(["_execute_tool_async()\n(internal helper)"])
        TELN_New_Tools(["self.available_tools\n(instance-specific, via __init__)"])

        CallLLM_Util_New(["call_llm()\n(utils/call_llm.py)"])
        PromptUtil_New(["generate_tool_prompt_section()\n(utils/prompt_utils.py)"])

        TELN_New --> TELN_New_ExecAsync
        TELN_New --> TELN_New_HelperExecTool
        TELN_New --> TELN_New_Tools
        TELN_New_ExecAsync -- "calls (via asyncio.to_thread)" --> CallLLM_Util_New
        TELN_New_ExecAsync -- uses --> PromptUtil_New
        TELN_New_ExecAsync -- calls --> TELN_New_HelperExecTool
        TELN_New_HelperExecTool -- uses --> TELN_New_Tools
    end

    style TELN_Old fill:#f9d,stroke:#333,stroke-width:1px
    style ToolLLMUtils fill:#f9d,stroke:#333,stroke-width:2px
    style LLM_TS_Util fill:#fcc,stroke:#333,stroke-width:1px
    style ExecTool_Util_Old fill:#fcc,stroke:#333,stroke-width:1px
    style Tools_Old fill:#fcc,stroke:#333,stroke-width:1px

    style TELN_New fill:#dfd,stroke:#333,stroke-width:2px
    style TELN_New_ExecAsync fill:#cfc,stroke:#333,stroke-width:1px
    style TELN_New_HelperExecTool fill:#cfc,stroke:#333,stroke-width:1px
    style TELN_New_Tools fill:#cfc,stroke:#333,stroke-width:1px

    note right of ToolLLMUtils: This file will be significantly reduced or removed.