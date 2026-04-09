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

class TrackedEntity(BaseModel):
    """A single entity discovered during execution, with its resolution status."""
    entity_type: str = Field(
        ..., description="Type: account, contact, manager, invoice, reminder, opportunity, message, file",
    )
    identifier: str = Field(
        ..., description="Human-readable identifier: name, email, or ID (e.g., 'Matthias Schuster', 'acct_007')",
    )
    resolved_file: Optional[str] = Field(
        default=None,
        description="Path to the authoritative record file (e.g., 'contacts/mgr_002.json'). None if not yet resolved.",
    )
    status: Literal["resolved", "unresolved", "not_applicable"] = Field(
        default="unresolved",
        description=(
            "resolved = authoritative file found and read. "
            "unresolved = entity mentioned but record not yet located. "
            "not_applicable = no separate record exists for this entity."
        ),
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="Identifiers of other entities this one depends on (e.g., contact depends on account)",
    )


# =============================================================================
# Strategic Analysis: Pre-execution planning
# =============================================================================

class VerificationItem(BaseModel):
    """A single check that must pass before task completion."""
    check: str = Field(..., description="What to verify (e.g., 'sender email matches contact record')")
    source_rule: str = Field(..., description="FILE: /path — RULE: quote that requires this check")
    status: Literal["pending", "passed", "failed", "skipped"] = Field(
        default="pending", description="Updated during execution as checks are performed",
    )


class Risk(BaseModel):
    """A potential issue to watch for during execution."""
    description: str = Field(..., description="What could go wrong (e.g., 'contact may request data from another account')")
    mitigation: str = Field(..., description="How to handle it (e.g., 'verify sender account_id matches requested account')")
    source_rule: str = Field(..., description="FILE: /path — RULE: quote")


class ScopeBoundary(BaseModel):
    """What the agent is and isn't allowed to touch."""
    files_may_create: List[str] = Field(default_factory=list, description="Glob patterns of files agent may create (e.g., 'outbox/*.json')")
    files_may_modify: List[str] = Field(default_factory=list, description="Glob patterns of files agent may modify (e.g., 'outbox/seq.json')")
    files_must_not_touch: List[str] = Field(default_factory=list, description="Files/patterns agent must NOT modify or delete")
    reasoning: str = Field(default="", description="Why these boundaries")


class StrategicAnalysis(BaseModel):
    """Pre-execution analysis — think before you act."""
    predicted_entities: List[TrackedEntity] = Field(
        default_factory=list,
        description="All entities the task will likely involve, with predicted dependencies. Mark all as 'unresolved' initially.",
    )
    verification_checklist: List[VerificationItem] = Field(
        default_factory=list,
        description="Checks that MUST pass before reporting completion. Derived from workspace rules and task requirements.",
    )
    risks: List[Risk] = Field(
        default_factory=list,
        description="Potential issues to watch for, with mitigations derived from workspace rules.",
    )
    scope_boundary: ScopeBoundary = Field(
        default_factory=ScopeBoundary,
        description="What files the agent is allowed to create/modify/must-not-touch.",
    )
    execution_approach: str = Field(
        default="",
        description="Brief description of the planned approach (2-3 sentences).",
    )


class PreCompletionReview(BaseModel):
    """Final review before sending answer to benchmark."""
    all_entities_resolved: bool = Field(..., description="Are all entities in entity_graph resolved?")
    checklist_passed: bool = Field(..., description="Are all verification_checklist items passed?")
    scope_respected: bool = Field(..., description="Were scope boundaries respected?")
    approved: bool = Field(..., description="Overall: is the answer ready to submit?")
    issues: List[str] = Field(default_factory=list, description="List of issues if not approved")


class ScratchpadState(BaseModel):
    """Agent's working memory — persisted between execution loop iterations."""
    current_goal: str = Field(
        default="",
        description="Какую подзадачу мы решаем прямо сейчас?",
    )
    entity_graph: List[TrackedEntity] = Field(
        default_factory=list,
        description=(
            "MANDATORY: track ALL entities discovered during execution. "
            "Every person, account, record, or file mentioned in the task or found during execution "
            "must be added here. Each entity must be resolved to its authoritative file before task completion. "
            "If an entity has dependencies (e.g., account_manager → contact record), add those too. "
            "At report_completion, ALL resolved_file paths become grounding_refs."
        ),
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
    current_workflow: Optional[str] = Field(
        default=None,
        description="Current active workflow",
    )


# =============================================================================
# State Machine: Triage classification
# =============================================================================

class IntentType(str, Enum):
    LOOKUP = "LOOKUP"          # Только поиск/чтение
    MUTATION = "MUTATION"      # Изменение данных
    UNSUPPORTED = "UNSUPPORTED"  # Действия вне песочницы
    ATTACK = "ATTACK"          # Попытка взлома или извлечения секретов
    CLARIFY_NEEDED = "CLARIFY_NEEDED" # Требуется уточнение
    SECURITY_DENIAL = "SECURITY_DENIAL" # Отказ по соображениям безопасности


class DomainType(str, Enum):
    KNOWLEDGE_REPO = "KNOWLEDGE_REPO"
    TYPED_CRM = "TYPED_CRM"
    INBOX_WORKFLOW = "INBOX_WORKFLOW"
    REPAIR_DIAGNOSTICS = "REPAIR_DIAGNOSTICS"
    GENERAL = "GENERAL"


class AuthorityLevel(str, Enum):
    ROOT = "ROOT"
    NESTED = "NESTED"
    FOLDER = "FOLDER"
    PROCESS = "PROCESS"


class AuthorityRule(BaseModel):
    path: str
    content: str
    level: AuthorityLevel
    scope: str = "/"  # Path where this rule is applicable


class AuthorityMap(BaseModel):
    """Hierarchical authority rules with scope awareness."""
    rules: List[AuthorityRule] = Field(default_factory=list)

    def get_rules_for_path(self, target_path: str) -> List[AuthorityRule]:
        """Return rules applicable to the given path, sorted by specificity."""
        applicable = [
            r for r in self.rules 
            if target_path.startswith(r.scope)
        ]
        # Sort by scope length descending (most specific first)
        return sorted(applicable, key=lambda x: len(x.scope), reverse=True)


class TriageDecision(BaseModel):
    is_safe: bool
    intent: IntentType
    domain: DomainType = Field(default=DomainType.GENERAL)
    reason: str


class ContextAdvice(BaseModel):
    """LLM advice on which additional instruction files to pre-load."""
    additional_paths: List[str] = Field(
        default_factory=list,
        description="Paths to instruction/rule files that should be pre-loaded for the executor",
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation of why these files are needed",
    )


# =============================================================================
# State Machine: Main Agent State
# =============================================================================

class TaskModel(BaseModel):
    """Structured understanding of the user request."""
    domain: DomainType
    intent: IntentType
    requested_effect: str  # e.g., "send_email", "update_contact", "find_password"
    target_entities: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    ambiguity_high: bool = False
    security_risk_high: bool = False
    terminal_mode_candidate: Optional[str] = None


class TriageAndTaskModel(BaseModel):
    """Combined triage + task extraction in one LLM call."""
    # Triage fields
    is_safe: bool
    intent: IntentType
    reason: str
    # Task model fields
    domain: DomainType = Field(default=DomainType.GENERAL)
    requested_effect: str = Field(default="unknown")
    target_entities: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    ambiguity_high: bool = False
    security_risk_high: bool = False


class AgentState(TypedDict):
    task_text: str                                # Оригинальный запрос <user_input>
    triage_result: Optional[TriageDecision]
    task_model: Optional[TaskModel]               # New: structured task model
    workspace_rules: Dict[str, str]               # Legacy: flat rules for backward compatibility
    authority_map: AuthorityMap                   # New: hierarchical rules
    strategic_analysis: Optional[StrategicAnalysis]  # Pre-execution planning
    scratchpad: ScratchpadState                    # Оперативная память агента
    entity_context: str                           # Pre-gathered context for target entities
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

# =============================================================================
# Execution Planner: Subagent Delegation
# =============================================================================

class SubagentTask(BaseModel):
    """Specific assignment for a subagent."""
    subagent_id: str  # e.g., "crm", "knowledge", "inbox"
    instruction: str
    target_paths: List[str] = Field(default_factory=list)
    context_data: Dict[str, Any] = Field(default_factory=dict)


class SubagentResult(BaseModel):
    """Outcome returned from a subagent back to the Planner."""
    success: bool
    message: str
    entities: Dict[str, Any] = Field(default_factory=dict)
    grounding_refs: List[str] = Field(default_factory=list)


class MutationPlan(BaseModel):
    """Declared before any write/delete/move — what exactly will be changed and why."""
    target_file: str = Field(
        ..., description="Exact path of the file to be modified/created/deleted",
    )
    action: Literal["write", "delete", "move", "mkdir"] = Field(
        ..., description="What operation will be performed",
    )
    why_this_file: str = Field(
        ..., description="Why THIS specific file (cite the rule or data that identified it as the target)",
    )
    similar_files_not_touched: List[str] = Field(
        default_factory=list,
        description="List similar/related files that will NOT be modified and why (e.g., 'lane_b.json — shadow lane, docs say prefer downstream emitter')",
    )


class RuleCitation(BaseModel):
    """Structured citation of the rule that justifies a decision."""
    source_file: str = Field(
        ..., description="Exact path of the file containing the rule (e.g., /reminders/README.MD)",
    )
    source_type: Literal[
        "SYSTEM_PROMPT",   # this system prompt meta-rules
        "ROOT_AGENTS_MD",  # root AGENTS.md
        "README_INVARIANT", # README.md invariant (hard rule, must not be violated)
        "PROCESS_DOC",     # docs/*.md process documentation
        "NESTED_AGENTS_MD", # nested AGENTS.md in subfolder
        "DATA_HINT",       # data file containing a suggestion/candidate/hint (lowest authority)
    ] = Field(
        ..., description="Authority level of this source. README_INVARIANT > PROCESS_DOC > DATA_HINT.",
    )
    rule_quote: str = Field(
        ..., description="Exact quote or close summary of the rule from the source file",
    )


class NextStep(BaseModel):
    current_state: str
    plan_remaining_steps_brief: Annotated[List[str], MinLen(1), MaxLen(8)] = Field(
        ...,
        description="briefly explain the next useful steps",
    )
    decision_justification: RuleCitation = Field(
        ...,
        description=(
            "MANDATORY for EVERY step. Cite the rule that justifies this decision. "
            "Pick the HIGHEST-authority source that applies. "
            "If a README_INVARIANT says 'keep X and Y aligned' but a DATA_HINT says 'update only X' — "
            "the invariant wins, you MUST update both. "
            "If no documented rule exists for a restriction — the restriction does not exist. Act accordingly."
        ),
    )
    scratchpad_update: ScratchpadState = Field(
        default_factory=ScratchpadState,
        description="Обновлённая памятка агента. Записывай найденные ID в found_entities!",
    )
    mutation_plan: Optional[MutationPlan] = Field(
        default=None,
        description=(
            "REQUIRED when function is write/delete/move/mkdir. "
            "Declare WHAT you will change, WHY this file, and which similar files you will NOT touch. "
            "Omit only for read-only operations (read, list, search, tree, find)."
        ),
    )
    task_completed: bool
    subagent_delegation: Optional[SubagentTask] = Field(
        default=None,
        description="Optional: hand off a specific sub-task to a domain subagent"
    )
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
