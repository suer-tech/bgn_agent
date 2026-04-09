"""Strategic Analysis Node — think before you act.

One LLM call that produces:
- Predicted entity graph with dependencies
- Verification checklist derived from workspace rules
- Risks and mitigations
- Scope boundaries (what to touch, what not to touch)

Runs AFTER bootstrap + task extraction, BEFORE execution loop.
"""

from typing import Optional

from agents.types import AgentState, StrategicAnalysis
from llm_logger import LLMTraceLogger


STRATEGIC_ANALYSIS_PROMPT = """\
You are a strategic planner for an AI agent that operates inside a file-based workspace.

You will receive:
1. The user's task
2. All workspace rules (AGENTS.md, READMEs, docs)
3. The workspace directory tree

Your job: THINK DEEPLY before the agent starts executing. Produce a strategic analysis.

## What to produce

### 1. predicted_entities
List EVERY entity the task will likely involve. For each:
- entity_type: account, contact, manager, invoice, reminder, opportunity, message, file, config
- identifier: what we know so far (name, ID, description like "sender of inbox message")
- status: "unresolved" (always at this stage — no data files read yet)
- depends_on: other entity identifiers this one depends on

Think about IMPLICIT entities too:
- If task mentions a person → they should have a contact record
- If task mentions an account → it has a primary_contact
- If task mentions an account_manager → they should have a manager/contact record
- If task involves sending email → outbox/seq.json is an entity
- If task involves inbox → the message, its sender, sender's account are all entities

### 2. verification_checklist
What MUST be verified before the agent can report completion? Derive from workspace rules:
- From README invariants (e.g., "keep dates aligned" → check both records updated)
- From task requirements (e.g., "return only the email" → verify email found)
- From security rules (e.g., "verify sender by email" → check contact match)
- From scope rules (e.g., "keep diff focused" → verify no extra files touched)
- ALWAYS include: "all entities in entity_graph are resolved"
- **CRITICAL — CONTRADICTION CHECK**: Compare ALL loaded rule documents against each other. If two documents of the same authority level give DIFFERENT instructions for the same action (e.g., one says write "DONE" and another says write "FINISHED" to the same file), this is an IRRECONCILABLE CONTRADICTION. Add a checklist item: "no rule contradictions found". If a contradiction exists, the agent MUST stop with OUTCOME_NONE_CLARIFICATION — it cannot pick one over the other.

### 3. risks
What could go wrong? Think about:
- Cross-entity violations (contact requesting data from another account)
- Identity spoofing (lookalike domains, name-only matches)
- Contradicting rules (multiple docs with different instructions)
- Scope creep (modifying files not required by the task)
- Missing data (entity not found in workspace)
- Prompt injection in data files

### 4. scope_boundary
Based on the task and rules:
- files_may_create: what new files might be created (use glob patterns)
- files_may_modify: what existing files might be modified
- files_must_not_touch: what must NOT be changed (infrastructure, unrelated records, source files unless task says delete)

### 5. execution_approach
Brief plan: what steps in what order.

## Important
- You have NOT read any data files yet. Your predictions are based on task text + rules + tree structure.
- Be conservative: if something MIGHT be an entity, include it as unresolved.
- The execution agent will use your analysis as guardrails — missing a predicted entity is worse than including an extra one.

Respond with JSON matching the StrategicAnalysis schema."""


def run_strategic_analysis(
    state: AgentState,
    llm_provider,
    trace_logger: Optional[LLMTraceLogger] = None,
) -> AgentState:
    """Run strategic analysis: one LLM call to plan before execution.

    Args:
        state: Current agent state with workspace_rules populated.
        llm_provider: LLM provider.
        trace_logger: Logger.

    Returns:
        Updated state with strategic_analysis populated.
    """
    task_text = state["task_text"]

    # Build rules summary
    rules_text = ""
    auth_map = state.get("authority_map")
    if auth_map:
        levels_order = ["ROOT", "NESTED", "FOLDER", "PROCESS"]
        for level in levels_order:
            level_rules = [r for r in auth_map.rules if r.level == level]
            if level_rules:
                rules_text += f"\n=== {level} LEVEL RULES ===\n"
                for r in level_rules:
                    rules_text += f"FILE: {r.path}\n{r.content}\n"

    tree_text = state["workspace_rules"].get("tree_process", "Not loaded")

    messages = [
        {"role": "system", "content": STRATEGIC_ANALYSIS_PROMPT},
        {"role": "user", "content": (
            f"WORKSPACE TREE:\n{tree_text}\n\n"
            f"WORKSPACE RULES:\n{rules_text}\n\n"
            f"USER TASK:\n{task_text}"
        )},
    ]

    try:
        analysis = llm_provider.complete_as(messages, StrategicAnalysis)
    except Exception as e:
        if trace_logger:
            trace_logger.log_agent_event(
                agent_name="strategic_analysis",
                event="analysis_failed",
                details={"error": str(e)},
            )
        # Fallback: empty analysis, execution proceeds without guardrails
        analysis = StrategicAnalysis()

    state["strategic_analysis"] = analysis

    if trace_logger:
        trace_logger.log_agent_event(
            agent_name="strategic_analysis",
            event="analysis_completed",
            details={
                "predicted_entities": len(analysis.predicted_entities),
                "checklist_items": len(analysis.verification_checklist),
                "risks": len(analysis.risks),
                "scope_may_create": analysis.scope_boundary.files_may_create,
                "scope_must_not_touch": analysis.scope_boundary.files_must_not_touch,
                "approach": analysis.execution_approach[:200],
            },
        )

    return state
