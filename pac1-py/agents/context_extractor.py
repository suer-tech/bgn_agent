import re
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field

from agents.types import ContextResult, TaskContext, ExtractionGraph, DependencyNode
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import TreeRequest, ReadRequest
from google.protobuf.json_format import MessageToDict
from llm_logger import LLMTraceLogger


AGENTS_CANDIDATES = ["AGENTS.MD", "AGENTS.md", "Agent.md", "agent.md"]


class LinkExtractionResponse(BaseModel):
    referenced_files: List[str] = Field(default_factory=list)


class FileDecisionItem(BaseModel):
    path: str = Field(description="Relative path to the file to read")
    reason: str = Field(description="Why this file is needed for the current task")


class FileDecisionResponse(BaseModel):
    files_to_read: List[FileDecisionItem] = Field(
        default_factory=list,
        description="List of files that should be read next, with reasons",
    )
    reasoning: str = Field(
        description="Explanation of why these files were chosen and what the agent is looking for"
    )
    done: bool = Field(
        description="Set to true when enough context has been gathered and no more files need to be read"
    )


CONTEXT_EXTRACTOR_SYSTEM_PROMPT = (
    "You are a Context Extractor Agent. Your job is to determine which files in the workspace "
    "need to be read to fully understand the context for executing the user's task.\n\n"
    "Rules:\n"
    "1. AGENTS.MD is the main source of truth \u2014 always analyze it first to understand policies, "
    "   workflows, and which files or directories are relevant.\n"
    "2. Only request files that are directly relevant to the user's task.\n"
    "3. Do NOT request files that are templates (files starting with _ like _template.md), "
    "   archives, or historical records unless the task specifically requires them.\n"
    "4. If AGENTS.MD says \"reference only this file\", no additional files need to be read.\n"
    "5. If AGENTS.MD points to specific policy files or directories, prioritize those.\n"
    "6. Be conservative \u2014 request the minimum number of files needed to understand the task.\n"
    "7. Set done=true when you have enough context to proceed with task execution.\n"
    "8. Always use paths exactly as they appear in the directory tree. Do not invent paths.\n\n"
    "Return your decision as a structured response with files_to_read, reasoning, and done flag."
)


def _normalize_rel_path(path: str) -> str:
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if p.startswith("/"):
        p = p[1:]
    return p


def _to_abs_path(path: str) -> str:
    p = _normalize_rel_path(path)
    if not p:
        return "/"
    return f"/{p}"


def _join_paths(base_path: str, target: str) -> str:
    target = _normalize_rel_path(target)
    if not target:
        return ""
    if "/" not in target:
        base_dir = (
            _normalize_rel_path(base_path).rsplit("/", 1)[0]
            if "/" in _normalize_rel_path(base_path)
            else ""
        )
        return f"{base_dir}/{target}".strip("/")
    return target


def _extract_links_regex(content: str) -> List[str]:
    """Extract markdown file references using regex."""
    refs: List[str] = []
    patterns = [
        r"""(?:^|[\s"'`(])([A-Za-z0-9_.\-/]+\.md)(?:$|[\s"'`),.:;])""",
        r"""(?:see|read|open|check)\s+['"`]([^'"`]+\.md)['"`]""",
    ]
    for p in patterns:
        for m in re.finditer(p, content, flags=re.IGNORECASE):
            v = _normalize_rel_path(m.group(1))
            if v:
                refs.append(v)
    out: List[str] = []
    seen = set()
    for r in refs:
        k = r.lower()
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _build_tree_summary(tree_data: Dict[str, Any]) -> str:
    """Build a compact text summary of the directory tree for LLM context."""
    lines: List[str] = []

    def _walk(node, prefix=""):
        name = node.get("name", node.get("path", "").split("/")[-1] or "/")
        is_dir = node.get("isDir", node.get("is_dir", False))
        tag = "[DIR] " if is_dir else ""
        lines.append(f"{prefix}{tag}{name}")
        if is_dir:
            children = node.get("children", [])
            if isinstance(children, dict):
                children = children.get("children", [])
            for child in children if isinstance(children, list) else []:
                _walk(child, prefix + "    ")

    if isinstance(tree_data, dict):
        root = tree_data.get("root", {})
        if root:
            _walk(root)
    return "\n".join(lines)


def _collect_all_paths(tree_data: Dict[str, Any], prefix: str = "") -> List[str]:
    """Collect all file paths from the tree structure."""
    paths: List[str] = []

    def _walk(node, current_prefix: str):
        name = node.get("name", node.get("path", "").split("/")[-1] or "/")
        is_dir = node.get("isDir", node.get("is_dir", False))
        full_path = f"{current_prefix}/{name}".lstrip("/") if current_prefix else name

        if not is_dir:
            paths.append(full_path)
        else:
            children = node.get("children", [])
            if isinstance(children, dict):
                children = children.get("children", [])
            for child in children if isinstance(children, list) else []:
                _walk(child, full_path)

    if isinstance(tree_data, dict):
        root = tree_data.get("root", {})
        if root:
            _walk(root, "")
    return paths


def _format_tree_entry(entry, prefix: str = "", is_last: bool = True) -> list[str]:
    """Format a tree entry for display."""
    branch = "└── " if is_last else "├── "
    lines = [f"{prefix}{branch}{entry.name}"]
    child_prefix = f"{prefix}{'    ' if is_last else '│   '}"
    children = list(entry.children)
    for idx, child in enumerate(children):
        lines.extend(
            _format_tree_entry(
                child,
                prefix=child_prefix,
                is_last=idx == len(children) - 1,
            )
        )
    return lines


class ContextExtractor:
    """Context Extractor Agent for PAC1.

    Performs TWO independent tasks:
    A) Get full directory structure of workspace
    B) Build instruction dependency graph (AGENTS.md -> referenced files)
    """

    def __init__(self, provider=None, trace_logger: LLMTraceLogger = None):
        self.provider = provider
        self.trace_logger = trace_logger

    def _read_path(self, vm: PcmRuntimeClientSync, path: str) -> Optional[str]:
        """Read file content from PCM runtime."""
        try:
            result = vm.read(ReadRequest(path=path))
            parsed = MessageToDict(result)
            content = parsed.get("content", "")
            return content if isinstance(content, str) else None
        except Exception:
            return None

    def _get_tree(
        self, vm: PcmRuntimeClientSync, root: str = "/", level: int = 3
    ) -> Dict[str, Any]:
        """Get directory tree structure."""
        try:
            result = vm.tree(TreeRequest(root=root, level=level))
            return MessageToDict(result)
        except Exception:
            return {}

    def _format_tree(self, tree_dict: Dict[str, Any]) -> str:
        """Format tree dict to readable string."""
        if not tree_dict:
            return "."

        root = tree_dict.get("root", {})
        if not root:
            return "."

        lines = []
        name = root.get("name", "")
        if name:
            lines.append(name)

        def format_children(children: List[Dict], prefix: str = ""):
            result = []
            for idx, child in enumerate(children):
                is_last = idx == len(children) - 1
                branch = "└── " if is_last else "├── "
                child_name = child.get("name", "")
                is_dir = child.get("isDir", False)
                display = f"{child_name}/" if is_dir else child_name
                result.append(f"{prefix}{branch}{display}")

                child_prefix = f"{prefix}{'    ' if is_last else '│   '}"
                grandchildren = child.get("children", [])
                if grandchildren:
                    result.extend(format_children(grandchildren, child_prefix))
            return result

        children = root.get("children", [])
        if children:
            lines.extend(format_children(children))

        return "\n".join(lines) if lines else "."

    def _resolve_agents_path(self, vm: PcmRuntimeClientSync) -> Optional[str]:
        """Find AGENTS.md file (check multiple name variants)."""
        for p in AGENTS_CANDIDATES:
            content = self._read_path(vm, p)
            if isinstance(content, str):
                return p
        return None

    def _extract_links_llm(self, content: str, current_path: str) -> List[str]:
        """Use LLM to extract file references from content."""
        if not self.provider or not content.strip():
            return []
        try:
            msg = [
                {
                    "role": "system",
                    "content": (
                        "Extract only file references to markdown files (*.md). "
                        "Return relative paths only, no commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Current file: {current_path}\n\n"
                        f"Content:\n{content}\n\n"
                        "Return references mentioned directly or implied by read/see instructions."
                    ),
                },
            ]
            parsed = self.provider.complete_as(msg, LinkExtractionResponse)
            refs = [_normalize_rel_path(x) for x in parsed.referenced_files]
            return [r for r in refs if r.lower().endswith(".md")]
        except Exception:
            return []

    def _decide_next_files(
        self,
        task_text: str,
        agents_content: str,
        tree_summary: str,
        all_paths: List[str],
        already_read: Dict[str, str],
        visited_paths: List[str] = None,
    ) -> FileDecisionResponse:
        """Use LLM to decide which files to read next based on task, AGENTS.MD, and current context."""
        if not self.provider:
            return FileDecisionResponse(done=True, reasoning="No LLM provider available")

        read_files_summary = ""
        if already_read:
            parts = []
            for p, c in already_read.items():
                preview = c[:400].replace("\n", " ")
                parts.append(f"### {p}\n{preview}...")
            read_files_summary = "\n\n".join(parts)

        available_paths = "\n".join(f"  - {p}" for p in all_paths)

        visited_list = ""
        if visited_paths:
            visited_list = "\n".join(f"  - {p}" for p in sorted(visited_paths))

        user_msg = (
            f"Task: {task_text}\n\n"
            f"## Directory Tree\n{tree_summary}\n\n"
            f"## All Available File Paths\n{available_paths}\n\n"
            f"## AGENTS.MD Content\n{agents_content}\n\n"
            f"## Already Read Files (content shown)\n"
            f"{read_files_summary if read_files_summary else '(none yet \u2014 AGENTS.MD was read but is not listed here)'}\n\n"
            f"## Already Visited Files (DO NOT re-read these)\n"
            f"{visited_list if visited_list else '(none)'}\n\n"
            "CRITICAL: Do NOT request any file listed in 'Already Visited Files' \u2014 they have already been read.\n"
            "Based on the task, AGENTS.MD instructions, and workspace structure, decide which files "
            "need to be read next. Be conservative \u2014 only request files that are truly necessary. "
            "Always use paths exactly as they appear in the All Available File Paths list."
        )

        try:
            msg = [
                {"role": "system", "content": CONTEXT_EXTRACTOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]
            return self.provider.complete_as(msg, FileDecisionResponse)
        except Exception:
            return FileDecisionResponse(
                done=True, reasoning="LLM decision failed, stopping file reads"
            )

    def extract_task_graph(
        self,
        harness_url: str,
        task_text: str,
        max_depth: int = 8,
        max_nodes: int = 50,
    ) -> Dict[str, Any]:
        """Extract workspace context and build instruction dependency graph.

        Returns:
            {
                "graph": {...},  # full extraction data
                "context_docs": {path: content},  # all read files
                "directory_structure": {...},  # tree structure
                "directory_tree_formatted": "...",  # formatted tree string
                "instruction_dependency_graph": ExtractionGraph,  # instruction graph
            }
        """
        vm = PcmRuntimeClientSync(harness_url)

        # ===== TASK A: Full directory structure =====
        if self.trace_logger:
            self.trace_logger.log_agent_event(
                agent_name="context_extractor",
                event="tree_extraction_started",
                details={"root": "/", "level": 3},
            )
        tree_dict = self._get_tree(vm, root="/", level=3)
        tree_formatted = self._format_tree(tree_dict)
        if self.trace_logger:
            self.trace_logger.log_agent_event(
                agent_name="context_extractor",
                event="tree_extraction_completed",
                details={"tree_available": bool(tree_dict), "tree_lines": tree_formatted.count("\n")},
            )

        # ===== TASK B: Instruction dependency graph =====
        context_docs: Dict[str, str] = {}
        graph_nodes: Dict[str, DependencyNode] = {}
        hierarchy: List[str] = ["system_prompt"]

        agents_path = self._resolve_agents_path(vm)
        agents_content = ""

        if self.trace_logger:
            self.trace_logger.log_agent_event(
                agent_name="context_extractor",
                event="agents_md_search_started",
                details={"candidates": ["AGENTS.MD", "AGENTS.md", "Agent.md", "agent.md"]},
            )

        if agents_path:
            agents_content = self._read_path(vm, agents_path) or ""
            if self.trace_logger:
                self.trace_logger.log_agent_event(
                    agent_name="context_extractor",
                    event="agents_md_found",
                    details={
                        "path": agents_path,
                        "content_length": len(agents_content),
                        "content_preview": agents_content[:200],
                    },
                )
            if agents_content:
                context_docs[agents_path] = agents_content
                hierarchy.append(agents_path)

                # Create AGENTS.md node
                graph_nodes[agents_path] = DependencyNode(
                    path=agents_path,
                    content=agents_content,
                    status="loaded",
                    parent="system_prompt",
                )

                # Extract references from AGENTS.md
                if self.trace_logger:
                    self.trace_logger.log_agent_event(
                        agent_name="context_extractor",
                        event="link_extraction_started",
                        details={"source_file": agents_path},
                    )
                llm_refs = self._extract_links_llm(agents_content, agents_path)
                rx_refs = _extract_links_regex(agents_content)
                if self.trace_logger:
                    self.trace_logger.log_agent_event(
                        agent_name="context_extractor",
                        event="link_extraction_completed",
                        details={
                            "llm_refs": llm_refs,
                            "regex_refs": rx_refs,
                            "total_refs": len(set(llm_refs + rx_refs)),
                        },
                    )
                refs = []
                seen_refs = set()
                for ref in llm_refs + rx_refs:
                    resolved = _join_paths(agents_path, ref)
                    if resolved and resolved.lower() not in seen_refs:
                        seen_refs.add(resolved.lower())
                        refs.append(resolved)

                # Update AGENTS.md node with children
                graph_nodes[agents_path].children = refs

                # LLM-driven file reading loop
                tree_summary = _build_tree_summary(tree_dict)
                all_paths = _collect_all_paths(tree_dict)
                visited = set()
                visited.add(agents_path.lower())

                if self.trace_logger:
                    self.trace_logger.log_agent_event(
                        agent_name="context_extractor",
                        event="llm_file_reading_started",
                        details={
                            "tree_summary_lines": tree_summary.count("\n"),
                            "total_available_paths": len(all_paths),
                            "max_nodes": max_nodes,
                        },
                    )

                # Track rounds without progress to detect LLM loops
                rounds_without_progress = 0
                max_stale_rounds = 5

                for _round in range(30):  # max LLM decision rounds
                    if len(graph_nodes) >= max_nodes:
                        break

                    prev_count = len(graph_nodes)

                    if self.trace_logger:
                        self.trace_logger.log_agent_event(
                            agent_name="context_extractor",
                            event="llm_decision_round",
                            details={
                                "round": _round,
                                "files_read_so_far": len(graph_nodes),
                                "stale_rounds": rounds_without_progress,
                            },
                        )

                    decision = self._decide_next_files(
                        task_text=task_text,
                        agents_content=agents_content,
                        tree_summary=tree_summary,
                        all_paths=all_paths,
                        already_read=dict(context_docs),
                        visited_paths=list(visited),
                    )

                    if self.trace_logger:
                        self.trace_logger.log_agent_event(
                            agent_name="context_extractor",
                            event="llm_decision_result",
                            details={
                                "done": decision.done,
                                "files_to_read": [f.path for f in decision.files_to_read],
                                "reasoning": decision.reasoning[:500],
                            },
                        )

                    if decision.done or not decision.files_to_read:
                        break

                    new_files_this_round = 0
                    for item in decision.files_to_read:
                        if len(graph_nodes) >= max_nodes:
                            break

                        npath = _normalize_rel_path(item.path)
                        if not npath or npath.lower() in visited:
                            continue

                        content = self._read_path(vm, npath)
                        if isinstance(content, str):
                            new_files_this_round += 1
                            visited.add(npath.lower())
                            context_docs[npath] = content
                            hierarchy.append(npath)

                            # Extract references via regex as supplementary hints
                            file_rx_refs = _extract_links_regex(content)

                            graph_nodes[npath] = DependencyNode(
                                path=npath,
                                content=content,
                                status="loaded",
                                children=file_rx_refs,
                                parent=agents_path,
                            )

                            if self.trace_logger:
                                self.trace_logger.log_agent_event(
                                    agent_name="context_extractor",
                                    event="file_read",
                                    details={
                                        "path": npath,
                                        "content_length": len(content),
                                        "reason": item.reason,
                                        "referenced_files": file_rx_refs,
                                    },
                                )

                    # Check if we made progress this round
                    if len(graph_nodes) == prev_count:
                        rounds_without_progress += 1
                        if rounds_without_progress >= max_stale_rounds:
                            if self.trace_logger:
                                self.trace_logger.log_agent_event(
                                    agent_name="context_extractor",
                                    event="llm_loop_detected",
                                    details={
                                        "stale_rounds": rounds_without_progress,
                                        "files_read": len(graph_nodes),
                                        "reasoning": "LLM kept suggesting already-read files, stopping to avoid infinite loop",
                                    },
                                )
                            break
                    else:
                        rounds_without_progress = 0

        # Build instruction dependency graph
        instruction_graph = ExtractionGraph(
            root="system_prompt",
            nodes=graph_nodes,
            hierarchy=hierarchy,
        )

        # Build graph summary for output
        graph: Dict[str, Any] = {
            "user_question": task_text,
            "directory_structure": {
                "status": "получен" if tree_dict else "не получен",
                "data": tree_dict,
            },
            "directory_tree_formatted": tree_formatted,
            "agents_md": {
                "path": agents_path,
                "full_path": _to_abs_path(agents_path) if agents_path else None,
                "status": "получен" if agents_content else "не получен",
                "content": agents_content,
                "blocks": graph_nodes.get(agents_path, DependencyNode(path="")).children
                if agents_path
                else [],
            },
            "files": [
                {
                    "path": node.path,
                    "full_path": _to_abs_path(node.path),
                    "status": node.status,
                    "content": node.content[:200] + "..."
                    if len(node.content) > 200
                    else node.content,
                    "blocked_by": node.parent,
                    "blocks": node.children,
                }
                for node in graph_nodes.values()
            ],
            "instruction_dependency_graph": {
                "root": instruction_graph.root,
                "hierarchy": instruction_graph.hierarchy,
                "nodes": {
                    path: {
                        "path": node.path,
                        "status": node.status,
                        "parent": node.parent,
                        "children": node.children,
                    }
                    for path, node in instruction_graph.nodes.items()
                },
            },
            "extract_status": "complete"
            if (tree_dict and agents_content)
            else "pending",
        }

        if self.trace_logger:
            self.trace_logger.log_agent_event(
                agent_name="context_extractor",
                event="extraction_completed",
                details={
                    "files_read": len(graph_nodes),
                    "hierarchy": hierarchy,
                    "extract_status": graph.get("extract_status"),
                },
            )

        return {
            "graph": graph,
            "context_docs": context_docs,
            "directory_structure": tree_dict,
            "directory_tree_formatted": tree_formatted,
            "instruction_dependency_graph": instruction_graph,
        }

    def extract(self, harness_url: str) -> ContextResult:
        """Extract context without task text."""
        return self.extract_with_llm(harness_url=harness_url, task_text="")

    def extract_with_llm(self, harness_url: str, task_text: str) -> ContextResult:
        """Extract context with LLM-based link extraction."""
        payload = self.extract_task_graph(harness_url=harness_url, task_text=task_text)
        graph = payload["graph"]

        protected = ["AGENTS.MD", "AGENTS.md", ".git"]
        if graph.get("agents_md", {}).get("path"):
            protected.append(str(graph["agents_md"]["path"]))

        return ContextResult(
            directory_structure=payload.get("directory_structure", {}),
            directory_tree_formatted=payload.get("directory_tree_formatted", ""),
            agents_md_path=graph.get("agents_md", {}).get("path"),
            agents_md_content=graph.get("agents_md", {}).get("content", ""),
            referenced_files=payload.get("context_docs", {}),
            instruction_dependency_graph=payload.get(
                "instruction_dependency_graph", ExtractionGraph()
            ),
            extract_status=str(graph.get("extract_status", "pending")),
        )

    def to_task_context(
        self, context_result: ContextResult, task_text: str = ""
    ) -> TaskContext:
        """Convert ContextResult to TaskContext for execution agent."""
        protected = (
            list(context_result.directory_structure.keys())
            if context_result.directory_structure
            else []
        )
        if "AGENTS.MD" not in protected:
            protected.append("AGENTS.MD")
        if "AGENTS.md" not in protected:
            protected.append("AGENTS.md")
        if ".git" not in protected:
            protected.append(".git")

        return TaskContext(
            task_text=task_text,
            system_prompt="",  # Will be filled by orchestrator
            workspace_structure=context_result.directory_tree_formatted,
            agents_md_content=context_result.agents_md_content,
            referenced_files=context_result.referenced_files,
            instruction_dependency_graph=context_result.instruction_dependency_graph,
            protected_files=protected,
        )


def create_context_extractor(provider=None, trace_logger: LLMTraceLogger = None):
    """Create a ContextExtractor instance."""
    return ContextExtractor(provider=provider, trace_logger=trace_logger)
