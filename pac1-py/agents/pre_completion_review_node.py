"""Pre-Completion Review Node — verify before submitting.

One LLM call that checks:
- All entities resolved?
- Verification checklist passed?
- Scope boundaries respected?
- Answer is correct?

Runs AFTER execution agent reports completion, BEFORE sending answer to PCM.
"""

from typing import Optional, List

from agents.types import (
    AgentState,
    StrategicAnalysis,
    PreCompletionReview,
    TrackedEntity,
)
from llm_logger import LLMTraceLogger


PRE_COMPLETION_REVIEW_PROMPT = """\
You are a quality reviewer for an AI agent. The agent has completed a task and wants to submit its answer.

Your job: review the execution against the strategic analysis and determine if the answer is ready.

## Check these:

1. **Entity Resolution**: Are ALL entities in the entity_graph resolved to authoritative files?
   - Every person, account, record mentioned should have resolved_file set
   - "unresolved" entities are a BLOCKER — the agent must find their records first

2. **Verification Checklist**: Have all checklist items been addressed?
   - "pending" items are a BLOCKER
   - "failed" items need explanation
   - "skipped" items need justification

3. **Scope Respect**: Were scope boundaries respected?
   - Check execution_history for any writes to files_must_not_touch
   - Check that only files in files_may_create/modify were changed

4. **Answer Quality**: Is the answer correct and complete?
   - Does it match what the task asked for?
   - Are grounding_refs complete (all relevant files included)?

If ANY check fails, set approved=false and list the specific issues.
If ALL checks pass, set approved=true.

Respond with JSON matching the PreCompletionReview schema."""


def run_pre_completion_review(
    state: AgentState,
    final_answer: str,
    proposed_outcome: str,
    grounding_refs: List[str],
    llm_provider,
    trace_logger: Optional[LLMTraceLogger] = None,
) -> PreCompletionReview:
    """Review the execution before submitting to PCM.

    Returns:
        PreCompletionReview with approved flag and issues list.
    """
    analysis = state.get("strategic_analysis")
    if not analysis:
        # No strategic analysis — approve by default
        return PreCompletionReview(
            all_entities_resolved=True,
            checklist_passed=True,
            scope_respected=True,
            approved=True,
        )

    # Build execution summary from conversation history
    execution_summary = []
    for msg in state["conversation_history"]:
        if msg["role"] == "assistant":
            execution_summary.append(f"ACTION: {msg.get('content', '')[:200]}")
        elif msg["role"] == "tool":
            execution_summary.append(f"RESULT: {msg.get('content', '')[:200]}")
    exec_text = "\n".join(execution_summary[-20:])  # Last 20 entries

    # Entity graph from latest scratchpad
    entity_graph = state["scratchpad"].entity_graph
    entity_text = "\n".join(
        f"- {e.entity_type}: {e.identifier} → {e.status} ({e.resolved_file or 'NO FILE'})"
        for e in entity_graph
    )

    # Checklist
    checklist_text = "\n".join(
        f"- [{v.status}] {v.check} (source: {v.source_rule})"
        for v in analysis.verification_checklist
    )

    # Scope
    scope = analysis.scope_boundary

    messages = [
        {"role": "system", "content": PRE_COMPLETION_REVIEW_PROMPT},
        {"role": "user", "content": (
            f"PROPOSED ANSWER: {final_answer}\n"
            f"PROPOSED OUTCOME: {proposed_outcome}\n"
            f"GROUNDING REFS: {', '.join(grounding_refs)}\n\n"
            f"ENTITY GRAPH:\n{entity_text or '(empty)'}\n\n"
            f"VERIFICATION CHECKLIST:\n{checklist_text or '(empty)'}\n\n"
            f"SCOPE BOUNDARY:\n"
            f"  may_create: {scope.files_may_create}\n"
            f"  may_modify: {scope.files_may_modify}\n"
            f"  must_not_touch: {scope.files_must_not_touch}\n\n"
            f"EXECUTION HISTORY (last 20):\n{exec_text}"
        )},
    ]

    try:
        review = llm_provider.complete_as(messages, PreCompletionReview)
    except Exception as e:
        if trace_logger:
            trace_logger.log_agent_event(
                agent_name="pre_completion_review",
                event="review_failed",
                details={"error": str(e)},
            )
        # On failure, approve to not block
        return PreCompletionReview(
            all_entities_resolved=True,
            checklist_passed=True,
            scope_respected=True,
            approved=True,
        )

    if trace_logger:
        trace_logger.log_agent_event(
            agent_name="pre_completion_review",
            event="review_completed",
            details={
                "approved": review.approved,
                "issues": review.issues,
                "entities_resolved": review.all_entities_resolved,
                "checklist_passed": review.checklist_passed,
                "scope_respected": review.scope_respected,
            },
        )

    return review
