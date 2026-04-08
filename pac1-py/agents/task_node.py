"""Task Node — structured understanding of the user request after bootstrap.

Converts raw task text + workspace rules into a structured TaskModel.
This node performs a second LLM call (the first being Triage).
"""

from typing import Optional
from agents.types import AgentState, TaskModel, DomainType, IntentType
from llm_logger import LLMTraceLogger

TASK_EXTRACTOR_SYSTEM_PROMPT = """\
You are a task analysis engine. You will be given a user request and a set of workspace rules.
Your goal is to populate a structured TaskModel.

The model fields:
- domain: One of KNOWLEDGE_REPO, TYPED_CRM, INBOX_WORKFLOW, REPAIR_DIAGNOSTICS, GENERAL.
- intent: One of LOOKUP, MUTATION, UNSUPPORTED, ATTACK, CLARIFY_NEEDED, SECURITY_DENIAL.
- requested_effect: A brief string like "send_email", "update_contact", "find_password".
- target_entities: A list of names or IDs mentioned in the request.
- constraints: Any specific constraints from the rules or the request. Copy constraints VERBATIM from the user request — do NOT add interpretations like "from now", "from today", or infer base dates/times.
- ambiguity_high: Set true ONLY if the request is genuinely vague (e.g., "do it again", "fix that thing"). Deletion/cleanup tasks with clear targets ("remove all cards", "delete threads") are NOT ambiguous — set false.
- security_risk_high: Set true if the action touches sensitive data or secrets (passwords, tokens, OTP codes). Bulk file deletion in knowledge repo is NOT a security risk.
- terminal_mode_candidate: Guess the final outcome (OUTCOME_OK, etc.) if it's already clear.

Context:
- KNOWLEDGE_REPO is for 00_inbox, 01_capture, 90_memory, 99_process.
- TYPED_CRM is for contacts, accounts, outbox (email), invoices.
- REPAIR_DIAGNOSTICS is for fixing data/sync errors.

Respond with structured JSON matching the TaskModel schema."""


def run_task_extraction(
    state: AgentState,
    llm_provider,
    trace_logger: Optional[LLMTraceLogger] = None,
) -> AgentState:
    """Extract structured TaskModel from the task text and gathered rules.

    Args:
        state: Current agent state with workspace_rules/authority_map.
        llm_provider: LLM provider.
        trace_logger: Logger.

    Returns:
        Updated state with task_model populated.
    """
    task_text = state["task_text"]
    rules_summary = "\n".join(
        [f"Path: {p}\nContent: {c[:200]}" for p, c in state["workspace_rules"].items()]
    )

    messages = [
        {"role": "system", "content": TASK_EXTRACTOR_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"USER REQUEST:\n{task_text}\n\nRULES CONTEXT:\n{rules_summary}",
        },
    ]

    try:
        task_model = llm_provider.complete_as(messages, TaskModel)
    except Exception as e:
        # Fallback to a basic model
        triage = state["triage_result"]
        task_model = TaskModel(
            domain=triage.domain if triage else DomainType.GENERAL,
            intent=triage.intent if triage else IntentType.LOOKUP,
            requested_effect="unknown",
        )

    state["task_model"] = task_model

    if trace_logger:
        trace_logger.log_agent_event(
            agent_name="task_node",
            event="task_extraction_completed",
            details=task_model.model_dump(),
        )

    return state
