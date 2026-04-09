"""Bootstrap Node — universal workspace explorer (zero LLM calls in Phase 1).

Phase 1 (deterministic):
  1. tree / → full workspace structure
  2. Read root AGENTS.md
  3. Extract ALL links from AGENTS.md (any file type, directories)
  4. Read each linked file; ls linked directories
  5. Populate state with tree + agents_md + linked_files

Phase 2 (1 LLM call — context advisor):
  - Given tree + AGENTS.md + linked files + task text
  - LLM decides which additional instruction files to pre-load
  - Output: list of paths

Phase 3 (deterministic):
  - Read files recommended by Phase 2
  - Add to state
"""

import re
from typing import List, Optional, Tuple

from agents.types import (
    AgentState,
    AuthorityMap,
    AuthorityRule,
    AuthorityLevel,
    ContextAdvice,
)
from agents.pcm_helpers import safe_read_file, safe_list, format_tree
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import TreeRequest
from llm_logger import LLMTraceLogger


# Multiple candidate names for the agents file
AGENTS_CANDIDATES = ["AGENTS.MD", "AGENTS.md", "Agent.md", "agent.md"]

# Regex: markdown links [text](path) — captures any path, not just .md
MARKDOWN_LINK_REGEX = re.compile(r'\[.*?\]\(([^)]+)\)')

# Regex: backtick-quoted paths like `docs/channels/` or `99_process/`
BACKTICK_PATH_REGEX = re.compile(r'`([A-Za-z0-9_.\-/]+(?:\.\w+)?/?)`')

# Regex: bare file references with extensions
BARE_FILE_REGEX = re.compile(
    r"""(?:^|[\s"'(])([A-Za-z0-9_.\-/]+\.\w{1,5})(?:$|[\s"'),.:;])""",
)


CONTEXT_ADVISOR_PROMPT = """\
You are a context advisor for an AI agent that operates inside a file-based workspace.

You are given:
1. The workspace directory tree
2. The root AGENTS.md (main instruction file) and files it references
3. The user's task

Your job: decide which ADDITIONAL instruction/rule files the executor needs to pre-load \
in order to have a COMPLETE understanding of workspace rules BEFORE it starts working.

Rules:
- Only recommend INSTRUCTION files: README, AGENTS.md, docs/*.md, process docs, schema docs, channel configs (.txt).
- Do NOT recommend DATA files: individual records (.json in data folders), inbox messages, notes content.
- If AGENTS.md says "read README.md in each folder" or "read docs/ before acting" — list the specific files.
- If a linked file references other instruction files — include those too.
- If the tree shows folders with AGENTS.md or README.md that weren't loaded — include them.
- Keep the list focused: only files that contain RULES, SCHEMAS, or WORKFLOW definitions.

Respond with JSON matching the ContextAdvice schema."""


def _normalize_path(path: str) -> str:
    """Normalize a relative path."""
    p = (path or "").strip().replace("\\", "/")
    # Remove fragment anchors
    if "#" in p:
        p = p.split("#")[0]
    while p.startswith("./"):
        p = p[2:]
    # Remove leading slash for consistency
    if p.startswith("/"):
        p = p[1:]
    return p


def _extract_all_links(content: str) -> List[str]:
    """Extract all file/directory paths from AGENTS.md content.

    Catches: markdown links, backtick-quoted paths, bare file references.
    Returns deduplicated list of normalized paths.
    """
    paths = set()

    # 1. Markdown links: [text](path)
    for match in MARKDOWN_LINK_REGEX.finditer(content):
        p = _normalize_path(match.group(1))
        if p and not p.startswith("http"):
            paths.add(p)

    # 2. Backtick-quoted paths: `docs/channels/`
    for match in BACKTICK_PATH_REGEX.finditer(content):
        p = _normalize_path(match.group(1))
        if p and len(p) > 2:  # Skip very short fragments
            paths.add(p)

    # 3. Bare file references with extensions
    for match in BARE_FILE_REGEX.finditer(content):
        p = _normalize_path(match.group(1))
        if p and p.lower() not in ("agents.md", "agents.md"):
            paths.add(p)

    return list(paths)


def _is_directory_path(path: str) -> bool:
    """Heuristic: does this path look like a directory reference?"""
    return path.endswith("/") or ("." not in path.split("/")[-1])


def _read_or_ls(
    vm_client: PcmRuntimeClientSync,
    path: str,
) -> Tuple[Optional[str], List[str]]:
    """Read a file or list a directory. Returns (content_or_None, child_paths)."""
    normalized = path.rstrip("/")

    if _is_directory_path(path):
        # Try to list directory
        entries = safe_list(vm_client, f"/{normalized}")
        if entries:
            child_paths = []
            for entry in entries:
                name = entry.get("name", "")
                if name:
                    child_paths.append(f"{normalized}/{name}")
            return None, child_paths
        # Maybe it's actually a file without extension
        content = safe_read_file(vm_client, normalized)
        if content is None:
            content = safe_read_file(vm_client, f"/{normalized}")
        return content, []
    else:
        # Try to read as file
        content = safe_read_file(vm_client, normalized)
        if content is None:
            content = safe_read_file(vm_client, f"/{normalized}")
        return content, []


def run_bootstrap(
    state: AgentState,
    vm_client: PcmRuntimeClientSync,
    trace_logger: Optional[LLMTraceLogger] = None,
    llm_provider=None,
) -> AgentState:
    """Universal workspace explorer: load rules from workspace structure.

    Phase 1: deterministic (0 LLM calls)
    Phase 2: 1 LLM call for context advice
    Phase 3: deterministic read of advised files
    """
    rules = {}
    auth_map = AuthorityMap()

    # =====================================================================
    # Phase 1: Deterministic Discovery
    # =====================================================================

    # --- Step 1: Full repo tree ---
    tree_formatted = ""
    try:
        tree_result = vm_client.tree(TreeRequest(root="/", level=3))
        tree_formatted = format_tree({"root": "/", "level": 3}, tree_result)
        rules["tree_process"] = tree_formatted
    except Exception:
        rules["tree_process"] = "Failed to load tree"

    # --- Step 2: Find and read root AGENTS.md ---
    agents_path = None
    agents_content = None

    for candidate in AGENTS_CANDIDATES:
        content = safe_read_file(vm_client, candidate)
        if content is not None:
            agents_path = f"/{candidate}" if not candidate.startswith("/") else candidate
            agents_content = content
            break

    if agents_content:
        rules["/AGENTS.md"] = agents_content
        auth_map.rules.append(AuthorityRule(
            path=agents_path,
            content=agents_content,
            level=AuthorityLevel.ROOT,
            scope="/",
        ))

    # --- Step 3: Extract ALL links from AGENTS.md (if found) ---
    referenced_paths = _extract_all_links(agents_content) if agents_content else []

    # --- Step 4: Read each linked file / ls each linked directory ---
    for ref_path in referenced_paths:
        content, children = _read_or_ls(vm_client, ref_path)

        if content is not None:
            key = f"/{ref_path}" if not ref_path.startswith("/") else ref_path
            rules[key] = content
            auth_map.rules.append(AuthorityRule(
                path=key,
                content=content,
                level=AuthorityLevel.PROCESS,
                scope="/",
            ))
        elif children:
            # Directory was listed — read instruction files inside
            for child_path in children:
                child_name = child_path.split("/")[-1]
                # Only auto-read instruction-like files from directories
                if child_name.upper() in ("AGENTS.MD", "README.MD", "README.md", "AGENTS.md"):
                    child_content = safe_read_file(vm_client, child_path)
                    if child_content is None:
                        child_content = safe_read_file(vm_client, f"/{child_path}")
                    if child_content is not None:
                        key = f"/{child_path}" if not child_path.startswith("/") else child_path
                        scope = "/".join(key.split("/")[:-1]) or "/"
                        rules[key] = child_content
                        auth_map.rules.append(AuthorityRule(
                            path=key,
                            content=child_content,
                            level=AuthorityLevel.FOLDER,
                            scope=scope,
                        ))

    if trace_logger:
        trace_logger.log_agent_event(
            agent_name="bootstrap_node",
            event="phase1_completed",
            details={
                "rules_loaded": len(rules),
                "referenced_paths": referenced_paths,
            },
        )

    # =====================================================================
    # Phase 2: LLM Context Advisor (1 call)
    # =====================================================================
    if llm_provider is not None:
        # Build context summary for the advisor
        loaded_files_summary = "\n".join(
            f"- {path} ({len(content)} chars)"
            for path, content in rules.items()
            if path != "tree_process"
        )

        loaded_contents = "\n\n".join(
            f"=== {path} ===\n{content[:1000]}"
            for path, content in rules.items()
            if path != "tree_process"
        )

        advisor_messages = [
            {"role": "system", "content": CONTEXT_ADVISOR_PROMPT},
            {"role": "user", "content": (
                f"WORKSPACE TREE:\n{tree_formatted}\n\n"
                f"ALREADY LOADED FILES:\n{loaded_files_summary}\n\n"
                f"LOADED FILE CONTENTS:\n{loaded_contents}\n\n"
                f"USER TASK:\n{state['task_text']}"
            )},
        ]

        try:
            advice = llm_provider.complete_as(advisor_messages, ContextAdvice)

            if trace_logger:
                trace_logger.log_agent_event(
                    agent_name="bootstrap_node",
                    event="context_advice_received",
                    details={
                        "additional_paths": advice.additional_paths,
                        "reasoning": advice.reasoning,
                    },
                )

            # =============================================================
            # Phase 3: Read advised files
            # =============================================================
            for adv_path in advice.additional_paths:
                norm = _normalize_path(adv_path)
                key = f"/{norm}" if not norm.startswith("/") else norm

                # Skip already loaded
                if key in rules:
                    continue

                content, children = _read_or_ls(vm_client, norm)

                if content is not None:
                    rules[key] = content
                    # Determine authority level
                    name_lower = norm.split("/")[-1].lower()
                    if name_lower in ("agents.md",):
                        level = AuthorityLevel.NESTED
                    elif name_lower in ("readme.md",):
                        level = AuthorityLevel.FOLDER
                    else:
                        level = AuthorityLevel.PROCESS
                    scope = "/".join(key.split("/")[:-1]) or "/"
                    auth_map.rules.append(AuthorityRule(
                        path=key,
                        content=content,
                        level=level,
                        scope=scope,
                    ))
                elif children:
                    # Directory — read instruction files inside
                    for child_path in children:
                        child_name = child_path.split("/")[-1].lower()
                        child_key = f"/{child_path}" if not child_path.startswith("/") else child_path
                        if child_key in rules:
                            continue
                        # Read instruction-like files + txt configs
                        if child_name.endswith((".md", ".txt")):
                            child_content = safe_read_file(vm_client, child_path)
                            if child_content is None:
                                child_content = safe_read_file(vm_client, f"/{child_path}")
                            if child_content is not None:
                                rules[child_key] = child_content
                                scope = "/".join(child_key.split("/")[:-1]) or "/"
                                auth_map.rules.append(AuthorityRule(
                                    path=child_key,
                                    content=child_content,
                                    level=AuthorityLevel.FOLDER,
                                    scope=scope,
                                ))

        except Exception as e:
            if trace_logger:
                trace_logger.log_agent_event(
                    agent_name="bootstrap_node",
                    event="context_advice_failed",
                    details={"error": str(e)},
                )

    state["workspace_rules"] = rules
    state["authority_map"] = auth_map

    if trace_logger:
        trace_logger.log_agent_event(
            agent_name="bootstrap_node",
            event="bootstrap_completed",
            details={
                "total_rules_loaded": len(rules),
                "authority_rules_count": len(auth_map.rules),
            },
        )

    return state
