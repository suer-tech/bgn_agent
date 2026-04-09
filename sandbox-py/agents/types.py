from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    task_id: str
    user_input: str
    system_prompt: str
    context: Optional[dict] = None


class AgentResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None
    next_action: Optional[Literal["continue", "retry", "stop"]] = None


class SecurityCheckResult(BaseModel):
    allowed: bool = True
    reason: Optional[str] = None
    blocked_tool: Optional[str] = None
    blocked_args_json: Optional[str] = None
    # LLM-specific fields
    injection_detected: bool = False
    injection_type: Optional[str] = (
        None  # "prompt_injection", "secret_exfiltration", "role_manipulation"
    )
    conflicting_rules: List[str] = Field(default_factory=list)
    priority_source: Optional[str] = None  # which rule source takes priority


class ContextResult(BaseModel):
    user_profile: dict = Field(default_factory=dict)
    project_rules: dict = Field(default_factory=dict)
    workspace_structure: dict = Field(default_factory=dict)
    workspace_root: str = "/"
    success: bool = True
    errors: List[str] = Field(default_factory=list)
    # LLM-specific fields
    instruction_hierarchy: List[str] = Field(default_factory=list)
    protected_files: List[str] = Field(default_factory=list)
    examples_found: List[str] = Field(default_factory=list)
    extraction_graph: Dict[str, Any] = Field(default_factory=dict)
    extract_status: str = "pending"
    user_question: str = ""


class ValidationResult(BaseModel):
    valid: bool = True
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    retry_needed: bool = False
    # LLM-specific fields
    quality_score: float = Field(1.0, ge=0.0, le=1.0)
    grounding_complete: bool = True
    missing_refs: List[str] = Field(default_factory=list)
    output_matches_task: bool = True


class ExecutionState(BaseModel):
    phase: Literal["discovery", "planning", "execution"] = "discovery"
    current_state: str = ""
    tool_history: List[dict] = Field(default_factory=list)
    plan_content: Optional[str] = None


class TaskContext(BaseModel):
    user_profile: dict = Field(default_factory=dict)
    project_rules: dict = Field(default_factory=dict)
    workspace_root: str = "/"
    protected_files: List[str] = Field(default_factory=list)
    extraction_graph: Dict[str, Any] = Field(default_factory=dict)
    user_question: str = ""


class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]


class ToolCallResult(BaseModel):
    success: bool
    tool_name: str
    arguments: Dict[str, Any]
    output: str
    error: Optional[str] = None


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

PERMISSIONS = {
    "read": "*",
    "write": "*",
    "delete": "protected",
    "tree": "*",
    "list": "*",
    "search": "*",
    "create_plan": "*",
    "update_plan_status": "*",
    "report_completion": "*",
}
