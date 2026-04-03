import sys

sys.path = [p for p in sys.path if "BitGN" not in p]

# ============================================================
# 1. Update pac1-py/agents/context_extractor.py - add trace_logger
# ============================================================
filepath = r"C:/Users/user2/Documents/BitGN/pac1-py/agents/context_extractor.py"
with open(filepath, "rb") as f:
    raw = f.read()

# Add import for LLMTraceLogger
old = b"from google.protobuf.json_format import MessageToDict"
new = b"from google.protobuf.json_format import MessageToDict\nfrom llm_logger import LLMTraceLogger"
raw = raw.replace(old, new)

# Update __init__ to accept trace_logger
old = b"""    def __init__(self, provider=None):
        self.provider = provider"""
new = b"""    def __init__(self, provider=None, trace_logger: LLMTraceLogger = None):
        self.provider = provider
        self.trace_logger = trace_logger"""
raw = raw.replace(old, new)

# Add logging after tree extraction
old = b"""        # ===== TASK A: Full directory structure =====
        tree_dict = self._get_tree(vm, root="/", level=3)
        tree_formatted = self._format_tree(tree_dict)"""
new = b"""        # ===== TASK A: Full directory structure =====
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
                details={"tree_available": bool(tree_dict), "tree_lines": tree_formatted.count("\\n")},
            )"""
raw = raw.replace(old, new)

# Add logging after AGENTS.MD extraction
old = b'''        agents_path = self._resolve_agents_path(vm)
        agents_content = ""

        if agents_path:
            agents_content = self._read_path(vm, agents_path) or ""'''
new = b"""        agents_path = self._resolve_agents_path(vm)
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
                )"""
raw = raw.replace(old, new)

# Add logging before and after LLM link extraction from AGENTS.MD
old = b"""                # Extract references from AGENTS.md
                llm_refs = self._extract_links_llm(agents_content, agents_path)
                rx_refs = _extract_links_regex(agents_content)"""
new = b"""                # Extract references from AGENTS.md
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
                    )"""
raw = raw.replace(old, new)

# Add logging before and after LLM-driven file reading loop
old = b"""                # LLM-driven file reading loop
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
new = b"""                # LLM-driven file reading loop
                tree_summary = _build_tree_summary(tree_dict)
                all_paths = _collect_all_paths(tree_dict)
                visited = set()
                visited.add(agents_path.lower())

                if self.trace_logger:
                    self.trace_logger.log_agent_event(
                        agent_name="context_extractor",
                        event="llm_file_reading_started",
                        details={
                            "tree_summary_lines": tree_summary.count("\\n"),
                            "total_available_paths": len(all_paths),
                            "max_nodes": max_nodes,
                        },
                    )

                for _round in range(30):  # max LLM decision rounds
                    if len(graph_nodes) >= max_nodes:
                        break

                    if self.trace_logger:
                        self.trace_logger.log_agent_event(
                            agent_name="context_extractor",
                            event="llm_decision_round",
                            details={
                                "round": _round,
                                "files_read_so_far": len(graph_nodes),
                            },
                        )

                    decision = self._decide_next_files(
                        task_text=task_text,
                        agents_content=agents_content,
                        tree_summary=tree_summary,
                        all_paths=all_paths,
                        already_read=dict(context_docs),
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
                                )"""
raw = raw.replace(old, new)

# Add logging at end of extract_task_graph
old = b"""        return {
            "graph": graph,
            "context_docs": context_docs,
            "directory_structure": tree_dict,
            "directory_tree_formatted": tree_formatted,
            "instruction_dependency_graph": instruction_graph,
        }"""
new = b"""        if self.trace_logger:
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
        }"""
raw = raw.replace(old, new)

# Update create_context_extractor to accept trace_logger
old = b'''def create_context_extractor(provider=None):
    """Create a ContextExtractor instance."""
    return ContextExtractor(provider=provider)'''
new = b'''def create_context_extractor(provider=None, trace_logger: LLMTraceLogger = None):
    """Create a ContextExtractor instance."""
    return ContextExtractor(provider=provider, trace_logger=trace_logger)'''
raw = raw.replace(old, new)

with open(filepath, "wb") as f:
    f.write(raw)

print("Updated pac1-py/agents/context_extractor.py")

# ============================================================
# 2. Update pac1-py/agents/execution_agent.py - add trace_logger
# ============================================================
filepath = r"C:/Users/user2/Documents/BitGN/pac1-py/agents/execution_agent.py"
with open(filepath, "rb") as f:
    raw = f.read()

# Add import for LLMTraceLogger
old = b"from llm_provider import LLMProvider"
new = b"from llm_provider import LLMProvider\nfrom llm_logger import LLMTraceLogger"
raw = raw.replace(old, new)

# Update __init__ to accept trace_logger
old = b"""    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        system_prompt: str = None,
    ):
        self.provider = provider
        self.system_prompt = system_prompt or SYSTEM_PROMPT"""
new = b"""    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        system_prompt: str = None,
        trace_logger: LLMTraceLogger = None,
    ):
        self.provider = provider
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.trace_logger = trace_logger"""
raw = raw.replace(old, new)

# Add logging in execute() method
old = b"""        prompt = self.base_prompt.format(context_info=context_info, protected_files=protected)"""
new = b"""        prompt = self.base_prompt.format(context_info=context_info, protected_files=protected)

        if self.trace_logger:
            self.trace_logger.log_agent_event(
                agent_name="execution_agent",
                event="execute_started",
                details={
                    "task_text": task_text[:200],
                    "context_info_length": len(context_info),
                    "conversation_length": len(conversation_log),
                },
            )"""
raw = raw.replace(old, new)

# Add logging after LLM call
old = b"""        try:
            job = self.provider.complete(conversation_log)
            return job, job.task_completed
        except Exception as e:
            return self._create_error_response(str(e)), True"""
new = b"""        try:
            if self.trace_logger:
                self.trace_logger.log_exchange(
                    messages=conversation_log,
                    response="(calling LLM...)",
                    step_name="execution_agent_decision",
                )

            job = self.provider.complete(conversation_log)

            if self.trace_logger:
                self.trace_logger.log_exchange(
                    messages=conversation_log,
                    response=job.model_dump_json(indent=2),
                    step_name="execution_agent_decision",
                )
                self.trace_logger.log_agent_event(
                    agent_name="execution_agent",
                    event="decision_made",
                    details={
                        "tool_name": job.function.__class__.__name__,
                        "reasoning": job.reasoning[:500],
                        "task_completed": job.task_completed,
                        "phase": job.phase,
                    },
                )

            return job, job.task_completed
        except Exception as e:
            if self.trace_logger:
                self.trace_logger.log_agent_event(
                    agent_name="execution_agent",
                    event="execution_error",
                    details={"error": str(e)},
                )
            return self._create_error_response(str(e)), True"""
raw = raw.replace(old, new)

# Update create_execution_agent to accept trace_logger
old = b'''def create_execution_agent(
    provider: LLMProvider, system_prompt: str = None
) -> ExecutionAgent:
    """Create an ExecutionAgent instance."""
    return ExecutionAgent(provider=provider, system_prompt=system_prompt)'''
new = b'''def create_execution_agent(
    provider: LLMProvider, system_prompt: str = None, trace_logger: LLMTraceLogger = None
) -> ExecutionAgent:
    """Create an ExecutionAgent instance."""
    return ExecutionAgent(provider=provider, system_prompt=system_prompt, trace_logger=trace_logger)'''
raw = raw.replace(old, new)

with open(filepath, "wb") as f:
    f.write(raw)

print("Updated pac1-py/agents/execution_agent.py")

# ============================================================
# 3. Update pac1-py/orchestrator.py - pass trace_logger to agents
# ============================================================
filepath = r"C:/Users/user2/Documents/BitGN/pac1-py/orchestrator.py"
with open(filepath, "rb") as f:
    raw = f.read()

# Update agent initialization to pass trace_logger
old = b"""        # Initialize all agents
        self.security_gate = SecurityGate(provider=provider)
        self.context_extractor = ContextExtractor(provider=provider)
        self.execution_agent = ExecutionAgent(
            provider=provider, system_prompt=system_prompt
        )"""
new = b"""        # Initialize all agents
        self.security_gate = SecurityGate(provider=provider)
        self.context_extractor = ContextExtractor(provider=provider, trace_logger=trace_logger)
        self.execution_agent = ExecutionAgent(
            provider=provider, system_prompt=system_prompt, trace_logger=trace_logger
        )"""
raw = raw.replace(old, new)

with open(filepath, "wb") as f:
    f.write(raw)

print("Updated pac1-py/orchestrator.py")

# Verify syntax
import ast

for fp in [
    r"C:/Users/user2/Documents/BitGN/pac1-py/agents/context_extractor.py",
    r"C:/Users/user2/Documents/BitGN/pac1-py/agents/execution_agent.py",
    r"C:/Users/user2/Documents/BitGN/pac1-py/orchestrator.py",
]:
    try:
        with open(fp, "r", encoding="utf-8") as f:
            ast.parse(f.read())
        print(f"Syntax OK: {fp}")
    except SyntaxError as e:
        print(f"Error in {fp} at line {e.lineno}: {e.msg}")
