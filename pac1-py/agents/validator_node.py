"""Validator Node — ensures post-mutation invariants and minimal diffs.

Runs after any 'write', 'delete', or 'move' operation to ensure the repository remains consistent.
"""

from typing import List, Optional
from agents.types import AgentState, TaskModel, DomainType
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
    domain = task_model.domain if task_model else DomainType.GENERAL
    
    tool_name = last_tool_call.get("name")
    args = last_tool_call.get("arguments", {})
    
    # 1. CRM Invariants: outbox + seq.json
    if domain == DomainType.TYPED_CRM and tool_name == "write":
        path = args.get("path", "")
        if "outbox/" in path:
            # Check if seq.json exists and if it was read or updated recently
            # Ideally, we should check if it was updated, but for now we look for it.
            seq_content = safe_read_file(vm_client, "outbox/seq.json")
            if seq_content is None:
                warnings.append("CRM Warning: outbox/seq.json is missing but a new email was written.")
            
    # 2. Minimal Diff: check if the path is related to the task
    if task_model and tool_name in ("write", "delete"):
        target_path = args.get("path", "")
        # Very crude check: is the path mentioned in the task or domain?
        is_relevant = False
        if any(entity.lower() in target_path.lower() for entity in task_model.target_entities):
            is_relevant = True
        if domain == DomainType.TYPED_CRM and any(p in target_path for p in ("contacts", "accounts", "outbox", "invoices")):
            is_relevant = True
        if domain == DomainType.KNOWLEDGE_REPO and any(p in target_path for p in ("00_inbox", "01_capture", "90_memory", "99_process")):
            is_relevant = True
            
        if not is_relevant and "AGENTS.md" not in target_path:
            warnings.append(f"Minimal Diff Warning: Modification of '{target_path}' seems unrelated to the task.")

    if trace_logger and warnings:
        trace_logger.log_agent_event(
            agent_name="validator_node",
            event="validation_warnings",
            details={"warnings": warnings}
        )
        
    return warnings
