"""Subagent Node — domain-specific task execution.

Maintains a cleaner context for the Planner by delegating "hands-on" 
operations to specialized sub-orchestrators.
"""

import json
from typing import Optional, List
from agents.types import AgentState, SubagentTask, SubagentResult, NextStep
from agents.tool_executor import execute_tool
from llm_logger import LLMTraceLogger

# Subagent prompt template
SUBAGENT_SYSTEM_PROMPT = """\
You are a specialized subagent for the domain: {domain}.
Your task: {task_instruction}

Target Paths: {target_paths}
Additional Context: {context_data}

## WORKSPACE RULES
{workspace_rules}

Rules:
1. You MUST follow the same tool schema as the main agent.
2. You only have access to the provided context.
3. Your final tool call MUST be to 'report_completion', which returns your result to the Planner.
4. ERROR HANDLING: If a tool returns an error (e.g., 'SECURITY BLOCK', 'file not found', 'Permission denied'), you MUST NOT ignore it. You MUST summarize the error and immediately call 'report_completion' with outcome='OUTCOME_FAILED'.
5. Follow the workspace rules above — they define how this workspace operates.

Respond with structured JSON matching the NextStep schema, where 'task_completed'
refers to the SUB-TASK completion."""


def run_subagent_session(
    domain: str,
    task: SubagentTask,
    state: AgentState,
    llm_provider,
    vm_client,
    trace_logger: Optional[LLMTraceLogger] = None,
) -> SubagentResult:
    """Run a micro-loop for a specialized subagent."""
    
    # 1. Build subagent prompt with workspace rules from state
    ws_rules = state.get("workspace_rules", {})
    rules_text = "\n".join(
        f"--- {path} ---\n{content[:500]}"
        for path, content in ws_rules.items()
        if path != "tree_process"
    )
    system_prompt = SUBAGENT_SYSTEM_PROMPT.format(
        domain=domain,
        task_instruction=task.instruction,
        target_paths=", ".join(task.target_paths),
        context_data=json.dumps(task.context_data, ensure_ascii=False),
        workspace_rules=rules_text or "No workspace rules loaded.",
    )
    
    sub_history = []
    max_sub_iterations = 20
    
    if trace_logger:
        trace_logger.log_agent_event(
            agent_name=f"subagent_{domain}",
            event="session_started",
            details={
                "instruction": task.instruction,
                "targets": task.target_paths
            }
        )

    for i in range(max_sub_iterations):
        messages = [{"role": "system", "content": system_prompt}] + sub_history
        
        try:
            next_step = llm_provider.complete_as(messages, NextStep)
        except Exception as e:
            return SubagentResult(success=False, message=f"Subagent LLM error: {str(e)}")

        # Check if task completed via report_completion
        if next_step.function.tool == "report_completion":
            comp = next_step.function
            return SubagentResult(
                success=(comp.outcome == "OUTCOME_OK"),
                message=comp.message,
                grounding_refs=comp.grounding_refs
            )

        # Execute tool within sub-loop
        tool_name = next_step.function.tool
        tool_args = next_step.function.model_dump()
        tool_args.pop("tool", None)
        
        result_text = execute_tool(
            {"name": tool_name, "arguments": tool_args},
            vm_client,
            trace_logger,
            step_name=f"subagent_{domain}_step_{i+1}"
        )

        sub_history.append({"role": "assistant", "content": next_step.current_state, "tool_calls": [{"id": f"sub_{i}", "type": "function", "function": {"name": tool_name, "arguments": json.dumps(tool_args)}}]})
        sub_history.append({"role": "tool", "content": result_text, "tool_call_id": f"sub_{i}"})

    return SubagentResult(success=False, message="Subagent reached max iterations.")
