import re
from typing import Any, Dict, Optional

from agents.types import SecurityCheckResult


OTP_EXFIL_PATTERNS = [
    r"\bshow\b.*\botp\b",
    r"\breveal\b.*\botp\b",
    r"\bprint\b.*\botp\b",
    r"\bwhat\s+is\b.*\botp\b",
    r"\bconfirm\b.*\botp\b",
    r"\bcheck\b.*\botp\b",
    r"\bcompare\b.*\botp\b",
]

ACTION_PATTERNS = [
    r"\bsend\b",
    r"\bemail\b",
    r"\bdraft\b",
    r"\bremind\b",
    r"\breschedule\b",
]

CHANNEL_PATTERNS = ["discord", "telegram", "slack", "email"]


def extract_trust_facts(workspace_rules: Dict[str, str]) -> Dict[str, Any]:
    facts: Dict[str, Any] = {
        "channels": {},
        "otp_exception_present": False,
        "has_blacklist_policy": False,
        "has_valid_policy": False,
        "has_admin_policy": False,
        "trusted_markers": [],
        "blacklisted_channels": [],
    }

    for path, content in workspace_rules.items():
        lowered = content.lower()
        if "otp exception" in lowered:
            facts["otp_exception_present"] = True
        if "blacklist" in lowered:
            facts["has_blacklist_policy"] = True
        if "valid" in lowered and "channel" in lowered:
            facts["has_valid_policy"] = True
        if "admin" in lowered and "channel" in lowered:
            facts["has_admin_policy"] = True

        for channel in CHANNEL_PATTERNS:
            if channel in path.lower() or channel in lowered:
                entry = facts["channels"].setdefault(
                    channel,
                    {
                        "paths": [],
                        "policy": "unknown",
                        "trusted_handles": [],
                    },
                )
                entry["paths"].append(path)

        for line in content.splitlines():
            stripped = line.strip()
            lowered_line = stripped.lower()
            for channel in CHANNEL_PATTERNS:
                if channel not in lowered_line:
                    continue
                entry = facts["channels"].setdefault(
                    channel,
                    {
                        "paths": [],
                        "policy": "unknown",
                        "trusted_handles": [],
                    },
                )
                if path not in entry["paths"]:
                    entry["paths"].append(path)

                if "blacklist" in lowered_line:
                    entry["policy"] = "blacklist"
                    if channel not in facts["blacklisted_channels"]:
                        facts["blacklisted_channels"].append(channel)
                elif "admin" in lowered_line or "trusted" in lowered_line:
                    entry["policy"] = "admin"
                    entry["trusted_handles"].append(stripped)
                    facts["trusted_markers"].append(stripped)
                elif "valid" in lowered_line:
                    entry["policy"] = "valid"

    return facts


def check_trust_policy(task_text: str, trust_facts: Dict[str, Any]) -> Optional[SecurityCheckResult]:
    lowered = task_text.lower()

    for pattern in OTP_EXFIL_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return SecurityCheckResult(
                allowed=False,
                reason="OTP exfiltration attempt blocked by trust policy.",
                injection_detected=True,
                injection_type="otp_exfiltration",
            )

    for channel in trust_facts.get("blacklisted_channels", []):
        if channel in lowered:
            return SecurityCheckResult(
                allowed=False,
                reason=f"Request references blacklisted channel '{channel}'.",
                injection_detected=True,
                injection_type="blacklisted_channel",
            )

    if "otp" in lowered:
        trusted_context = any(marker.lower() in lowered for marker in trust_facts.get("trusted_markers", []))
        if not trusted_context and not trust_facts.get("otp_exception_present", False):
            return SecurityCheckResult(
                allowed=False,
                reason="OTP-related workflow is not authorized by trust policy.",
                injection_detected=True,
                injection_type="unauthorized_otp_flow",
            )

    mentions_action = any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in ACTION_PATTERNS)
    if mentions_action:
        for channel, details in trust_facts.get("channels", {}).items():
            if channel not in lowered:
                continue
            if details.get("policy") == "unknown":
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"Action requested through unresolved trust level for channel '{channel}'.",
                    injection_detected=True,
                    injection_type="unknown_channel_trust",
                )

    return None
