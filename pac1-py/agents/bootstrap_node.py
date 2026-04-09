import re
from collections import deque
from typing import Dict, Optional

from agents.state import AgentState
from agents.pcm_helpers import pcm_list, pcm_read, pcm_tree
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from llm_logger import LLMTraceLogger


AGENTS_CANDIDATES = ["AGENTS.MD", "AGENTS.md", "Agent.md", "agent.md"]
LINK_REGEX = re.compile(r"\[.*?\]\(([^)]+\.(?:md|MD))\)", re.IGNORECASE)
BARE_MD_REGEX = re.compile(
    r"""(?:^|[\s"'`(])([A-Za-z0-9_.\-/]+?\.(?:md|MD))(?:$|[\s"'`),.:;])""",
    re.IGNORECASE,
)


def _normalize_path(path: str) -> str:
    value = (path or "").strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    if value.startswith("/"):
        value = value[1:]
    return value


def _dirname(path: str) -> str:
    normalized = _normalize_path(path)
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def _join_relative(base_path: str, target: str) -> str:
    normalized_target = _normalize_path(target)
    if not normalized_target:
        return ""
    if "/" in normalized_target:
        return normalized_target
    base_dir = _dirname(base_path)
    return f"{base_dir}/{normalized_target}".strip("/")


def _resolve_agents_path(vm_client: PcmRuntimeClientSync) -> Optional[str]:
    for candidate in AGENTS_CANDIDATES:
        if pcm_read(vm_client, candidate, allow_missing=True) is not None:
            return candidate
    return None


def _extract_doc_refs(base_path: str, content: str) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()

    for regex in (LINK_REGEX, BARE_MD_REGEX):
        for match in regex.finditer(content):
            candidate = _join_relative(base_path, match.group(1))
            lowered = candidate.lower()
            if candidate and lowered not in seen:
                seen.add(lowered)
                refs.append(candidate)
    return refs


def _classify_doc(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith("agents.md"):
        return "nested_agents"
    if lowered.endswith("readme.md"):
        return "readme"
    if "process" in lowered or "workflow" in lowered or "policy" in lowered:
        return "referenced_process"
    if "schema" in lowered or "records" in lowered or "invariants" in lowered:
        return "schema_doc"
    return "referenced_doc"


def run_bootstrap(
    state: AgentState,
    vm_client: PcmRuntimeClientSync,
    trace_logger: Optional[LLMTraceLogger] = None,
    *,
    max_docs: int = 40,
    max_depth: int = 4,
) -> AgentState:
    rules: Dict[str, str] = {}
    provenance: Dict[str, str] = {}
    graph_edges: Dict[str, list[str]] = {}

    agents_path = _resolve_agents_path(vm_client)
    agents_content = pcm_read(vm_client, agents_path, allow_missing=True) if agents_path else None

    if not agents_content:
        state["workspace_rules"] = rules
        state["workspace_metadata"] = {
            "bootstrap_status": "failed",
            "reason": "AGENTS.md not found",
        }
        if trace_logger:
            trace_logger.log_agent_event(
                agent_name="bootstrap_node",
                event="bootstrap_failed",
                details={"reason": "AGENTS.md not found"},
            )
        return state

    queue = deque([(agents_path, agents_content, 0, "root_agents")])
    visited: set[str] = set()

    while queue and len(rules) < max_docs:
        current_path, current_content, depth, doc_kind = queue.popleft()
        normalized_path = _normalize_path(current_path)
        lowered = normalized_path.lower()
        if lowered in visited:
            continue

        visited.add(lowered)
        rules[f"/{normalized_path}"] = current_content
        provenance[f"/{normalized_path}"] = doc_kind

        if depth >= max_depth:
            continue

        refs = _extract_doc_refs(normalized_path, current_content)
        graph_edges[f"/{normalized_path}"] = [f"/{item}" for item in refs]

        for ref in refs:
            if ref.lower() in visited:
                continue
            ref_content = pcm_read(vm_client, ref, allow_missing=True)
            if ref_content is None:
                continue
            queue.append((ref, ref_content, depth + 1, _classify_doc(ref)))

    workspace_roots = pcm_list(vm_client, "/")
    workspace_tree = pcm_tree(vm_client, "/", level=3)

    rules["workspace_root_ls"] = workspace_roots
    rules["workspace_tree"] = workspace_tree

    state["workspace_rules"] = rules
    state["workspace_metadata"] = {
        "bootstrap_status": "complete",
        "root_agents_path": agents_path,
        "doc_provenance": provenance,
        "instruction_graph": graph_edges,
        "loaded_docs": list(rules.keys()),
    }

    if trace_logger:
        trace_logger.log_agent_event(
            agent_name="bootstrap_node",
            event="bootstrap_completed",
            details={
                "agents_path": agents_path,
                "docs_loaded": len(rules),
                "provenance": provenance,
            },
        )

    return state
