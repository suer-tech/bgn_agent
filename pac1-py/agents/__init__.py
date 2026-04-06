"""PAC1-PY Agents Package — State Machine Architecture.

Exports all agent types and node functions for the orchestrator.
"""

from agents.types import (
    # State Machine types
    AgentState,
    ScratchpadState,
    IntentType,
    TriageDecision,
    # PCM tool models
    NextStep,
    ReportTaskCompletion,
    Req_Context,
    Req_Tree,
    Req_Find,
    Req_Search,
    Req_List,
    Req_Read,
    Req_Write,
    Req_Delete,
    Req_MkDir,
    Req_Move,
    # Legacy types (for llm_logger compatibility)
    SecurityCheckResult,
    DependencyNode,
    ExtractionGraph,
    ContextResult,
    TaskContext,
    PROTECTED_FILES,
    SYSTEM_DIRECTORIES,
    get_outcome_map,
)

from agents.triage_node import run_triage
from agents.bootstrap_node import run_bootstrap
from agents.execution_agent import build_planner_prompt, plan_next_step
from agents.tool_executor import execute_tool
from agents.pcm_helpers import (
    safe_read_file,
    safe_tree,
    safe_list,
    safe_find,
    safe_search,
    safe_write,
    safe_delete,
    safe_mkdir,
    safe_move,
    safe_context,
    send_answer,
    dispatch_tool,
)

__all__ = [
    # State Machine
    "AgentState",
    "ScratchpadState",
    "IntentType",
    "TriageDecision",
    # PCM tools
    "NextStep",
    "ReportTaskCompletion",
    "Req_Context",
    "Req_Tree",
    "Req_Find",
    "Req_Search",
    "Req_List",
    "Req_Read",
    "Req_Write",
    "Req_Delete",
    "Req_MkDir",
    "Req_Move",
    # Legacy
    "SecurityCheckResult",
    "DependencyNode",
    "ExtractionGraph",
    "ContextResult",
    "TaskContext",
    "PROTECTED_FILES",
    "SYSTEM_DIRECTORIES",
    "get_outcome_map",
    # Node functions
    "run_triage",
    "run_bootstrap",
    "build_planner_prompt",
    "plan_next_step",
    "execute_tool",
    # PCM helpers
    "safe_read_file",
    "safe_tree",
    "safe_list",
    "safe_find",
    "safe_search",
    "safe_write",
    "safe_delete",
    "safe_mkdir",
    "safe_move",
    "safe_context",
    "send_answer",
    "dispatch_tool",
]
