import os
import ast

filepath = r"C:/Users/user2/Documents/BitGN/sandbox-py/agents/context_extractor.py"
NL = chr(10)
BS = chr(92)
DQ = chr(34)
SQ = chr(39)
EM = chr(8212)

lines = []

# Imports
lines.append("import re")
lines.append("from typing import Dict, List, Optional")
lines.append("")
lines.append("from pydantic import BaseModel, Field")
lines.append("")
lines.append("from agents.types import ContextResult, TaskContext")
lines.append("from agents.prompt_storage import get_prompt")
lines.append("from bitgn.vm.mini_connect import MiniRuntimeClientSync")
lines.append("from bitgn.vm.mini_pb2 import OutlineRequest, ReadRequest")
lines.append("from google.protobuf.json_format import MessageToDict")
lines.append("")
lines.append("")

# _get_context_extraction_prompt
lines.append("def _get_context_extraction_prompt() -> str:")
lines.append("    try:")
lines.append("        return get_prompt(" + DQ + "context_extractor" + DQ + ")")
lines.append("    except FileNotFoundError:")
lines.append("        return " + DQ + "You are a Context Extractor Agent." + DQ)
lines.append("")
lines.append("")

# Constants
lines.append("CONTEXT_EXTRACTION_PROMPT = _get_context_extraction_prompt()")
lines.append(
    "AGENTS_CANDIDATES = ["
    + DQ
    + "AGENTS.MD"
    + DQ
    + ", "
    + DQ
    + "AGENTS.md"
    + DQ
    + ", "
    + DQ
    + "Agent.md"
    + DQ
    + ", "
    + DQ
    + "agent.md"
    + DQ
    + "]"
)
lines.append("")
lines.append("")

# LinkExtractionResponse
lines.append("class LinkExtractionResponse(BaseModel):")
lines.append("    referenced_files: List[str] = Field(default_factory=list)")
lines.append("")
lines.append("")

# FileDecisionItem
lines.append("class FileDecisionItem(BaseModel):")
lines.append(
    "    path: str = Field(description="
    + DQ
    + "Relative path to the file to read"
    + DQ
    + ")"
)
lines.append(
    "    reason: str = Field(description="
    + DQ
    + "Why this file is needed for the current task"
    + DQ
    + ")"
)
lines.append("")
lines.append("")

# FileDecisionResponse
lines.append("class FileDecisionResponse(BaseModel):")
lines.append("    files_to_read: List[FileDecisionItem] = Field(")
lines.append("        default_factory=list,")
lines.append(
    "        description="
    + DQ
    + "List of files that should be read next, with reasons"
    + DQ
    + ","
)
lines.append("    )")
lines.append("    reasoning: str = Field(")
lines.append(
    "        description="
    + DQ
    + "Explanation of why these files were chosen and what the agent is looking for"
    + DQ
)
lines.append("    )")
lines.append("    done: bool = Field(")
lines.append(
    "        description="
    + DQ
    + "Set to true when enough context has been gathered and no more files need to be read"
    + DQ
)
lines.append("    )")
lines.append("")
lines.append("")

# CONTEXT_EXTRACTOR_SYSTEM_PROMPT
lines.append("CONTEXT_EXTRACTOR_SYSTEM_PROMPT = (")
lines.append(
    "    "
    + DQ
    + "You are a Context Extractor Agent. Your job is to determine which files in the workspace "
    + DQ
)
lines.append(
    "    "
    + DQ
    + "need to be read to fully understand the context for executing the user"
    + SQ
    + "s task."
    + BS
    + "n"
    + BS
    + "n"
    + DQ
)
lines.append("    " + DQ + "Rules:" + BS + "n" + DQ)
lines.append(
    "    "
    + DQ
    + "1. AGENTS.MD is the main source of truth "
    + EM
    + " always analyze it first to understand policies, "
    + DQ
)
lines.append(
    "    "
    + DQ
    + "   workflows, and which files or directories are relevant."
    + BS
    + "n"
    + DQ
)
lines.append(
    "    "
    + DQ
    + "2. Only request files that are directly relevant to the user"
    + SQ
    + "s task."
    + BS
    + "n"
    + DQ
)
lines.append(
    "    "
    + DQ
    + "3. Do NOT request files that are templates (files starting with _ like _template.md), "
    + DQ
)
lines.append(
    "    "
    + DQ
    + "   archives, or historical records unless the task specifically requires them."
    + BS
    + "n"
    + DQ
)
lines.append(
    "    "
    + DQ
    + "4. If AGENTS.MD says "
    + BS
    + DQ
    + "reference only this file"
    + BS
    + DQ
    + ", no additional files need to be read."
    + BS
    + "n"
    + DQ
)
lines.append(
    "    "
    + DQ
    + "5. If AGENTS.MD points to specific policy files or directories, prioritize those."
    + BS
    + "n"
    + DQ
)
lines.append(
    "    "
    + DQ
    + "6. Be conservative "
    + EM
    + " request the minimum number of files needed to understand the task."
    + BS
    + "n"
    + DQ
)
lines.append(
    "    "
    + DQ
    + "7. Set done=true when you have enough context to proceed with task execution."
    + BS
    + "n"
    + DQ
)
lines.append(
    "    "
    + DQ
    + "8. Always use paths exactly as they appear in the directory tree. Do not invent paths."
    + BS
    + "n"
    + BS
    + "n"
    + DQ
)
lines.append(
    "    "
    + DQ
    + "Return your decision as a structured response with files_to_read, reasoning, and done flag."
    + DQ
)
lines.append(")")
lines.append("")
lines.append("")

# _normalize_rel_path
lines.append("def _normalize_rel_path(path: str) -> str:")
lines.append(
    "    p = (path or "
    + DQ
    + DQ
    + ").strip().replace("
    + BS
    + BS
    + DQ
    + BS
    + DQ
    + ", "
    + DQ
    + "/"
    + DQ
    + ")"
)
lines.append("    while p.startswith(" + DQ + "./" + DQ + "):")
lines.append("        p = p[2:]")
lines.append("    if p.startswith(" + DQ + "/" + DQ + "):")
lines.append("        p = p[1:]")
lines.append("    return p")
lines.append("")
lines.append("")

# _to_abs_path
lines.append("def _to_abs_path(path: str) -> str:")
lines.append("    p = _normalize_rel_path(path)")
lines.append("    if not p:")
lines.append("        return " + DQ + "/" + DQ)
lines.append("    return f" + DQ + "/{p}" + DQ)
lines.append("")
lines.append("")

# _join_paths
lines.append("def _join_paths(base_path: str, target: str) -> str:")
lines.append("    target = _normalize_rel_path(target)")
lines.append("    if not target:")
lines.append("        return " + DQ + DQ)
lines.append("    if " + DQ + "/" + DQ + " not in target:")
lines.append("        base_dir = (")
lines.append(
    "            _normalize_rel_path(base_path).rsplit(" + DQ + "/" + DQ + ", 1)[0]"
)
lines.append("            if " + DQ + "/" + DQ + " in _normalize_rel_path(base_path)")
lines.append("            else " + DQ + DQ)
lines.append("        )")
lines.append(
    "        return f"
    + DQ
    + "{base_dir}/{target}"
    + DQ
    + ".strip("
    + DQ
    + "/"
    + DQ
    + ")"
)
lines.append("    return target")
lines.append("")
lines.append("")

# _extract_exact_literal_answer
lines.append("def _extract_exact_literal_answer(rule_text: str) -> Optional[str]:")
lines.append("    if not isinstance(rule_text, str):")
lines.append("        return None")
lines.append("    patterns = [")
lines.append(
    "        r"
    + DQ
    + DQ
    + DQ
    + "always"
    + BS
    + "s+respond"
    + BS
    + "s+with"
    + BS
    + "s+["
    + DQ
    + SQ
    + "]([^"
    + DQ
    + SQ
    + "]+)["
    + DQ
    + SQ
    + "]"
    + DQ
    + DQ
    + DQ
    + ","
)
lines.append(
    "        r"
    + DQ
    + DQ
    + DQ
    + "respond"
    + BS
    + "s+with"
    + BS
    + "s+exactly"
    + BS
    + "s+["
    + DQ
    + SQ
    + "]([^"
    + DQ
    + SQ
    + "]+)["
    + DQ
    + SQ
    + "]"
    + DQ
    + DQ
    + DQ
    + ","
)
lines.append(
    "        r"
    + DQ
    + DQ
    + DQ
    + "always"
    + BS
    + "s+respond"
    + BS
    + "s+with"
    + BS
    + "s+([A-Za-z0-9._"
    + BS
    + "-/]+)"
    + DQ
    + DQ
    + DQ
    + ","
)
lines.append(
    "        r"
    + DQ
    + DQ
    + DQ
    + "answer"
    + BS
    + "s+with"
    + BS
    + "s+exactly"
    + BS
    + "s+([A-Za-z0-9._"
    + BS
    + "-/]+)"
    + DQ
    + DQ
    + DQ
    + ","
)
lines.append("    ]")
lines.append("    for p in patterns:")
lines.append("        m = re.search(p, rule_text, flags=re.IGNORECASE)")
lines.append("        if m:")
lines.append("            return m.group(1).strip()")
lines.append("    return None")
lines.append("")
lines.append("")

# _extract_policy_dirs
lines.append("def _extract_policy_dirs(rule_text: str) -> List[str]:")
lines.append("    if not isinstance(rule_text, str):")
lines.append("        return []")
lines.append("    found: List[str] = []")
lines.append(
    "    for m in re.finditer(r"
    + DQ
    + DQ
    + DQ
    + "["
    + SQ
    + DQ
    + "`]([a-zA-Z0-9_"
    + BS
    + "-./]+/)["
    + SQ
    + DQ
    + "`]"
    + DQ
    + DQ
    + DQ
    + ", rule_text):"
)
lines.append(
    "        d = _normalize_rel_path(m.group(1)).rstrip(" + DQ + "/" + DQ + ")"
)
lines.append("        if d:")
lines.append("            found.append(d)")
lines.append("    for m in re.finditer(")
lines.append(
    "        r"
    + DQ
    + DQ
    + DQ
    + BS
    + "b([a-zA-Z0-9_"
    + BS
    + "-.]+(?:/[a-zA-Z0-9_"
    + BS
    + "-.]+)*/)"
    + BS
    + "b"
    + DQ
    + DQ
    + DQ
    + ", rule_text"
)
lines.append("    ):")
lines.append(
    "        d = _normalize_rel_path(m.group(1)).rstrip(" + DQ + "/" + DQ + ")"
)
lines.append("        if d and " + DQ + "://" + DQ + " not in d:")
lines.append("            found.append(d)")
lines.append("    out: List[str] = []")
lines.append("    seen = set()")
lines.append("    for d in found:")
lines.append("        k = d.lower()")
lines.append("        if k not in seen:")
lines.append("            seen.add(k)")
lines.append("            out.append(d)")
lines.append("    return out")
lines.append("")
lines.append("")

# _extract_links_regex
lines.append("def _extract_links_regex(content: str) -> List[str]:")
lines.append("    refs: List[str] = []")
lines.append("    patterns = [")
lines.append(
    "        r"
    + DQ
    + DQ
    + DQ
    + "(?:^|["
    + BS
    + "s"
    + DQ
    + SQ
    + "`(])([A-Za-z0-9_."
    + BS
    + "-/]+)"
    + BS
    + ".md)(?:$|["
    + BS
    + "s"
    + DQ
    + SQ
    + "`),.:;])"
    + DQ
    + DQ
    + DQ
    + ","
)
lines.append(
    "        r"
    + DQ
    + DQ
    + DQ
    + "(?:see|read|open|check)"
    + BS
    + "s+["
    + SQ
    + DQ
    + "`]([^"
    + SQ
    + DQ
    + "`]+)"
    + BS
    + ".md)["
    + SQ
    + DQ
    + "`]"
    + DQ
    + DQ
    + DQ
    + ","
)
lines.append("    ]")
lines.append("    for p in patterns:")
lines.append("        for m in re.finditer(p, content, flags=re.IGNORECASE):")
lines.append("            v = _normalize_rel_path(m.group(1))")
lines.append("            if v:")
lines.append("                refs.append(v)")
lines.append("    out: List[str] = []")
lines.append("    seen = set()")
lines.append("    for r in refs:")
lines.append("        k = r.lower()")
lines.append("        if k not in seen:")
lines.append("            seen.add(k)")
lines.append("            out.append(r)")
lines.append("    return out")
lines.append("")
lines.append("")

# _build_tree_summary
lines.append("def _build_tree_summary(tree_data: Dict) -> str:")
lines.append("    lines: List[str] = []")
lines.append("")
lines.append("    def _walk(node, prefix=" + DQ + DQ + "):")
lines.append(
    "        name = node.get("
    + DQ
    + "name"
    + DQ
    + ", node.get("
    + DQ
    + "path"
    + DQ
    + ", "
    + DQ
    + DQ
    + ").split("
    + DQ
    + "/"
    + DQ
    + ")[-1] or "
    + DQ
    + "/"
    + DQ
    + ")"
)
lines.append("        is_dir = node.get(" + DQ + "is_dir" + DQ + ", False)")
lines.append("        tag = " + DQ + "[DIR] " + DQ + " if is_dir else " + DQ + DQ)
lines.append("        lines.append(f" + DQ + "{prefix}{tag}{name}" + DQ + ")")
lines.append("        if is_dir:")
lines.append("            children = node.get(" + DQ + "children" + DQ + ", [])")
lines.append("            if isinstance(children, dict):")
lines.append(
    "                children = children.get(" + DQ + "children" + DQ + ", [])"
)
lines.append("            for child in children if isinstance(children, list) else []:")
lines.append("                _walk(child, prefix + " + DQ + "    " + DQ + ")")
lines.append("")
lines.append("    if isinstance(tree_data, dict):")
lines.append("        _walk(tree_data)")
lines.append("    return " + DQ + BS + "n" + DQ + ".join(lines)")
lines.append("")
lines.append("")

# _collect_all_paths
lines.append(
    "def _collect_all_paths(tree_data: Dict, prefix: str = "
    + DQ
    + DQ
    + ") -> List[str]:"
)
lines.append("    paths: List[str] = []")
lines.append("")
lines.append("    def _walk(node, current_prefix: str):")
lines.append(
    "        name = node.get("
    + DQ
    + "name"
    + DQ
    + ", node.get("
    + DQ
    + "path"
    + DQ
    + ", "
    + DQ
    + DQ
    + ").split("
    + DQ
    + "/"
    + DQ
    + ")[-1] or "
    + DQ
    + "/"
    + DQ
    + ")"
)
lines.append("        is_dir = node.get(" + DQ + "is_dir" + DQ + ", False)")
lines.append(
    "        full_path = f"
    + DQ
    + "{current_prefix}/{name}"
    + DQ
    + ".lstrip("
    + DQ
    + "/"
    + DQ
    + ") if current_prefix else name"
)
lines.append("")
lines.append("        if not is_dir:")
lines.append("            paths.append(full_path)")
lines.append("        else:")
lines.append("            children = node.get(" + DQ + "children" + DQ + ", [])")
lines.append("            if isinstance(children, dict):")
lines.append(
    "                children = children.get(" + DQ + "children" + DQ + ", [])"
)
lines.append("            for child in children if isinstance(children, list) else []:")
lines.append("                _walk(child, full_path)")
lines.append("")
lines.append("    if isinstance(tree_data, dict):")
lines.append("        _walk(tree_data, " + DQ + DQ + ")")
lines.append("    return paths")
lines.append("")
lines.append("")

# ContextExtractor class
lines.append("class ContextExtractor:")
lines.append("    def __init__(self, provider=None):")
lines.append("        self.provider = provider")
lines.append("        self.prompt = CONTEXT_EXTRACTION_PROMPT")
lines.append("")
lines.append(
    "    def _read_path(self, vm: MiniRuntimeClientSync, path: str) -> Optional[str]:"
)
lines.append("        try:")
lines.append("            result = vm.read(ReadRequest(path=path))")
lines.append("            parsed = MessageToDict(result)")
lines.append(
    "            content = parsed.get(" + DQ + "content" + DQ + ", " + DQ + DQ + ")"
)
lines.append("            return content if isinstance(content, str) else None")
lines.append("        except Exception:")
lines.append("            return None")
lines.append("")
lines.append(
    "    def _extract_links_llm(self, content: str, current_path: str) -> List[str]:"
)
lines.append("        if not self.provider or not content.strip():")
lines.append("            return []")
lines.append("        try:")
lines.append("            msg = [")
lines.append("                {")
lines.append(
    "                    " + DQ + "role" + DQ + ": " + DQ + "system" + DQ + ","
)
lines.append("                    " + DQ + "content" + DQ + ": (")
lines.append(
    "                        "
    + DQ
    + "Extract only file references to markdown files (*.md). "
    + DQ
)
lines.append(
    "                        " + DQ + "Return relative paths only, no commentary." + DQ
)
lines.append("                    ),")
lines.append("                },")
lines.append("                {")
lines.append("                    " + DQ + "role" + DQ + ": " + DQ + "user" + DQ + ",")
lines.append("                    " + DQ + "content" + DQ + ": (")
lines.append(
    "                        f"
    + DQ
    + "Current file: {current_path}"
    + BS
    + "n"
    + BS
    + "n"
    + DQ
)
lines.append(
    "                        f"
    + DQ
    + "Content:"
    + BS
    + "n{content}"
    + BS
    + "n"
    + BS
    + "n"
    + DQ
)
lines.append(
    "                        "
    + DQ
    + "Return references mentioned directly or implied by read/see instructions."
    + DQ
)
lines.append("                    ),")
lines.append("                },")
lines.append("            ]")
lines.append(
    "            parsed = self.provider.complete_as(msg, LinkExtractionResponse)"
)
lines.append(
    "            refs = [_normalize_rel_path(x) for x in parsed.referenced_files]"
)
lines.append(
    "            return [r for r in refs if r.lower().endswith("
    + DQ
    + ".md"
    + DQ
    + ")]"
)
lines.append("        except Exception:")
lines.append("            return []")
lines.append("")

# _decide_next_files
lines.append("    def _decide_next_files(")
lines.append("        self,")
lines.append("        task_text: str,")
lines.append("        agents_content: str,")
lines.append("        tree_summary: str,")
lines.append("        all_paths: List[str],")
lines.append("        already_read: Dict[str, str],")
lines.append("    ) -> FileDecisionResponse:")
lines.append("        if not self.provider:")
lines.append(
    "            return FileDecisionResponse(done=True, reasoning="
    + DQ
    + "No LLM provider available"
    + DQ
    + ")"
)
lines.append("")
lines.append("        read_files_summary = " + DQ + DQ)
lines.append("        if already_read:")
lines.append("            parts = []")
lines.append("            for p, c in already_read.items():")
lines.append(
    "                preview = c[:400].replace("
    + DQ
    + BS
    + "n"
    + DQ
    + ", "
    + DQ
    + " "
    + DQ
    + ")"
)
lines.append(
    "                parts.append(f" + DQ + "### {p}" + BS + "n{preview}..." + DQ + ")"
)
lines.append(
    "            read_files_summary = " + DQ + BS + "n" + BS + "n" + DQ + ".join(parts)"
)
lines.append("")
lines.append(
    "        available_paths = "
    + DQ
    + BS
    + "n"
    + DQ
    + ".join(f"
    + DQ
    + "  - {p}"
    + DQ
    + " for p in all_paths)"
)
lines.append("")
lines.append("        user_msg = (")
lines.append("            f" + DQ + "Task: {task_text}" + BS + "n" + BS + "n" + DQ)
lines.append(
    "            f"
    + DQ
    + "## Directory Tree"
    + BS
    + "n{tree_summary}"
    + BS
    + "n"
    + BS
    + "n"
    + DQ
)
lines.append(
    "            f"
    + DQ
    + "## All Available File Paths"
    + BS
    + "n{available_paths}"
    + BS
    + "n"
    + BS
    + "n"
    + DQ
)
lines.append(
    "            f"
    + DQ
    + "## AGENTS.MD Content"
    + BS
    + "n{agents_content}"
    + BS
    + "n"
    + BS
    + "n"
    + DQ
)
lines.append(
    "            f" + DQ + "## Already Read Files (content shown)" + BS + "n" + DQ
)
lines.append(
    "            f"
    + DQ
    + "{read_files_summary if read_files_summary else "
    + SQ
    + "(none yet "
    + EM
    + " AGENTS.MD was read but is not listed here)"
    + SQ
    + "}"
    + BS
    + "n"
    + BS
    + "n"
    + DQ
)
lines.append(
    "            "
    + DQ
    + "Based on the task, AGENTS.MD instructions, and workspace structure, decide which files "
    + DQ
)
lines.append(
    "            "
    + DQ
    + "need to be read next. Be conservative "
    + EM
    + " only request files that are truly necessary. "
    + DQ
)
lines.append(
    "            "
    + DQ
    + "Always use paths exactly as they appear in the All Available File Paths list."
    + DQ
)
lines.append("        )")
lines.append("")
lines.append("        try:")
lines.append("            msg = [")
lines.append(
    "                {"
    + DQ
    + "role"
    + DQ
    + ": "
    + DQ
    + "system"
    + DQ
    + ", "
    + DQ
    + "content"
    + DQ
    + ": CONTEXT_EXTRACTOR_SYSTEM_PROMPT},"
)
lines.append(
    "                {"
    + DQ
    + "role"
    + DQ
    + ": "
    + DQ
    + "user"
    + DQ
    + ", "
    + DQ
    + "content"
    + DQ
    + ": user_msg},"
)
lines.append("            ]")
lines.append("            return self.provider.complete_as(msg, FileDecisionResponse)")
lines.append("        except Exception:")
lines.append("            return FileDecisionResponse(")
lines.append(
    "                done=True, reasoning="
    + DQ
    + "LLM decision failed, stopping file reads"
    + DQ
)
lines.append("            )")
lines.append("")

# _resolve_agents_path
lines.append(
    "    def _resolve_agents_path(self, vm: MiniRuntimeClientSync) -> Optional[str]:"
)
lines.append("        for p in AGENTS_CANDIDATES:")
lines.append("            content = self._read_path(vm, p)")
lines.append("            if isinstance(content, str):")
lines.append("                return p")
lines.append("        return None")
lines.append("")

# extract_task_graph
lines.append("    def extract_task_graph(")
lines.append("        self,")
lines.append("        harness_url: str,")
lines.append("        task_text: str,")
lines.append("        max_llm_round: int = 8,")
lines.append("        max_files: int = 50,")
lines.append("    ) -> Dict[str, object]:")
lines.append("        vm = MiniRuntimeClientSync(harness_url)")
lines.append("")
lines.append("        graph: Dict[str, object] = {")
lines.append("            " + DQ + "user_question" + DQ + ": task_text,")
lines.append(
    "            "
    + DQ
    + "directory_structure"
    + DQ
    + ": {"
    + DQ
    + "status"
    + DQ
    + ": "
    + DQ
    + BS
    + "u043d"
    + BS
    + "u0435 "
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
    + ", "
    + DQ
    + "data"
    + DQ
    + ": None},"
)
lines.append("            " + DQ + "agents_md" + DQ + ": {")
lines.append("                " + DQ + "path" + DQ + ": None,")
lines.append("                " + DQ + "full_path" + DQ + ": None,")
lines.append(
    "                "
    + DQ
    + "status"
    + DQ
    + ": "
    + DQ
    + BS
    + "u043d"
    + BS
    + "u0435 "
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
    + ","
)
lines.append("                " + DQ + "content" + DQ + ": " + DQ + DQ + ",")
lines.append("                " + DQ + "blocks" + DQ + ": [],")
lines.append("            },")
lines.append("            " + DQ + "files" + DQ + ": [],")
lines.append(
    "            " + DQ + "extract_status" + DQ + ": " + DQ + "pending" + DQ + ","
)
lines.append("        }")
lines.append("        context_docs: Dict[str, str] = {}")
lines.append("        required_policy_refs: List[str] = []")
lines.append("        policy_dirs: List[str] = []")
lines.append("        exact_literal_answer: Optional[str] = None")
lines.append("        reference_only_this_file = False")
lines.append("        requires_policy_ref = False")
lines.append("")
lines.append("        # Step 1: Get directory tree (direct call, no LLM)")
lines.append("        try:")
lines.append(
    "            outline = vm.outline(OutlineRequest(path=" + DQ + "/" + DQ + "))"
)
lines.append("            outline_dict = MessageToDict(outline)")
lines.append(
    "            graph["
    + DQ
    + "directory_structure"
    + DQ
    + "] = {"
    + DQ
    + "status"
    + DQ
    + ": "
    + DQ
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
    + ", "
    + DQ
    + "data"
    + DQ
    + ": outline_dict}"
)
lines.append("        except Exception:")
lines.append(
    "            graph["
    + DQ
    + "directory_structure"
    + DQ
    + "] = {"
    + DQ
    + "status"
    + DQ
    + ": "
    + DQ
    + BS
    + "u043d"
    + BS
    + "u0435 "
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
    + ", "
    + DQ
    + "data"
    + DQ
    + ": None}"
)
lines.append("")
lines.append("        tree_summary = _build_tree_summary(")
lines.append(
    "            graph["
    + DQ
    + "directory_structure"
    + DQ
    + "].get("
    + DQ
    + "data"
    + DQ
    + ", {})"
)
lines.append("        )")
lines.append(
    "        all_paths = _collect_all_paths(graph["
    + DQ
    + "directory_structure"
    + DQ
    + "].get("
    + DQ
    + "data"
    + DQ
    + ", {}))"
)
lines.append("")
lines.append("        # Step 2: Get AGENTS.MD (direct call, no LLM)")
lines.append("        agents_path = self._resolve_agents_path(vm)")
lines.append("")
lines.append("        if agents_path:")
lines.append(
    "            agents_content = self._read_path(vm, agents_path) or " + DQ + DQ
)
lines.append("            graph[" + DQ + "agents_md" + DQ + "] = {")
lines.append("                " + DQ + "path" + DQ + ": agents_path,")
lines.append(
    "                " + DQ + "full_path" + DQ + ": _to_abs_path(agents_path),"
)
lines.append(
    "                "
    + DQ
    + "status"
    + DQ
    + ": "
    + DQ
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
    + " if agents_content else "
    + DQ
    + BS
    + "u043d"
    + BS
    + "u0435 "
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
    + ","
)
lines.append("                " + DQ + "content" + DQ + ": agents_content,")
lines.append("                " + DQ + "blocks" + DQ + ": [],")
lines.append("            }")
lines.append("            if agents_content:")
lines.append("                context_docs[agents_path] = agents_content")
lines.append(
    "                exact_literal_answer = _extract_exact_literal_answer(agents_content)"
)
lines.append("                reference_only_this_file = (")
lines.append(
    "                    "
    + DQ
    + "reference only this file"
    + DQ
    + " in agents_content.lower()"
)
lines.append("                )")
lines.append(
    "                requires_policy_ref = "
    + DQ
    + "policy file"
    + DQ
    + " in agents_content.lower()"
)
lines.append("                policy_dirs = _extract_policy_dirs(agents_content)")
lines.append("")
lines.append("        # Step 3: LLM-driven file reading loop")
lines.append("        files_nodes_map: Dict[str, Dict[str, object]] = {}")
lines.append("        visited = set()")
lines.append("")
lines.append(
    "        # If AGENTS.MD says reference only this file, skip LLM loop entirely"
)
lines.append("        if not reference_only_this_file:")
lines.append("            for _round in range(max_llm_round):")
lines.append("                if len(files_nodes_map) >= max_files:")
lines.append("                    break")
lines.append("")
lines.append("                # Ask LLM which files to read next")
lines.append("                decision = self._decide_next_files(")
lines.append("                    task_text=task_text,")
lines.append("                    agents_content=agents_content or " + DQ + DQ + ",")
lines.append("                    tree_summary=tree_summary,")
lines.append("                    all_paths=all_paths,")
lines.append("                    already_read=dict(context_docs),")
lines.append("                )")
lines.append("")
lines.append("                if decision.done or not decision.files_to_read:")
lines.append("                    break")
lines.append("")
lines.append("                # Read the files the LLM decided on")
lines.append("                for item in decision.files_to_read:")
lines.append("                    if len(files_nodes_map) >= max_files:")
lines.append("                        break")
lines.append("")
lines.append("                    npath = _normalize_rel_path(item.path)")
lines.append("                    if not npath or npath.lower() in visited:")
lines.append("                        continue")
lines.append("")
lines.append("                    content = self._read_path(vm, npath)")
lines.append("                    node: Dict[str, object] = {")
lines.append("                        " + DQ + "path" + DQ + ": npath,")
lines.append(
    "                        " + DQ + "full_path" + DQ + ": _to_abs_path(npath),"
)
lines.append(
    "                        "
    + DQ
    + "status"
    + DQ
    + ": "
    + DQ
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
    + " if isinstance(content, str) else "
    + DQ
    + BS
    + "u043d"
    + BS
    + "u0435 "
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
    + ","
)
lines.append(
    "                        "
    + DQ
    + "content"
    + DQ
    + ": content if isinstance(content, str) else "
    + DQ
    + DQ
    + ","
)
lines.append("                        " + DQ + "blocked_by" + DQ + ": None,")
lines.append("                        " + DQ + "blocks" + DQ + ": [],")
lines.append("                        " + DQ + "reason_to_read" + DQ + ": item.reason,")
lines.append("                    }")
lines.append("")
lines.append("                    if isinstance(content, str):")
lines.append("                        visited.add(npath.lower())")
lines.append("                        context_docs[npath] = content")
lines.append(
    "                        if npath.lower().endswith(" + DQ + ".md" + DQ + "):"
)
lines.append("                            required_policy_refs.append(npath)")
lines.append("")
lines.append("                        rx_refs = _extract_links_regex(content)")
lines.append("                        node[" + DQ + "blocks" + DQ + "] = rx_refs")
lines.append("")
lines.append("                    files_nodes_map[npath] = node")
lines.append("")
lines.append("        files_nodes = list(files_nodes_map.values())")
lines.append("")
lines.append(
    "        # Fallback for policy directories mentioned in AGENTS: read first markdown in each."
)
lines.append("        if requires_policy_ref and not required_policy_refs:")
lines.append(
    "            structure = graph.get("
    + DQ
    + "directory_structure"
    + DQ
    + ", {}).get("
    + DQ
    + "data"
    + DQ
    + ", {})"
)
lines.append("            top_files = (")
lines.append(
    "                structure.get("
    + DQ
    + "files"
    + DQ
    + ", []) if isinstance(structure, dict) else []"
)
lines.append("            )")
lines.append(
    "            for entry in top_files if isinstance(top_files, list) else []:"
)
lines.append("                if isinstance(entry, dict):")
lines.append(
    "                    p = _normalize_rel_path(entry.get("
    + DQ
    + "path"
    + DQ
    + ", "
    + DQ
    + DQ
    + "))"
)
lines.append("                elif isinstance(entry, str):")
lines.append("                    p = _normalize_rel_path(entry)")
lines.append("                else:")
lines.append("                    continue")
lines.append(
    "                if p.lower().endswith("
    + DQ
    + ".md"
    + DQ
    + ") and p not in required_policy_refs:"
)
lines.append("                    required_policy_refs.append(p)")
lines.append("")
lines.append("        graph[" + DQ + "files" + DQ + "] = files_nodes")
lines.append("")
lines.append(
    "        agents_ok = graph.get("
    + DQ
    + "agents_md"
    + DQ
    + ", {}).get("
    + DQ
    + "status"
    + DQ
    + ") == "
    + DQ
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
)
lines.append(
    "        tree_ok = graph.get("
    + DQ
    + "directory_structure"
    + DQ
    + ", {}).get("
    + DQ
    + "status"
    + DQ
    + ") == "
    + DQ
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
)
lines.append(
    "        deps_ok = all(x.get("
    + DQ
    + "status"
    + DQ
    + ") == "
    + DQ
    + BS
    + "u043f"
    + BS
    + "u043e"
    + BS
    + "u043b"
    + BS
    + "u0443"
    + BS
    + "u0447"
    + BS
    + "u0435"
    + BS
    + "u043d"
    + DQ
    + " for x in files_nodes)"
)
lines.append("        graph[" + DQ + "extract_status" + DQ + "] = (")
lines.append(
    "            "
    + DQ
    + "complete"
    + DQ
    + " if (tree_ok and agents_ok and deps_ok) else "
    + DQ
    + "pending"
    + DQ
)
lines.append("        )")
lines.append("")
lines.append("        return {")
lines.append("            " + DQ + "graph" + DQ + ": graph,")
lines.append("            " + DQ + "context_docs" + DQ + ": context_docs,")
lines.append(
    "            " + DQ + "required_policy_refs" + DQ + ": required_policy_refs,"
)
lines.append("            " + DQ + "policy_dirs" + DQ + ": policy_dirs,")
lines.append(
    "            " + DQ + "exact_literal_answer" + DQ + ": exact_literal_answer,"
)
lines.append(
    "            "
    + DQ
    + "reference_only_this_file"
    + DQ
    + ": reference_only_this_file,"
)
lines.append(
    "            " + DQ + "requires_policy_ref" + DQ + ": requires_policy_ref,"
)
lines.append("        }")
lines.append("")

# extract
lines.append("    def extract(self, harness_url: str) -> ContextResult:")
lines.append(
    "        return self.extract_with_llm(harness_url=harness_url, task_text="
    + DQ
    + DQ
    + ")"
)
lines.append("")

# extract_with_llm
lines.append(
    "    def extract_with_llm(self, harness_url: str, task_text: str) -> ContextResult:"
)
lines.append(
    "        payload = self.extract_task_graph(harness_url=harness_url, task_text=task_text)"
)
lines.append("        graph = payload[" + DQ + "graph" + DQ + "]")
lines.append("")
lines.append(
    "        protected = ["
    + DQ
    + "AGENTS.MD"
    + DQ
    + ", "
    + DQ
    + "AGENTS.md"
    + DQ
    + ", "
    + DQ
    + ".git"
    + DQ
    + "]"
)
lines.append(
    "        if graph.get("
    + DQ
    + "agents_md"
    + DQ
    + ", {}).get("
    + DQ
    + "path"
    + DQ
    + "):"
)
lines.append(
    "            protected.append(str(graph["
    + DQ
    + "agents_md"
    + DQ
    + "]["
    + DQ
    + "path"
    + DQ
    + "]))"
)
lines.append("")
lines.append("        return ContextResult(")
lines.append("            user_profile={},")
lines.append("            project_rules={")
lines.append(
    "                "
    + DQ
    + "extract_status"
    + DQ
    + ": str(graph.get("
    + DQ
    + "extract_status"
    + DQ
    + ", "
    + DQ
    + "pending"
    + DQ
    + ")),"
)
lines.append("            },")
lines.append(
    "            workspace_structure=graph.get("
    + DQ
    + "directory_structure"
    + DQ
    + ", {}).get("
    + DQ
    + "data"
    + DQ
    + ") or {},"
)
lines.append(
    "            success=graph.get("
    + DQ
    + "extract_status"
    + DQ
    + ") == "
    + DQ
    + "complete"
    + DQ
    + ","
)
lines.append("            errors=[],")
lines.append("            protected_files=protected,")
lines.append("            extraction_graph=graph,")
lines.append(
    "            extract_status=str(graph.get("
    + DQ
    + "extract_status"
    + DQ
    + ", "
    + DQ
    + "pending"
    + DQ
    + ")),"
)
lines.append("            user_question=task_text,")
lines.append("        )")
lines.append("")

# to_task_context
lines.append(
    "    def to_task_context(self, context_result: ContextResult) -> TaskContext:"
)
lines.append("        protected = list(context_result.protected_files or [])")
lines.append("        if " + DQ + "AGENTS.MD" + DQ + " not in protected:")
lines.append("            protected.append(" + DQ + "AGENTS.MD" + DQ + ")")
lines.append("        if " + DQ + "AGENTS.md" + DQ + " not in protected:")
lines.append("            protected.append(" + DQ + "AGENTS.md" + DQ + ")")
lines.append("        if " + DQ + ".git" + DQ + " not in protected:")
lines.append("            protected.append(" + DQ + ".git" + DQ + ")")
lines.append("")
lines.append("        return TaskContext(")
lines.append("            user_profile=context_result.user_profile,")
lines.append("            project_rules=context_result.project_rules,")
lines.append("            workspace_root=context_result.workspace_root,")
lines.append("            protected_files=protected,")
lines.append("            extraction_graph=context_result.extraction_graph,")
lines.append("            user_question=context_result.user_question,")
lines.append("        )")
lines.append("")
lines.append("")

# create_context_extractor
lines.append("def create_context_extractor():")
lines.append("    return ContextExtractor()")
lines.append("")

content = NL.join(lines)

# Verify syntax
try:
    ast.parse(content)
    print("Syntax OK!")
except SyntaxError as e:
    print(f"Syntax error at line {e.lineno}: {e.msg}")
    print(f"Text: {e.text}")
    raise

# Write the file
with open(filepath, "w", encoding="utf-8", newline="") as f:
    f.write(content)

print(f"File written: {len(content)} bytes, {content.count(NL)} lines")
