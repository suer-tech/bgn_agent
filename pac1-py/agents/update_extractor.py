import sys

sys.path = [p for p in sys.path if "BitGN" not in p]

filepath = r"C:/Users/user2/Documents/BitGN/pac1-py/agents/context_extractor.py"
with open(filepath, "rb") as f:
    raw = f.read()

# 1. Add new Pydantic models and system prompt after LinkExtractionResponse
old = b"""class LinkExtractionResponse(BaseModel):
    referenced_files: List[str] = Field(default_factory=list)"""

new = b"""class LinkExtractionResponse(BaseModel):
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
    "need to be read to fully understand the context for executing the user's task.\\n\\n"
    "Rules:\\n"
    "1. AGENTS.MD is the main source of truth \\u2014 always analyze it first to understand policies, "
    "   workflows, and which files or directories are relevant.\\n"
    "2. Only request files that are directly relevant to the user's task.\\n"
    "3. Do NOT request files that are templates (files starting with _ like _template.md), "
    "   archives, or historical records unless the task specifically requires them.\\n"
    "4. If AGENTS.MD says \\"reference only this file\\", no additional files need to be read.\\n"
    "5. If AGENTS.MD points to specific policy files or directories, prioritize those.\\n"
    "6. Be conservative \\u2014 request the minimum number of files needed to understand the task.\\n"
    "7. Set done=true when you have enough context to proceed with task execution.\\n"
    "8. Always use paths exactly as they appear in the directory tree. Do not invent paths.\\n\\n"
    "Return your decision as a structured response with files_to_read, reasoning, and done flag."
)"""

raw = raw.replace(old, new)

# 2. Add helper functions after _extract_links_regex
old = b'''def _format_tree_entry(entry, prefix: str = "", is_last: bool = True) -> list[str]:
    """Format a tree entry for display."""'''

new = b'''def _build_tree_summary(tree_data: Dict[str, Any]) -> str:
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
    return "\\n".join(lines)


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
    """Format a tree entry for display."""'''

raw = raw.replace(old, new)

# 3. Add _decide_next_files method after _extract_links_llm
old = b"""            parsed = self.provider.complete_as(msg, LinkExtractionResponse)
            refs = [_normalize_rel_path(x) for x in parsed.referenced_files]
            return [r for r in refs if r.lower().endswith(".md")]
        except Exception:
            return []

    def extract_task_graph("""

new = b'''            parsed = self.provider.complete_as(msg, LinkExtractionResponse)
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
    ) -> FileDecisionResponse:
        """Use LLM to decide which files to read next based on task, AGENTS.MD, and current context."""
        if not self.provider:
            return FileDecisionResponse(done=True, reasoning="No LLM provider available")

        read_files_summary = ""
        if already_read:
            parts = []
            for p, c in already_read.items():
                preview = c[:400].replace("\\n", " ")
                parts.append(f"### {p}\\n{preview}...")
            read_files_summary = "\\n\\n".join(parts)

        available_paths = "\\n".join(f"  - {p}" for p in all_paths)

        user_msg = (
            f"Task: {task_text}\\n\\n"
            f"## Directory Tree\\n{tree_summary}\\n\\n"
            f"## All Available File Paths\\n{available_paths}\\n\\n"
            f"## AGENTS.MD Content\\n{agents_content}\\n\\n"
            f"## Already Read Files (content shown)\\n"
            f"{read_files_summary if read_files_summary else '(none yet \\u2014 AGENTS.MD was read but is not listed here)'}\\n\\n"
            "Based on the task, AGENTS.MD instructions, and workspace structure, decide which files "
            "need to be read next. Be conservative \\u2014 only request files that are truly necessary. "
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

    def extract_task_graph('''

raw = raw.replace(old, new)

# 4. Replace the BFS loop in extract_task_graph with LLM-driven loop
old = b"""                # Process referenced files recursively
                queue = [(r, agents_path, 1) for r in refs]
                visited = set()
                visited.add(agents_path.lower())

                for _round in range(10):  # max retry rounds
                    round_queue = list(queue)
                    queue.clear()

                    while round_queue and len(graph_nodes) < max_nodes:
                        path, blocked_by, depth = round_queue.pop(0)
                        npath = _normalize_rel_path(path)
                        if not npath or npath.lower() in visited or depth > max_depth:
                            continue

                        content = self._read_path(vm, npath)
                        if isinstance(content, str):
                            visited.add(npath.lower())
                            context_docs[npath] = content
                            hierarchy.append(npath)

                            # Extract references from this file
                            file_llm_refs = self._extract_links_llm(content, npath)
                            file_rx_refs = _extract_links_regex(content)
                            file_refs = []
                            file_seen = set()
                            for ref in file_llm_refs + file_rx_refs:
                                resolved = _join_paths(npath, ref)
                                if resolved and resolved.lower() not in file_seen:
                                    file_seen.add(resolved.lower())
                                    file_refs.append(resolved)

                            # Create node
                            graph_nodes[npath] = DependencyNode(
                                path=npath,
                                content=content,
                                status="loaded",
                                children=file_refs,
                                parent=blocked_by,
                            )

                            # Add children to queue
                            for ref in file_refs:
                                queue.append((ref, npath, depth + 1))
                        else:
                            # File not found, retry later
                            queue.append((npath, blocked_by, depth))

                    # Check if all fetched
                    if all(n.status == "loaded" for n in graph_nodes.values()):
                        break"""

new = b"""                # LLM-driven file reading loop
                tree_summary = _build_tree_summary(tree_dict)
                all_paths = _collect_all_paths(tree_dict)
                visited = set()
                visited.add(agents_path.lower())

                for _round in range(30):  # max LLM decision rounds
                    if len(graph_nodes) >= max_nodes:
                        break

                    decision = self._decide_next_files(
                        task_text=task_text,
                        agents_content=agents_content,
                        tree_summary=tree_summary,
                        all_paths=all_paths,
                        already_read=dict(context_docs),
                    )

                    if decision.done or not decision.files_to_read:
                        break

                    for item in decision.files_to_read:
                        if len(graph_nodes) >= max_nodes:
                            break

                        npath = _normalize_rel_path(item.path)
                        if not npath or npath.lower() in visited:
                            continue

                        content = self._read_path(vm, npath)
                        if isinstance(content, str):
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
                            )"""

raw = raw.replace(old, new)

with open(filepath, "wb") as f:
    f.write(raw)

print("Updated pac1-py/context_extractor.py")

# Verify syntax
try:
    import ast

    ast.parse(raw.decode("utf-8"))
    print("Syntax OK!")
except SyntaxError as e:
    print(f"Error at line {e.lineno}: {e.msg}")
    lines = raw.decode("utf-8").split("\\n")
    for i in range(max(0, e.lineno - 3), min(len(lines), e.lineno + 3)):
        marker = ">>>" if i == e.lineno - 1 else "   "
        print(f"{marker} Line {i + 1}: {repr(lines[i])}")
