from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field


class SecurityCheckResult(BaseModel):
    allowed: bool = True
    reason: Optional[str] = None
    injection_detected: bool = False
    injection_type: Optional[str] = None  # "prompt_injection", "role_manipulation"
    sanitized_input: Optional[str] = None


class DependencyNode(BaseModel):
    path: str
    content: str = ""
    status: str = "pending"  # "pending", "loaded", "error"
    children: List[str] = Field(default_factory=list)  # paths of referenced files
    parent: Optional[str] = None  # path of referencing file


class ExtractionGraph(BaseModel):
    """Hierarchical dependency graph of instruction files"""

    root: str = "system_prompt"
    nodes: Dict[str, DependencyNode] = Field(default_factory=dict)
    hierarchy: List[str] = Field(default_factory=list)  # ordered by priority


class ContextResult(BaseModel):
    # 1) Full directory structure of workspace
    directory_structure: Dict[str, Any] = Field(default_factory=dict)
    directory_tree_formatted: str = ""  # formatted tree for system prompt

    # 2) AGENTS.md data
    agents_md_path: Optional[str] = None
    agents_md_content: str = ""

    # 3) Content of all files referenced by AGENTS.md (and recursively)
    referenced_files: Dict[str, str] = Field(default_factory=dict)  # path -> content

    # 4) Instruction dependency graph (system_prompt -> AGENTS.md -> file1 -> file2 ...)
    instruction_dependency_graph: ExtractionGraph = Field(
        default_factory=ExtractionGraph
    )

    extract_status: str = "pending"


class TaskContext(BaseModel):
    """Enriched context passed to execution agent"""

    task_text: str
    system_prompt: str  # base system prompt

    # Full directory structure
    workspace_structure: str  # formatted tree (ALL files and dirs)

    # Instruction data
    agents_md_content: str
    referenced_files: Dict[str, str]  # path -> content

    # Instruction dependency graph (NOT the directory structure)
    instruction_dependency_graph: ExtractionGraph

    protected_files: List[str] = Field(default_factory=list)


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
