from agents.types import IntentType, TriageDecision

import re

MUTATION_PATTERNS = [
    r"\bdelete\b",
    r"\bremove\b",
    r"\bwrite\b",
    r"\bedit\b",
    r"\bupdate\b",
    r"\brename\b",
    r"\bmove\b",
    r"\bcreate\b",
    r"\bmkdir\b",
    r"\bdiscard\b",
    r"\bsend\b",
    r"\bemail\b",
    r"\bdraft\b",
    r"\breschedule\b",
    r"\bfix\b",
]

LOOKUP_PATTERNS = [
    r"\bfind\b",
    r"\bsearch\b",
    r"\bread\b",
    r"\bshow\b",
    r"\blookup\b",
    r"\bwhat\b",
    r"\bwhich\b",
    r"\blist\b",
]

UNSUPPORTED_PATTERNS = [
    r"\bhttp[s]?://",
    r"\bcall\s+api\b",
    r"\bopen\s+browser\b",
    r"\bfetch\s+from\s+internet\b",
    r"\bdeploy\b",
    r"\bcalendar\s+invite\b",
    r"\bcrm\s+sync\b",
]

REPO_WORKFLOW_HINTS = [
    "workflow",
    "process",
    "policy",
    "outbox",
    "inbox",
    "capture",
    "distill",
    "seq.json",
    "records",
    "thread",
    "card",
    "invoice",
    "contact",
    "account",
    "channel",
    "email",
]


def run_triage(task_text: str) -> TriageDecision:
    lowered = task_text.strip().lower()

    for pattern in UNSUPPORTED_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return TriageDecision(
                is_safe=True,
                intent=IntentType.UNSUPPORTED,
                reason="Request appears to require capabilities outside the PCM workspace.",
            )

    for pattern in MUTATION_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return TriageDecision(
                is_safe=True,
                intent=IntentType.MUTATION,
                reason="Request requires workspace mutation.",
            )

    for pattern in LOOKUP_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return TriageDecision(
                is_safe=True,
                intent=IntentType.LOOKUP,
                reason="Request appears read-only.",
            )

    return TriageDecision(
        is_safe=True,
        intent=IntentType.UNSUPPORTED,
        reason="Intent could not be classified safely.",
    )


def reroute_triage_with_workspace(
    task_text: str,
    workspace_rules: dict[str, str],
    initial: TriageDecision,
) -> TriageDecision:
    if initial.intent != IntentType.UNSUPPORTED:
        return initial

    lowered = task_text.strip().lower()
    rules_blob = " ".join(workspace_rules.values()).lower()

    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in LOOKUP_PATTERNS):
        return TriageDecision(
            is_safe=True,
            intent=IntentType.LOOKUP,
            reason="Repo-aware triage reclassified request as read-oriented.",
        )

    mentions_repo_work = any(hint in lowered for hint in ("process", "handle", "latest", "next", "follow"))
    has_local_workflow = any(hint in rules_blob for hint in REPO_WORKFLOW_HINTS)
    mentions_local_entities = any(
        token in lowered
        for token in ("thread", "card", "invoice", "contact", "account", "message", "inbox", "outbox", "record")
    )
    if (mentions_repo_work or mentions_local_entities) and has_local_workflow:
        return TriageDecision(
            is_safe=True,
            intent=IntentType.MUTATION,
            reason="Repo-aware triage found local workflow context for the request.",
        )

    return initial
