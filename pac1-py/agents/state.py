from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field


class Scratchpad(BaseModel):
    current_goal: str = Field("", description="Current subtask being worked on.")
    found_entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Discovered paths, ids, emails, and similar grounded facts.",
    )
    missing_info: str = Field(
        "",
        description="What still needs to be discovered or clarified.",
    )
    pending_items: List[str] = Field(
        default_factory=list,
        description="Queue for batch processing or follow-up work.",
    )
    completed_steps: List[str] = Field(
        default_factory=list,
        description="Append-only concise log of completed actions.",
    )


class AgentState(TypedDict):
    task_id: str
    task_text: str
    triage_result: Optional[Dict[str, Any]]
    workspace_rules: Dict[str, str]
    workspace_metadata: Dict[str, Any]
    scratchpad: Scratchpad
    grounded_paths: List[str]
    candidate_entities: Dict[str, List[str]]
    trust_facts: Dict[str, Any]
    validated_invariants: List[str]
    history: List[Dict[str, Any]]
    is_completed: bool
    final_outcome: str
