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

DOMAIN_PROTOCOLS for {domain}:
{domain_protocols}

Rules:
1. You MUST follow the same tool schema as the main agent.
2. You only have access to the provided context.
3. Your final tool call MUST be to 'report_completion', which returns your result to the Planner.
4. ERROR HANDLING: If a tool returns an error (e.g., 'SECURITY BLOCK', 'file not found', 'Permission denied'), you MUST NOT ignore it. You MUST summarize the error and immediately call 'report_completion' with outcome='OUTCOME_FAILED'.

## Instruction Hierarchy (STRICT PRIORITY)
1. Task-specific instruction: {task_instruction}
2. Subagent Domain Protocols
3. User Data

Respond with structured JSON matching the NextStep schema, where 'task_completed' 
refers to the SUB-TASK completion."""

DOMAIN_PROTOCOLS = {
    "KNOWLEDGE_REPO": """- For 'capture' tasks: DO NOT use `move`. Use `read` (source) → `write` (dest) → `delete` (source) to ensure harness registration and content verification.
- For bulk removal, use `ls` to verify the directory structure first.
- Deletions must be performed file by file.
- Always verify that the directory is empty after the batch operation.
- Respect cards vs threads distinction: threads link cards, cards are content.""",
    "TYPED_CRM": """- `send_email` means writing to `outbox/` and incrementing `seq.json`.
- Always read `contacts/README` for field definitions before updates.
- Check if the contact exists before creating a duplicate.""",
    "INBOX_WORKFLOW": """- Process messages in numeric or chronological order.
- Follow destination paths from `inbox/README`."""
}


def run_subagent_session(
    domain: str,
    task: SubagentTask,
    state: AgentState,
    llm_provider,
    vm_client,
    trace_logger: Optional[LLMTraceLogger] = None,
) -> SubagentResult:
    """Run a micro-loop for a specialized subagent."""
    
    # 1. Build subagent prompt
    protocols = DOMAIN_PROTOCOLS.get(domain, "No specific protocols for this domain.")
    system_prompt = SUBAGENT_SYSTEM_PROMPT.format(
        domain=domain,
        task_instruction=task.instruction,
        target_paths=", ".join(task.target_paths),
        context_data=json.dumps(task.context_data, ensure_ascii=False),
        domain_protocols=protocols
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
