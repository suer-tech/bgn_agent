import json
from pathlib import PurePosixPath
from typing import Any, Dict, Optional

from agents.state import AgentState
from agents.types import WorkflowValidationResult


def _normalize(path: str) -> str:
    return (path or "").replace("\\", "/").lstrip("/")


def _json_from_content(content: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(content)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_tool_against_workflow(
    state: AgentState,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Optional[WorkflowValidationResult]:
    if tool_name == "write":
        return _validate_write(state, arguments)
    if tool_name == "move":
        return _validate_move(state, arguments)
    if tool_name == "report_completion":
        return _validate_completion(state, arguments)
    return None


def _validate_write(
    state: AgentState,
    arguments: Dict[str, Any],
) -> Optional[WorkflowValidationResult]:
    path = _normalize(arguments.get("path", ""))
    content = arguments.get("content", "")

    if path.endswith(".json"):
        parsed = _json_from_content(content)
        if parsed is None:
            return _clarification(f"JSON write must contain valid object content: {path}")

        stable_id_error = _validate_stable_id(path, parsed)
        if stable_id_error:
            return stable_id_error

        invoice_error = _validate_invoice_invariants(path, parsed)
        if invoice_error:
            return invoice_error

        probability_error = _validate_probability(path, parsed)
        if probability_error:
            return probability_error

        sequence_error = _validate_sequence(path, parsed)
        if sequence_error:
            return sequence_error

        outbox_error = _validate_outbox_email(state, path, parsed)
        if outbox_error:
            return outbox_error

    return None


def _validate_stable_id(
    path: str,
    parsed: Dict[str, Any],
) -> Optional[WorkflowValidationResult]:
    stem = PurePosixPath(path).stem
    stable_id = parsed.get("id") or parsed.get("number")
    if isinstance(stable_id, str) and stable_id and stable_id != stem:
        return _clarification(f"Stable record id must match filename stem for {path}")
    return None


def _validate_invoice_invariants(
    path: str,
    parsed: Dict[str, Any],
) -> Optional[WorkflowValidationResult]:
    lines = parsed.get("lines")
    total = parsed.get("total")
    if isinstance(lines, list) and isinstance(total, (int, float)):
        line_sum = 0
        for line in lines:
            if isinstance(line, dict):
                amount = line.get("amount")
                if isinstance(amount, (int, float)):
                    line_sum += amount
        if line_sum and line_sum != total:
            return _clarification(f"Invoice total invariant violated for {path}")
    return None


def _validate_probability(
    path: str,
    parsed: Dict[str, Any],
) -> Optional[WorkflowValidationResult]:
    probability = parsed.get("probability_percent")
    if probability is not None and not (
        isinstance(probability, int) and 0 <= probability <= 100
    ):
        return _clarification(f"probability_percent must be integer 0..100 for {path}")
    return None


def _validate_sequence(
    path: str,
    parsed: Dict[str, Any],
) -> Optional[WorkflowValidationResult]:
    if not path.endswith("seq.json"):
        return None
    if "id" not in parsed:
        return _clarification("seq.json writes must preserve integer id field")
    if not isinstance(parsed.get("id"), int):
        return _clarification("seq.json id must remain an integer")
    return None


def _validate_outbox_email(
    state: AgentState,
    path: str,
    parsed: Dict[str, Any],
) -> Optional[WorkflowValidationResult]:
    lowered_path = path.lower()
    if "/outbox/" not in f"/{lowered_path}" and not lowered_path.endswith(".json"):
        return None

    if {"subject", "to", "body"}.issubset(parsed.keys()):
        to_value = parsed.get("to")
        if not isinstance(to_value, str) or "@" not in to_value:
            return _clarification(f"Outbox email must target a concrete email address in {path}")

        sent_value = parsed.get("sent")
        if sent_value is not None and sent_value is not False:
            return _clarification(f"Outbox email must be created with sent=false in {path}")

        attachments = parsed.get("attachments")
        if attachments is not None:
            if not isinstance(attachments, list):
                return _clarification(f"Attachments must be an array in {path}")
            grounded = {item.lower() for item in state["grounded_paths"]}
            for attachment in attachments:
                if not isinstance(attachment, str):
                    return _clarification(f"Attachment paths must be strings in {path}")
                if attachment.replace("\\", "/").lstrip("/").lower() not in grounded:
                    return _clarification(
                        f"Attachment must point to an existing grounded repo path: {attachment}"
                    )

    return None


def _validate_move(
    state: AgentState,
    arguments: Dict[str, Any],
) -> Optional[WorkflowValidationResult]:
    source = _normalize(arguments.get("from_name", ""))
    destination = _normalize(arguments.get("to_name", ""))
    if source.endswith(".json") and destination.endswith(".json"):
        source_stem = PurePosixPath(source).stem
        destination_stem = PurePosixPath(destination).stem
        if source_stem != destination_stem and "historical repair" not in " ".join(
            state["workspace_rules"].values()
        ).lower():
            return _unsupported(
                "Stable record IDs cannot be renamed without explicit workflow authorization."
            )
    return None


def _validate_completion(
    state: AgentState,
    arguments: Dict[str, Any],
) -> Optional[WorkflowValidationResult]:
    outcome = arguments.get("outcome", "")
    if outcome == "OUTCOME_OK" and _scratchpad_missing_critical_info(state):
        return _clarification("Cannot report OUTCOME_OK while required information is still missing.")
    return None


def _scratchpad_missing_critical_info(state: AgentState) -> bool:
    missing_info = str(state["scratchpad"].missing_info or "").strip()
    if not missing_info:
        return False
    keywords = ("missing", "unknown", "ambiguous", "unclear", "not found")
    lowered = missing_info.lower()
    return any(word in lowered for word in keywords)


def _clarification(reason: str) -> WorkflowValidationResult:
    return WorkflowValidationResult(
        reason=reason,
        outcome="OUTCOME_NONE_CLARIFICATION",
    )


def _unsupported(reason: str) -> WorkflowValidationResult:
    return WorkflowValidationResult(
        reason=reason,
        outcome="OUTCOME_NONE_UNSUPPORTED",
    )
