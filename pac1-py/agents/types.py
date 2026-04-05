"""Unified type definitions for PAC1-PY State Machine architecture.

This is the SINGLE SOURCE OF TRUTH for all Pydantic models, enums,
and TypedDicts used across the agent graph.
"""

import os
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union, Annotated

from annotated_types import Ge, Le, MaxLen, MinLen
from pydantic import BaseModel, Field


# =============================================================================
# Security & Legacy types (kept for backward compatibility with llm_logger.py)
# =============================================================================

class SecurityCheckResult(BaseModel):
    allowed: bool = True
    reason: Optional[str] = None
    injection_detected: bool = False
    injection_type: Optional[str] = None
    sanitized_input: Optional[str] = None


class DependencyNode(BaseModel):
    path: str
    content: str = ""
    status: str = "pending"
    children: List[str] = Field(default_factory=list)
    parent: Optional[str] = None


class ExtractionGraph(BaseModel):
    """Hierarchical dependency graph of instruction files"""
    root: str = "system_prompt"
    nodes: Dict[str, DependencyNode] = Field(default_factory=dict)
    hierarchy: List[str] = Field(default_factory=list)


class ContextResult(BaseModel):
    directory_structure: Dict[str, Any] = Field(default_factory=dict)
    directory_tree_formatted: str = ""
    agents_md_path: Optional[str] = None
    agents_md_content: str = ""
    referenced_files: Dict[str, str] = Field(default_factory=dict)
    instruction_dependency_graph: ExtractionGraph = Field(default_factory=ExtractionGraph)
    extract_status: str = "pending"


class TaskContext(BaseModel):
    """Enriched context passed to execution agent"""
    task_text: str
    system_prompt: str
    workspace_structure: str
    agents_md_content: str
    referenced_files: Dict[str, str]
    instruction_dependency_graph: ExtractionGraph
    protected_files: List[str] = Field(default_factory=list)


PROTECTED_FILES = {"AGENTS.MD", "AGENTS.md", "README.md", ".git"}
SYSTEM_DIRECTORIES = {
    "/system", "/proc", "/sys", "/dev",
    r"C:\Windows", r"C:\Program Files", r"C:\Program Files (x86)",
}


# =============================================================================
# State Machine: Scratchpad Memory
# =============================================================================

class ScratchpadState(BaseModel):
    """Agent's working memory — persisted between execution loop iterations."""
    current_goal: str = Field(
        default="",
        description="Какую подзадачу мы решаем прямо сейчас?",
    )
    found_entities: Dict[str, Union[str, List[str]]] = Field(
        default_factory=dict,
        description="Кэш найденных данных: ID, email, пути. Формат: {'Alex Meyer email': ['alex@example.com']}",
    )
    missing_info: str = Field(
        default="",
        description="Чего нам не хватает для выполнения задачи?",
    )
    completed_steps: List[str] = Field(
        default_factory=list,
        description="Краткий лог того, что уже успешно сделано",
    )
    pending_items_to_process: List[str] = Field(
        default_factory=list,
        description="Список файлов, которые еще предстоит обработать",
    )


# =============================================================================
# State Machine: Triage classification
# =============================================================================

class IntentType(str, Enum):
    LOOKUP = "LOOKUP"          # Только поиск/чтение
    MUTATION = "MUTATION"      # Изменение данных
    UNSUPPORTED = "UNSUPPORTED"  # Действия вне песочницы
    ATTACK = "ATTACK"          # Попытка взлома или извлечения секретов


class TriageDecision(BaseModel):
    is_safe: bool
    intent: IntentType
    reason: str


# =============================================================================
# State Machine: Main Agent State
# =============================================================================

class AgentState(TypedDict):
    task_text: str                                # Оригинальный запрос <user_input>
    triage_result: Optional[TriageDecision]
    workspace_rules: Dict[str, str]               # Загруженные правила: {"/AGENTS.md": "текст", ...}
    scratchpad: ScratchpadState                    # Оперативная память агента
    conversation_history: List[dict]               # Лог LLM-вызовов
    is_completed: bool                             # Флаг завершения цикла
    final_outcome: str                             # OUTCOME_OK, OUTCOME_DENIED_SECURITY и т.д.


# =============================================================================
# PCM Tool Request Models (единый источник правды)
# =============================================================================

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


class Req_Tree(BaseModel):
    tool: Literal["tree"]
    level: int = Field(2, description="max tree depth, 0 means unlimited")
    root: str = Field("", description="tree root, empty means repository root")


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
    number: bool = Field(False, description="return 1-based line numbers")
    start_line: Annotated[int, Ge(0)] = Field(
        0, description="1-based inclusive linum; 0 == from the first line",
    )
    end_line: Annotated[int, Ge(0)] = Field(
        0, description="1-based inclusive linum; 0 == through the last line",
    )


class Req_Context(BaseModel):
    tool: Literal["context"]


class Req_Write(BaseModel):
    tool: Literal["write"]
    path: str
    content: str
    start_line: Annotated[int, Ge(0)] = Field(
        0, description="1-based inclusive line number; 0 keeps whole-file overwrite behavior",
    )
    end_line: Annotated[int, Ge(0)] = Field(
        0, description="1-based inclusive line number; 0 means through the last line for ranged writes",
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


# =============================================================================
# Execution Planner: NextStep with Scratchpad
# =============================================================================

class NextStep(BaseModel):
    current_state: str
    plan_remaining_steps_brief: Annotated[List[str], MinLen(1), MaxLen(5)] = Field(
        ...,
        description="briefly explain the next useful steps",
    )
    scratchpad_update: ScratchpadState = Field(
        default_factory=ScratchpadState,
        description="Обновлённая памятка агента. Записывай найденные ID в found_entities!",
    )
    task_completed: bool
    function: Union[
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
    ] = Field(..., description="execute the first remaining step")


# =============================================================================
# PCM Outcome mapping
# =============================================================================

# Lazy import — avoid importing protobuf at module level for testability.
# Populated on first access via get_outcome_map().
_OUTCOME_MAP = None


def get_outcome_map():
    """Return PCM Outcome enum map, importing protobuf lazily."""
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
