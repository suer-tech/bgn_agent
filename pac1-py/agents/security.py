import re
from typing import Any, Dict, Iterable, Optional

from agents.types import PROTECTED_FILES, SYSTEM_DIRECTORIES, SecurityCheckResult


INPUT_ATTACK_PATTERNS: list[tuple[str, str, bool]] = [
    (r"ignore\s+(all\s+)?previous\s+instructions", "prompt_injection", False),
    (r"ignore\s+(all\s+)?prior\s+rules", "prompt_injection", False),
    (r"forget\s+(all\s+)?previous\s+instructions", "prompt_injection", False),
    (r"disregard\s+(the\s+)?system\s+prompt", "prompt_injection", False),
    (r"you\s+are\s+now\s+(admin|root|god|system)", "role_manipulation", False),
    (r"act\s+as\s+(admin|root|god|system)", "role_manipulation", False),
    (r"reveal\s+(the\s+)?(system\s+prompt|api\s+key|secret|password)", "secret_exfiltration", False),
    (r"show\s+(the\s+)?(system\s+prompt|api\s+key|secret|password)", "secret_exfiltration", False),
    (r"print\s+(the\s+)?(system\s+prompt|api\s+key|secret|password)", "secret_exfiltration", False),
    (r"<\s*system[-_]?reminder\s*>", "prompt_injection", False),
    (r"BEGIN[_\s-]*PROMPT[_\s-]*INJECTION", "prompt_injection", False),
    (r"developer\s+message", "prompt_injection", False),
    (r"tool\s+schema", "prompt_injection", False),
]

CONTEXT_ATTACK_PATTERNS: list[tuple[str, str, bool]] = [
    (r"<!--.*?ignore.*?instructions.*?-->", "hidden_instruction", True),
    (r"<!--.*?system.*?prompt.*?-->", "hidden_instruction", True),
    (r"<!--.*?reveal.*?(secret|password|api key).*?-->", "hidden_instruction", True),
    (r"<\s*system[-_]?reminder\s*>.*?<\s*/\s*system[-_]?reminder\s*>", "hidden_instruction", True),
    (r"\b(?:assistant|system|developer)\s*:\s*ignore", "spoofing", False),
    (r"\bdo not tell the user\b", "hidden_instruction", False),
    (r"\bonly the agent should see this\b", "hidden_instruction", False),
]

SUSPICIOUS_PATH_PATTERNS = [
    r"\.\.",
    r"^/root\b",
    r"^/etc\b",
    r"^c:/windows\b",
    r"^c:\\windows\b",
]


def _match_patterns(
    text: str,
    patterns: Iterable[tuple[str, str, bool]],
) -> Optional[tuple[str, str]]:
    lowered = text.lower()
    for pattern, attack_type, dotall in patterns:
        flags = re.IGNORECASE | (re.DOTALL if dotall else 0)
        if re.search(pattern, lowered, flags=flags):
            return attack_type, pattern
    return None


def sanitize_user_input(text: str) -> str:
    cleaned = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    cleaned = re.sub(
        r"<\s*system[-_]?reminder\s*>.*?<\s*/\s*system[-_]?reminder\s*>",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return cleaned.strip()


def check_user_input(text: str) -> SecurityCheckResult:
    match = _match_patterns(text, INPUT_ATTACK_PATTERNS)
    if not match:
        return SecurityCheckResult(allowed=True, reason="Input approved")
    attack_type, _ = match
    return SecurityCheckResult(
        allowed=False,
        reason=f"Blocked unsafe user input ({attack_type}).",
        injection_detected=True,
        injection_type=attack_type,
        sanitized_input=sanitize_user_input(text),
    )


def check_context_block(name: str, content: str) -> SecurityCheckResult:
    match = _match_patterns(content, CONTEXT_ATTACK_PATTERNS)
    if not match:
        return SecurityCheckResult(allowed=True, reason=f"Context approved: {name}")
    attack_type, _ = match
    return SecurityCheckResult(
        allowed=False,
        reason=f"Blocked suspicious hidden instruction in {name} ({attack_type}).",
        injection_detected=True,
        injection_type=attack_type,
    )


def check_workspace_rules(workspace_rules: Dict[str, str]) -> SecurityCheckResult:
    for name, content in workspace_rules.items():
        result = check_context_block(name, content)
        if not result.allowed:
            return result
    return SecurityCheckResult(allowed=True, reason="Bootstrap context approved")


def check_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    seen_paths: set[str],
) -> SecurityCheckResult:
    protected_files = {item.lower() for item in PROTECTED_FILES}
    system_directories = tuple(item.lower().replace("\\", "/") for item in SYSTEM_DIRECTORIES)

    def normalize(path: str) -> str:
        return (path or "").replace("\\", "/").lstrip("/").lower()

    primary_path = ""
    if tool_name in {"read", "cat", "write", "delete", "list", "ls"}:
        primary_path = arguments.get("path", "") or ""
    elif tool_name == "tree":
        primary_path = arguments.get("root", "") or ""
    elif tool_name == "move":
        primary_path = arguments.get("from_name", "") or ""

    normalized = normalize(primary_path)
    if normalized:
        for pattern in SUSPICIOUS_PATH_PATTERNS:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"Suspicious path rejected: {primary_path}",
                    injection_detected=False,
                )
        for sys_dir in system_directories:
            if normalized.startswith(sys_dir.lstrip("/")):
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"System path access is forbidden: {primary_path}",
                    injection_detected=False,
                )

    if tool_name in {"write", "delete", "move"}:
        if normalized and any(token in normalized for token in protected_files):
            return SecurityCheckResult(
                allowed=False,
                reason=f"Protected path is immutable: {primary_path}",
                injection_detected=False,
            )

    if tool_name in {"write", "delete"} and normalized and normalized not in seen_paths:
        return SecurityCheckResult(
            allowed=False,
            reason=f"Path was not discovered earlier in session: {primary_path}",
            injection_detected=False,
        )

    if tool_name == "move":
        source = normalize(arguments.get("from_name", "") or "")
        destination = normalize(arguments.get("to_name", "") or "")
        if source and source not in seen_paths:
            return SecurityCheckResult(
                allowed=False,
                reason=f"Move source was not discovered earlier in session: {arguments.get('from_name', '')}",
                injection_detected=False,
            )
        if destination and any(token in destination for token in protected_files):
            return SecurityCheckResult(
                allowed=False,
                reason=f"Move destination targets protected path: {arguments.get('to_name', '')}",
                injection_detected=False,
            )

    if tool_name == "report_completion":
        outcome = arguments.get("outcome", "")
        if outcome not in {
            "OUTCOME_OK",
            "OUTCOME_DENIED_SECURITY",
            "OUTCOME_NONE_CLARIFICATION",
            "OUTCOME_NONE_UNSUPPORTED",
            "OUTCOME_ERR_INTERNAL",
        }:
            return SecurityCheckResult(
                allowed=False,
                reason=f"Unknown outcome in report_completion: {outcome}",
                injection_detected=False,
            )

    return SecurityCheckResult(allowed=True, reason="Tool call approved")
