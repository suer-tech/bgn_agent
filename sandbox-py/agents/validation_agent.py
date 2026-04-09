import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agents.types import ValidationResult
from agents.prompt_storage import get_prompt


def _get_validation_prompt() -> str:
    try:
        return get_prompt("validation_agent")
    except FileNotFoundError:
        return "You are a Validation Agent."


VALIDATION_AGENT_PROMPT = _get_validation_prompt()


class ValidationAgent:
    """Validation Agent — validates tool execution results."""
    
    def __init__(self):
        self.prompt = VALIDATION_AGENT_PROMPT
    
    def validate(self, tool_name: str, arguments: Dict[str, Any], result: str, is_error: bool = False):
        from agents.types import ValidationResult
        errors = []
        warnings = []
        
        if is_error or "error" in result.lower():
            if is_error:
                errors.append(f"Tool execution error: {result[:200]}")
            else:
                if "permission denied" in result.lower():
                    errors.append("Permission denied")
                elif "not found" in result.lower() and tool_name == "read":
                    errors.append("File not found")
                elif "timeout" in result.lower():
                    errors.append("Operation timed out")
        
        retry_needed = len(errors) > 0
        valid = len(errors) == 0
        
        return ValidationResult(
            valid=valid,
            errors=errors,
            warnings=warnings,
            retry_needed=retry_needed,
        )


def create_validation_agent():
    return ValidationAgent()
