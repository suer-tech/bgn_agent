"""Shared tool, triage, and protocol types for the Agentic OS runtime."""

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional

from annotated_types import Ge, Le, MaxLen
from pydantic import BaseModel, Field, model_validator


class SecurityCheckResult(BaseModel):
    allowed: bool = True
    reason: Optional[str] = None
    injection_detected: bool = False
    injection_type: Optional[str] = None
    sanitized_input: Optional[str] = None


class WorkflowValidationResult(BaseModel):
    reason: str
    outcome: Literal[
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_DENIED_SECURITY",
    ] = "OUTCOME_NONE_CLARIFICATION"


PROTECTED_FILES = {"AGENTS.MD", "AGENTS.md", "README.md", ".git"}
SYSTEM_DIRECTORIES = {
    "/system",
    "/proc",
    "/sys",
    "/dev",
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
}


class IntentType(str, Enum):
    LOOKUP = "LOOKUP"
    MUTATION = "MUTATION"
    UNSUPPORTED = "UNSUPPORTED"
    ATTACK = "ATTACK"


class TriageDecision(BaseModel):
    is_safe: bool
    intent: IntentType
    reason: str


class ReportTaskCompletion(BaseModel):
    tool: Literal["report_completion"]
    completed_steps_laconic: List[str]
    message: str
    grounding_refs: List[str] = Field(default_factory=list)
    outcome: Literal[
        "OUTCOME_OK",
        "OUTCOME_DENIED_SECURITY",
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_ERR_INTERNAL",
    ]

    @model_validator(mode="before")
    @classmethod
    def _normalize_completed_steps(cls, data: Any) -> Any:
        if isinstance(data, dict):
            steps = data.get("completed_steps_laconic")
            if isinstance(steps, str):
                data = dict(data)
                data["completed_steps_laconic"] = [steps]
        return data


class Req_Tree(BaseModel):
    tool: Literal["tree"]
    level: int = Field(2, description="Max tree depth, 0 means unlimited.")
    root: str = Field("", description="Tree root, empty means repository root.")


class Req_Find(BaseModel):
    tool: Literal["find"]
    name: str
    root: str = "/"
    kind: Literal["all", "files", "dirs"] = "all"
    limit: Annotated[int, Ge(1), Le(20)] = 10


class Req_Search(BaseModel):
    tool: Literal["search"]
    pattern: str
    limit: Annotated[int, Ge(1), Le(20)] = 10
    root: str = "/"


class Req_List(BaseModel):
    tool: Literal["list", "ls"]
    path: str = "/"


class Req_Read(BaseModel):
    tool: Literal["read", "cat"]
    path: str
    number: bool = Field(False, description="Return 1-based line numbers.")
    start_line: Annotated[int, Ge(0)] = Field(
        0,
        description="1-based inclusive start line, 0 means from the first line.",
    )
    end_line: Annotated[int, Ge(0)] = Field(
        0,
        description="1-based inclusive end line, 0 means through the last line.",
    )


class Req_Context(BaseModel):
    tool: Literal["context"]


class Req_Write(BaseModel):
    tool: Literal["write"]
    path: str
    content: str
    start_line: Annotated[int, Ge(0)] = Field(
        0,
        description="1-based inclusive start line for ranged writes.",
    )
    end_line: Annotated[int, Ge(0)] = Field(
        0,
        description="1-based inclusive end line for ranged writes.",
    )


class Req_Delete(BaseModel):
    tool: Literal["delete"]
    path: str


class Req_MkDir(BaseModel):
    tool: Literal["mkdir"]
    path: str


class Req_Move(BaseModel):
    tool: Literal["move"]
    from_name: str
    to_name: str


class ToolCall(BaseModel):
    name: Literal[
        "context",
        "tree",
        "find",
        "search",
        "list",
        "ls",
        "read",
        "cat",
        "write",
        "delete",
        "mkdir",
        "move",
        "report_completion",
    ]
    arguments: Dict[str, Any] = Field(default_factory=dict)


class NextStep(BaseModel):
    current_state: str
    plan_remaining_steps_brief: Annotated[List[str], MaxLen(5)] = Field(
        ...,
        description="Briefly explain the next useful steps.",
    )
    scratchpad_update: Dict[str, Any] = Field(
        default_factory=dict,
        description="Full next scratchpad payload.",
    )
    task_completed: bool
    tool_call: ToolCall = Field(..., description="Tool call to execute next.")

    @model_validator(mode="before")
    @classmethod
    def _validate_conditional_plan(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        task_completed = bool(data.get("task_completed"))
        plan = data.get("plan_remaining_steps_brief")
        if not task_completed and (not isinstance(plan, list) or len(plan) == 0):
            raise ValueError(
                "plan_remaining_steps_brief must contain at least one step while task_completed is false."
            )
        return data


_OUTCOME_MAP = None


def get_outcome_map():
    global _OUTCOME_MAP
    if _OUTCOME_MAP is None:
        from bitgn.vm.pcm_pb2 import Outcome

        _OUTCOME_MAP = {
            "OUTCOME_OK": Outcome.OUTCOME_OK,
            "OUTCOME_DENIED_SECURITY": Outcome.OUTCOME_DENIED_SECURITY,
            "OUTCOME_NONE_CLARIFICATION": Outcome.OUTCOME_NONE_CLARIFICATION,
            "OUTCOME_NONE_UNSUPPORTED": Outcome.OUTCOME_NONE_UNSUPPORTED,
            "OUTCOME_ERR_INTERNAL": Outcome.OUTCOME_ERR_INTERNAL,
        }
    return _OUTCOME_MAP
