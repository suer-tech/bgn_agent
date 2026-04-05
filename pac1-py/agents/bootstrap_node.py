"""Bootstrap Node — deterministic rules loader (zero LLM calls).

Reads /AGENTS.md, extracts all markdown links via regex,
reads each referenced file, and populates state["workspace_rules"].
"""

import re
from typing import List, Optional

from agents.types import AgentState
from agents.pcm_helpers import safe_read_file
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import TreeRequest
from llm_logger import LLMTraceLogger
from agents.pcm_helpers import safe_read_file, format_tree


# Multiple candidate names for the agents file
AGENTS_CANDIDATES = ["AGENTS.MD", "AGENTS.md", "Agent.md", "agent.md"]

# Regex to extract markdown links: [text](path.md)
LINK_REGEX = re.compile(r'\[.*?\]\((.*?\.md)\)')

# Additional regex for bare .md references
BARE_MD_REGEX = re.compile(
    r"""(?:^|[\s"'`(])([A-Za-z0-9_.\-/]+\.md)(?:$|[\s"'`),.:;])""",
    re.IGNORECASE,
)


def _normalize_path(path: str) -> str:
    """Normalize a relative path."""
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    # Remove leading slash for relative paths
    if p.startswith("/"):
        p = p[1:]
    return p


def _extract_md_links(content: str) -> List[str]:
    """Extract unique .md file paths from markdown content using regex."""
    paths = set()

    # Standard markdown links [text](file.md)
    for match in LINK_REGEX.finditer(content):
        p = _normalize_path(match.group(1))
        if p:
            paths.add(p)

    # Bare .md references
    for match in BARE_MD_REGEX.finditer(content):
        p = _normalize_path(match.group(1))
        if p and p.lower() not in {"agents.md"}:  # Don't re-read agents.md
            paths.add(p)

    return list(paths)


def run_bootstrap(
    state: AgentState,
    vm_client: PcmRuntimeClientSync,
    trace_logger: Optional[LLMTraceLogger] = None,
) -> AgentState:
    """Load workspace rules deterministically (no LLM calls).

    1. Find and read /AGENTS.md
    2. Extract all .md links via regex
    3. Read each referenced file
    4. Populate state["workspace_rules"]

    Args:
        state: Current agent state.
        vm_client: PCM runtime client.
        trace_logger: Optional logger for diagnostics.

    Returns:
        Updated AgentState with workspace_rules populated.
    """
    rules = {}

    # Step 1: Find AGENTS.md
    agents_path = None
    agents_content = None

    for candidate in AGENTS_CANDIDATES:
        content = safe_read_file(vm_client, candidate)
        if content is not None:
            agents_path = candidate
            agents_content = content
            break

    if trace_logger:
        trace_logger.log_agent_event(
            agent_name="bootstrap_node",
            event="agents_md_search",
            details={
                "candidates_tried": AGENTS_CANDIDATES,
                "found": agents_path,
                "content_length": len(agents_content) if agents_content else 0,
            },
        )

    if not agents_content:
        if trace_logger:
            trace_logger.log_agent_event(
                agent_name="bootstrap_node",
                event="agents_md_not_found",
                details={"error": "No AGENTS.md found in any candidate path"},
            )
        state["workspace_rules"] = rules
        return state

    # Store AGENTS.md with canonical key
    rules["/AGENTS.md"] = agents_content

    # Step 2: Extract all referenced .md links
    referenced_paths = _extract_md_links(agents_content)

    if trace_logger:
        trace_logger.log_agent_event(
            agent_name="bootstrap_node",
            event="links_extracted",
            details={
                "referenced_paths": referenced_paths,
                "count": len(referenced_paths),
            },
        )

    # Step 3: Read each referenced file
    for rel_path in referenced_paths:
        # Try both with and without leading slash
        content = safe_read_file(vm_client, rel_path)
        if content is None:
            content = safe_read_file(vm_client, f"/{rel_path}")

        if content is not None:
            key = f"/{rel_path}" if not rel_path.startswith("/") else rel_path
            rules[key] = content

            if trace_logger:
                trace_logger.log_agent_event(
                    agent_name="bootstrap_node",
                    event="rule_file_loaded",
                    details={
                        "path": key,
                        "content_length": len(content),
                        "content_preview": content[:200],
                    },
                )
        else:
            if trace_logger:
                trace_logger.log_agent_event(
                    agent_name="bootstrap_node",
                    event="rule_file_not_found",
                    details={"path": rel_path},
                )

    # Step 4: Deterministic tree extraction for /99_process/
    try:
        tree_result = vm_client.tree(TreeRequest(root="/99_process/", level=2))
        formatted_tree = format_tree({"root": "/99_process/", "level": 2}, tree_result)
        rules["tree_process"] = formatted_tree
        
        if trace_logger:
            trace_logger.log_agent_event(
                agent_name="bootstrap_node",
                event="process_tree_extracted",
                details={
                    "root": "/99_process/",
                    "tree_preview": formatted_tree[:200]
                },
            )
    except Exception as e:
        if trace_logger:
            trace_logger.log_agent_event(
                agent_name="bootstrap_node",
                event="process_tree_failed",
                details={"error": str(e)},
            )
        rules["tree_process"] = "Failed to load /99_process/ tree"

    state["workspace_rules"] = rules

    if trace_logger:
        trace_logger.log_agent_event(
            agent_name="bootstrap_node",
            event="bootstrap_completed",
            details={
                "total_rules_loaded": len(rules),
                "rule_paths": list(rules.keys()),
            },
        )

    return state
