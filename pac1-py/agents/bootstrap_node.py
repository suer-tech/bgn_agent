"""Bootstrap Node — deterministic rules loader (zero LLM calls).

Reads /AGENTS.md, extracts all markdown links via regex,
reads each referenced file, and populates state["workspace_rules"].
"""

import re
from typing import List, Optional

from agents.types import (
    AgentState, 
    AuthorityMap, 
    AuthorityRule, 
    AuthorityLevel, 
    DomainType
)
from agents.pcm_helpers import safe_read_file, format_tree
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import TreeRequest
from llm_logger import LLMTraceLogger


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

    1. Find and read /AGENTS.md (Root Authority)
    2. Extract and read referenced files (Process Authority)
    3. Perform domain-conditioned discovery (Folder/Nested Authority)
    4. Populate hierarchical authority_map and flat workspace_rules.
    """
    rules = {}
    auth_map = AuthorityMap()
    triage = state.get("triage_result")
    domain = triage.domain if triage else DomainType.GENERAL

    # --- Step 1: Find Root AGENTS.md ---
    agents_path = None
    agents_content = None

    for candidate in AGENTS_CANDIDATES:
        content = safe_read_file(vm_client, candidate)
        if content is not None:
            agents_path = f"/{candidate}" if not candidate.startswith("/") else candidate
            agents_content = content
            break

    if not agents_content:
        state["workspace_rules"] = rules
        state["authority_map"] = auth_map
        return state

    # Add Root Authority
    rules["/AGENTS.md"] = agents_content
    auth_map.rules.append(AuthorityRule(
        path=agents_path,
        content=agents_content,
        level=AuthorityLevel.ROOT,
        scope="/"
    ))

    # --- Step 2: Extract Referenced Process Rules ---
    referenced_paths = _extract_md_links(agents_content)
    for rel_path in referenced_paths:
        content = safe_read_file(vm_client, rel_path)
        if content is None:
            content = safe_read_file(vm_client, f"/{rel_path}")

        if content is not None:
            key = f"/{rel_path}" if not rel_path.startswith("/") else rel_path
            rules[key] = content
            auth_map.rules.append(AuthorityRule(
                path=key,
                content=content,
                level=AuthorityLevel.PROCESS,
                scope="/"
            ))

    # --- Step 3: Domain-Conditioned Discovery ---
    # Load READMEs for all relevant folders + processing docs
    domain_discovery_paths = []
    if domain in (DomainType.KNOWLEDGE_REPO,):
        domain_discovery_paths = [
            "00_inbox/README.md",
            "01_capture/README.md",
            "02_distill/README.md",
            "99_process/README.md",
        ]
    elif domain == DomainType.INBOX_WORKFLOW:
        domain_discovery_paths = [
            "inbox/README.md",
            "docs/inbox-msg-processing.md",
            "docs/inbox-task-processing.md",
            "docs/channels/AGENTS.MD",
            "docs/channels/Discord.txt",
            "docs/channels/Telegram.txt",
            # Note: otp.txt intentionally NOT pre-loaded (sensitive)
            "contacts/README.md",
            "accounts/README.md",
            "outbox/README.md",
            "my-invoices/README.MD",
            "reminders/README.MD",
        ]
    elif domain == DomainType.TYPED_CRM:
        domain_discovery_paths = [
            "contacts/README.md",
            "accounts/README.md",
            "outbox/README.md",
            "my-invoices/README.MD",
            "reminders/README.MD",
            "opportunities/README.MD",
            "01_notes/README.MD",
        ]
    elif domain == DomainType.REPAIR_DIAGNOSTICS:
        domain_discovery_paths = [
            "docs/repair/README.md",
            "config/README.md",
        ]

    for path in domain_discovery_paths:
        content = safe_read_file(vm_client, path)
        if content:
            key = f"/{path}" if not path.startswith("/") else path
            scope = "/".join(key.split("/")[:-1]) or "/"
            rules[key] = content
            auth_map.rules.append(AuthorityRule(
                path=key,
                content=content,
                level=AuthorityLevel.FOLDER,
                scope=scope
            ))

    # --- Step 4: Nested AGENTS.md Discovery (Heuristic) ---
    # We look for AGENTS.md in common subdirectories if relevant
    nested_candidates = []
    if domain == DomainType.TYPED_CRM:
        nested_candidates = ["contacts/AGENTS.md", "accounts/AGENTS.md"]
    elif domain == DomainType.KNOWLEDGE_REPO:
        nested_candidates = ["99_process/AGENTS.md"]

    for path in nested_candidates:
        content = safe_read_file(vm_client, path)
        if content:
            key = f"/{path}" if not path.startswith("/") else path
            scope = "/".join(key.split("/")[:-1]) or "/"
            rules[key] = content
            auth_map.rules.append(AuthorityRule(
                path=key,
                content=content,
                level=AuthorityLevel.NESTED,
                scope=scope
            ))

    # --- Step 5: Full repo tree for orientation ---
    try:
        tree_result = vm_client.tree(TreeRequest(root="/", level=2))
        formatted_tree = format_tree({"root": "/", "level": 2}, tree_result)
        rules["tree_process"] = formatted_tree
    except:
        try:
            tree_result = vm_client.tree(TreeRequest(root="/99_process/", level=2))
            formatted_tree = format_tree({"root": "/99_process/", "level": 2}, tree_result)
            rules["tree_process"] = formatted_tree
        except:
            rules["tree_process"] = "Failed to load tree"

    state["workspace_rules"] = rules
    state["authority_map"] = auth_map

    if trace_logger:
        trace_logger.log_agent_event(
            agent_name="bootstrap_node",
            event="bootstrap_completed",
            details={
                "total_rules_loaded": len(rules),
                "authority_rules_count": len(auth_map.rules),
                "domain": domain.value
            },
        )

    return state
