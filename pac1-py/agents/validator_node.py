"""Validator Node — ensures post-mutation invariants and minimal diffs.

Runs after any 'write', 'delete', or 'move' operation to ensure the repository remains consistent.
"""

from typing import List, Optional
from agents.types import AgentState, TaskModel
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from agents.pcm_helpers import safe_read_file
from llm_logger import LLMTraceLogger

def run_post_mutation_validation(
    state: AgentState,
    vm_client: PcmRuntimeClientSync,
    last_tool_call: dict,
    trace_logger: Optional[LLMTraceLogger] = None,
) -> List[str]:
    """Validate the state of the repository after a mutating action.
    
    Returns a list of warning messages if invariants are violated.
    """
    warnings = []
    task_model = state.get("task_model")

    tool_name = last_tool_call.get("name")
    args = last_tool_call.get("arguments", {})

    # Universal: check if modified path relates to the task
    if task_model and tool_name in ("write", "delete"):
        target_path = args.get("path", "")
        is_relevant = False

        # Check if any target entity appears in the path
        if any(entity.lower() in target_path.lower() for entity in task_model.target_entities):
            is_relevant = True

        # Check if the path is in a directory mentioned in workspace rules
        ws_rules = state.get("workspace_rules", {})
        for rule_path in ws_rules:
            if rule_path == "tree_process":
                continue
            # If the rule is about a directory that contains the target path
            rule_dir = "/".join(rule_path.split("/")[:-1]).lstrip("/")
            if rule_dir and rule_dir in target_path:
                is_relevant = True
                break

        if not is_relevant and "AGENTS.md" not in target_path:
            warnings.append(f"Minimal Diff Warning: Modification of '{target_path}' seems unrelated to the task.")

    if trace_logger and warnings:
        trace_logger.log_agent_event(
            agent_name="validator_node",
            event="validation_warnings",
            details={"warnings": warnings}
        )
        
    return warnings
