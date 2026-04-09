from typing import Any, Dict, Optional

from agents.state import Scratchpad
from agents.types import IntentType, TriageDecision


HIGH_RISK_TOOLS = {"write", "delete", "move", "mkdir"}
AMBIGUITY_ENTITY_KEYS = {
    "contact",
    "account",
    "invoice",
    "opportunity",
    "thread",
    "card",
    "channel",
    "recipient",
    "sender",
    "message",
}

BATCH_KEY_HINTS = {
    "pending",
    "queue",
    "items",
    "targets",
    "files",
    "paths",
    "to_delete",
    "to_remove",
    "to_move",
    "to_process",
}


def check_action_ambiguity(
    tool_name: str,
    arguments: Dict[str, Any],
    scratchpad: Scratchpad,
    task_text: str = "",
    candidate_entities: Dict[str, list[str]] | None = None,
) -> Optional[str]:
    if tool_name not in HIGH_RISK_TOOLS and tool_name != "report_completion":
        return None

    if scratchpad.missing_info.strip():
        return scratchpad.missing_info.strip()

    for key, value in scratchpad.found_entities.items():
        if not isinstance(value, list) or len(value) <= 1:
            continue
        if _looks_like_batch_queue(key, value, scratchpad, task_text):
            continue
        if _looks_like_multi_target_batch_request(tool_name, scratchpad, task_text):
            continue
        if _is_entity_ambiguity_key(key):
            return f"Ambiguous target remains unresolved for '{key}'."

    path = arguments.get("path") or arguments.get("from_name") or ""
    if isinstance(path, list) and len(path) > 1:
        return "Multiple candidate paths remain unresolved."

    relevant_groups = _infer_relevant_groups(tool_name, arguments, scratchpad, task_text)
    for key, values in (candidate_entities or {}).items():
        normalized_key = key.lower()
        if relevant_groups and normalized_key not in relevant_groups:
            continue
        if normalized_key in AMBIGUITY_ENTITY_KEYS and isinstance(values, list) and len(values) > 1:
            return f"Multiple candidate {key} entities remain unresolved."

    return None


def check_triage_violation(
    triage_result: Dict[str, Any] | TriageDecision | None,
    tool_name: str,
) -> Optional[str]:
    if triage_result is None:
        return None

    if isinstance(triage_result, TriageDecision):
        intent = triage_result.intent.value
    else:
        intent = str(triage_result.get("intent", ""))

    if intent == IntentType.LOOKUP.value and tool_name in HIGH_RISK_TOOLS:
        return "Lookup-classified task cannot perform mutation without clarification."

    return None


def _infer_relevant_groups(
    tool_name: str,
    arguments: Dict[str, Any],
    scratchpad: Scratchpad,
    task_text: str,
) -> set[str]:
    haystack_parts = [
        tool_name,
        str(arguments.get("path", "")),
        str(arguments.get("from_name", "")),
        str(arguments.get("to_name", "")),
        scratchpad.current_goal,
        task_text,
    ]
    haystack = " ".join(part.lower() for part in haystack_parts if part)
    matched = {key for key in AMBIGUITY_ENTITY_KEYS if key in haystack}

    for key in scratchpad.found_entities.keys():
        lowered = str(key).lower()
        if lowered in AMBIGUITY_ENTITY_KEYS and lowered in haystack:
            matched.add(lowered)

    return matched


def _looks_like_batch_queue(
    key: str,
    value: list[Any],
    scratchpad: Scratchpad,
    task_text: str,
) -> bool:
    lowered_key = str(key).lower()
    if any(hint in lowered_key for hint in BATCH_KEY_HINTS):
        return True

    if all(isinstance(item, str) and "/" in item for item in value):
        haystack = " ".join(
            part.lower()
            for part in (scratchpad.current_goal, task_text)
            if part
        )
        if any(token in haystack for token in ("all", "every", "batch", "cleanup", "clean", "remove", "delete")):
            return True

    return False


def _looks_like_multi_target_batch_request(
    tool_name: str,
    scratchpad: Scratchpad,
    task_text: str,
) -> bool:
    if tool_name != "delete":
        return False
    haystack = " ".join(
        part.lower()
        for part in (scratchpad.current_goal, task_text)
        if part
    )
    return any(token in haystack for token in ("all", "every", "cleanup", "clean", "remove all", "delete all"))


def _is_entity_ambiguity_key(key: str) -> bool:
    lowered_key = str(key).lower()
    if lowered_key in AMBIGUITY_ENTITY_KEYS:
        return True
    singular = lowered_key.rstrip("s")
    return singular in AMBIGUITY_ENTITY_KEYS
