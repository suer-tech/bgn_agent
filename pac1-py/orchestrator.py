"""Orchestrator — State Machine pipeline for PAC1.

Flow:
1. Initialize AgentState
2. Triage (1 LLM call) → early exit if ATTACK/UNSUPPORTED
3. Bootstrap (1 LLM call) → load workspace rules
4. Task Extraction (1 LLM call) → structured task model
5. Strategic Analysis (1 LLM call) → entity graph, checklist, risks, scope
6. Execution Loop (max 30 steps):
   a. build_planner_prompt() + plan_next_step()
   b. Update Scratchpad + entity graph
   c. If report_completion → check entities + checklist → break or feedback
   d. execute_tool() → add to conversation_history
7. Pre-Completion Review (1 LLM call) → verify before submitting
8. Send AnswerRequest to PCM (ONLY here!)
9. Log everything
"""

import json
import time
from typing import Any, Dict, Optional

from bitgn.vm.pcm_connect import PcmRuntimeClientSync

from agents.types import (
    AgentState,
    ScratchpadState,
    ReportTaskCompletion,
    AuthorityMap,
    get_outcome_map,
)
from agents.triage_node import run_triage
from agents.bootstrap_node import run_bootstrap
from agents.task_node import run_task_extraction
from agents.strategic_analysis_node import run_strategic_analysis
from agents.context_gatherer import gather_entity_context, format_gathered_context
from agents.security_node import run_post_context_security
from agents.validator_node import run_post_mutation_validation
from agents.subagent_node import run_subagent_session
from agents.execution_agent import build_planner_prompt, plan_next_step
from agents.tool_executor import execute_tool
from agents.pcm_helpers import send_answer
from llm_logger import LLMTraceLogger


CLI_RED = "\x1b[31m"
CLI_GREEN = "\x1b[32m"
CLI_CLR = "\x1b[0m"
CLI_YELLOW = "\x1b[33m"
CLI_BLUE = "\x1b[34m"
CLI_CYAN = "\x1b[36m"

# ── Context optimization constants ──
HISTORY_WINDOW_SIZE = 5
TOOL_RESULT_MAX_CHARS = 2000


def _compress_tool_result(tool_name: str, result_text: str) -> str:
    """Compress a tool result for storage in conversation history."""
    if len(result_text) <= TOOL_RESULT_MAX_CHARS:
        return result_text
    if tool_name in ("read", "cat"):
        lines = result_text.split("\n")
        if len(lines) > 20:
            head = "\n".join(lines[:12])
            tail = "\n".join(lines[-5:])
            return f"{head}\n\n[... {len(lines) - 17} lines omitted, {len(result_text)} chars total ...]\n\n{tail}"
        return result_text[:TOOL_RESULT_MAX_CHARS] + f"\n[... truncated, {len(result_text)} chars total]"
    if tool_name in ("tree", "list", "ls"):
        lines = result_text.split("\n")
        if len(lines) > 30:
            return "\n".join(lines[:25]) + f"\n[... {len(lines) - 25} more entries]"
    if tool_name == "search":
        lines = result_text.split("\n")
        if len(lines) > 20:
            return "\n".join(lines[:18]) + f"\n[... {len(lines) - 18} more matches]"
    return result_text[:TOOL_RESULT_MAX_CHARS] + f"\n[... truncated, {len(result_text)} chars total]"


def _apply_sliding_window(conversation_history: list) -> list:
    """Keep last HISTORY_WINDOW_SIZE tool-call pairs, collapse older into summary."""
    pair_count = len(conversation_history) // 2
    if pair_count <= HISTORY_WINDOW_SIZE:
        return conversation_history

    cut_point = (pair_count - HISTORY_WINDOW_SIZE) * 2
    old_messages = conversation_history[:cut_point]
    recent_messages = conversation_history[cut_point:]

    summary_parts = []
    for i in range(0, len(old_messages), 2):
        assistant_msg = old_messages[i]
        tool_msg = old_messages[i + 1] if i + 1 < len(old_messages) else None
        tool_name = "?"
        tool_args_brief = ""
        tool_calls = assistant_msg.get("tool_calls", [])
        if tool_calls:
            func = tool_calls[0].get("function", {})
            tool_name = func.get("name", "?")
            try:
                args = json.loads(func.get("arguments", "{}"))
                for key in ("path", "pattern", "name", "content"):
                    if key in args:
                        tool_args_brief = f" {key}={str(args[key])[:60]}"
                        break
            except (json.JSONDecodeError, TypeError):
                pass
        result_brief = ""
        if tool_msg:
            for line in tool_msg.get("content", "").split("\n"):
                line = line.strip()
                if line and not line.startswith("="):
                    result_brief = f" -> {line[:80]}"
                    break
        summary_parts.append(f"  step {i // 2 + 1}: {tool_name}{tool_args_brief}{result_brief}")

    summary_text = (
        f"[HISTORY SUMMARY — steps 1-{pair_count - HISTORY_WINDOW_SIZE} compressed]\n"
        + "\n".join(summary_parts)
    )
    return [{"role": "user", "content": summary_text}, *recent_messages]


class Orchestrator:
    """State Machine orchestrator for PAC1 multi-agent pipeline.

    Coordinates: Triage → Bootstrap → Execution Loop → Answer.
    Only the orchestrator sends AnswerRequest to PCM.
    """

    def __init__(
        self,
        provider=None,
        trace_logger: Optional[LLMTraceLogger] = None,
    ):
        self.provider = provider
        self.trace_logger = trace_logger or LLMTraceLogger()

    def run(
        self,
        harness_url: str,
        task_text: str,
        task_id: str,
        max_iterations: int = 30,
    ) -> Dict[str, Any]:
        """Run the full State Machine pipeline.

        Returns:
            Dictionary with task results.
        """
        start_time = time.time()

        print(f"\n{CLI_BLUE}{'=' * 60}")
        print(f"ORCHESTRATOR STARTING - Task: {task_id}", flush=True)
        print(f"{'=' * 60}{CLI_CLR}\n", flush=True)

        # Set up logger
        self.trace_logger.set_task(task_id, task_text)

        # Initialize VM client
        vm = PcmRuntimeClientSync(harness_url)

        # =====================================================================
        # Step 1: Initialize AgentState
        # =====================================================================
        state: AgentState = {
            "task_text": task_text,
            "triage_result": None,
            "task_model": None,
            "workspace_rules": {},
            "authority_map": AuthorityMap(),
            "strategic_analysis": None,
            "scratchpad": ScratchpadState(),
            "entity_context": "",
            "conversation_history": [],
            "is_completed": False,
            "final_outcome": "",
        }

        # =====================================================================
        # Step 1b: Get sandbox current date
        # =====================================================================
        sandbox_date = ""
        try:
            from bitgn.vm.pcm_pb2 import ContextRequest
            from google.protobuf.json_format import MessageToDict
            ctx_result = vm.context(ContextRequest())
            ctx_dict = MessageToDict(ctx_result)
            time_str = ctx_dict.get("time", "")
            if time_str:
                sandbox_date = time_str[:10]  # Extract YYYY-MM-DD
                state["task_text"] = f"[Current date: {sandbox_date}]\n{state['task_text']}"
                print(f"{CLI_GREEN}Sandbox date: {sandbox_date}{CLI_CLR}")
        except Exception as e:
            print(f"{CLI_YELLOW}Could not get sandbox date: {e}{CLI_CLR}")

        # =====================================================================
        # Step 1b: Quick tree for triage context (0 LLM calls)
        # =====================================================================
        workspace_tree = ""
        try:
            from bitgn.vm.pcm_pb2 import TreeRequest
            from agents.pcm_helpers import format_tree
            tree_result = vm.tree(TreeRequest(root="/", level=2))
            workspace_tree = format_tree({"root": "/", "level": 2}, tree_result)
        except Exception:
            pass

        # =====================================================================
        # Step 2: Triage (1 LLM call) — with workspace tree for capability awareness
        # =====================================================================
        print(f"{CLI_YELLOW}[1/5] Triage — classifying request...{CLI_CLR}", flush=True)
        state = run_triage(state, self.provider, self.trace_logger, workspace_tree=workspace_tree)

        if state["is_completed"]:
            outcome = state["final_outcome"]
            reason = (
                state["triage_result"].reason if state["triage_result"] else "Unknown"
            )
            print(f"{CLI_RED}TRIAGE BLOCKED: {outcome} — {reason}{CLI_CLR}")

            try:
                send_answer(vm, f"Request blocked by triage: {reason}", outcome)
            except Exception as e:
                print(f"Failed to submit triage block to VM: {e}")

            return self._build_result(state, task_id, start_time, 0)

        triage_info = state["triage_result"]
        print(
            f"{CLI_GREEN}Triage passed: {triage_info.intent.value} — {triage_info.reason}{CLI_CLR}"
        )

        # =====================================================================
        # Step 3: Bootstrap (1 LLM call for context advisor)
        # =====================================================================
        print(f"{CLI_YELLOW}[2/5] Bootstrap — loading workspace rules...{CLI_CLR}")
        state = run_bootstrap(state, vm, self.trace_logger, llm_provider=self.provider)

        rules_count = len(state["workspace_rules"])
        print(f"{CLI_GREEN}Loaded {rules_count} rule files{CLI_CLR}")
        for path in state["workspace_rules"]:
            print(f"  [Rule] {path}")

        # =====================================================================
        # Step 4: Task Extraction (1 LLM call)
        # =====================================================================
        print(f"{CLI_YELLOW}[3/5] Task Model — extracting structure...{CLI_CLR}")
        state = run_task_extraction(state, self.provider, self.trace_logger)

        model = state["task_model"]
        print(
            f"{CLI_GREEN}Task Model Ready: {model.domain.value} - {model.requested_effect}{CLI_CLR}"
        )
        print(
            f"  Objective: {model.task_objective}\n"
            f"  Requires file changes: {model.requires_file_changes}"
        )

        # =====================================================================
        # Step 5: Decision Gate (Ambiguity & Security)
        # =====================================================================
        if model.ambiguity_high and model.intent in ("MUTATION", "SECURITY_DENIAL"):
            print(
                f"{CLI_RED}DECISION GATE: STOP — High Ambiguity for Mutation{CLI_CLR}"
            )
            state["final_outcome"] = "OUTCOME_NONE_CLARIFICATION"
            state["is_completed"] = True
            send_answer(
                vm,
                f"Request is too ambiguous for action: {model.requested_effect}",
                state["final_outcome"],
            )
            return self._build_result(state, task_id, start_time, 0)

        if model.security_risk_high and model.intent == "SECURITY_DENIAL":
            print(f"{CLI_RED}DECISION GATE: STOP — High Security Risk Denial{CLI_CLR}")
            state["final_outcome"] = "OUTCOME_DENIED_SECURITY"
            state["is_completed"] = True
            send_answer(
                vm,
                f"Request denied for security reasons: {model.requested_effect}",
                state["final_outcome"],
            )
            return self._build_result(state, task_id, start_time, 0)

        # =====================================================================
        # Step 5b: Strategic Analysis (1 LLM call)
        # =====================================================================
        print(f"{CLI_YELLOW}[4a/6] Strategic Analysis — thinking before acting...{CLI_CLR}")
        state = run_strategic_analysis(state, self.provider, self.trace_logger)

        sa = state["strategic_analysis"]
        if sa:
            print(f"{CLI_GREEN}Strategic Analysis:{CLI_CLR}")
            print(f"  Entities: {len(sa.predicted_entities)} predicted")
            print(f"  Checklist: {len(sa.verification_checklist)} items")
            print(f"  Risks: {len(sa.risks)} identified")
            print(f"  Scope: create={sa.scope_boundary.files_may_create}, must_not_touch={sa.scope_boundary.files_must_not_touch}")
            print(f"  Approach: {sa.execution_approach[:150]}")

            # Check for irreconcilable contradictions in risks/checklist
            contradiction_risks = [
                r for r in sa.risks
                if "contradict" in r.description.lower() or "irreconcilable" in r.description.lower()
            ]
            contradiction_checks = [
                v for v in sa.verification_checklist
                if "contradict" in v.check.lower() and v.status == "failed"
            ]
            if contradiction_risks or contradiction_checks:
                reason = contradiction_risks[0].description if contradiction_risks else contradiction_checks[0].check
                print(f"{CLI_RED}STRATEGIC BLOCK: Contradiction detected — {reason}{CLI_CLR}")
                state["final_outcome"] = "OUTCOME_NONE_CLARIFICATION"
                state["is_completed"] = True
                send_answer(vm, f"Cannot proceed: {reason}", state["final_outcome"])
                return self._build_result(state, task_id, start_time, 0)

            # Initialize scratchpad entity_graph from predicted entities
            state["scratchpad"].entity_graph = list(sa.predicted_entities)

        # =====================================================================
        # Step 5c: Entity Context Gathering (deterministic, no LLM)
        # =====================================================================
        if model.target_entities:
            print(f"{CLI_YELLOW}[4a/4] Gathering entity context...{CLI_CLR}")
            try:
                contexts = gather_entity_context(vm, model.target_entities)
                state["entity_context"] = format_gathered_context(contexts)
                file_count = sum(len(c.related_files) for c in contexts.values())
                print(f"{CLI_GREEN}Gathered context: {len(contexts)} entities, {file_count} related files{CLI_CLR}")
                # Debug: show all date mentions with context
                for ename, ectx in contexts.items():
                    for dm in ectx.date_mentions:
                        print(f"  [Date] {dm.file_path} | {dm.label} | {dm.value}")
            except Exception as e:
                print(f"{CLI_YELLOW}Context gathering failed (non-fatal): {e}{CLI_CLR}")
                state["entity_context"] = ""

        # =====================================================================
        # Step 6: Execution Loop
        # =====================================================================
        print(
            f"{CLI_YELLOW}[4/4] Execution loop (max {max_iterations} steps)...{CLI_CLR}"
        )

        tool_calls_log = []
        iteration = 0
        final_answer = ""
        grounding_refs = []
        completed_steps = []
        sequential_read_dirs = {}  # dir -> count of sequential reads
        read_source_files = set()  # files agent has read (for delete protection)
        inbox_messages_read = set()  # distinct inbox msg files read (for one-at-a-time)

        # Pre-compute: does task text explicitly request deletion?
        task_lower = state["task_text"].lower()
        task_allows_delete = any(w in task_lower for w in ("delete", "remove", "discard", "clean up", "clean-up"))

        for iteration in range(max_iterations):
            step_name = f"step_{iteration + 1}"
            print(f"\n{CLI_YELLOW}--- {step_name} ---{CLI_CLR}")

            # 4a. Plan next step (with sliding window on history)
            prompt = build_planner_prompt(state)
            windowed_history = _apply_sliding_window(state["conversation_history"])

            try:
                next_step = plan_next_step(
                    prompt=prompt,
                    conversation_history=windowed_history,
                    llm_provider=self.provider,
                    trace_logger=self.trace_logger,
                    step_name=step_name,
                )
            except Exception as e:
                print(f"{CLI_RED}LLM error: {e}{CLI_CLR}")
                state["final_outcome"] = "OUTCOME_ERR_INTERNAL"
                state["is_completed"] = True
                final_answer = f"LLM error: {e}"
                break

            # 4b. Update Scratchpad from LLM response
            state["scratchpad"] = next_step.scratchpad_update

            print(f"  📝 Goal: {next_step.scratchpad_update.current_goal[:100]}")
            print(f"  📋 Plan: {next_step.plan_remaining_steps_brief[0]}")
            cit = next_step.decision_justification
            if cit:
                print(f"  📖 [{cit.source_type}] {cit.source_file} — {cit.rule_quote[:120]}")

            # 4c. Delegate to Subagent (check BEFORE completion — LLM may return both)
            if next_step.subagent_delegation:
                task = next_step.subagent_delegation
                print(
                    f"{CLI_CYAN}  -> Delegating to SUBAGENT: {task.subagent_id}{CLI_CLR}"
                )
                print(f"{CLI_CYAN}     Instruction: {task.instruction}{CLI_CLR}")

                sub_result = run_subagent_session(
                    domain=task.subagent_id,
                    task=task,
                    state=state,
                    llm_provider=self.provider,
                    vm_client=vm,
                    trace_logger=self.trace_logger,
                )

                # Feedback sub-result to Planner in the next iteration
                status_str = "SUCCESS" if sub_result.success else "FAILED"
                result_text = f"[SUBAGENT {task.subagent_id} RESULT - {status_str}]: {sub_result.message}"
                if sub_result.grounding_refs:
                    result_text += f"\nRefs: {', '.join(sub_result.grounding_refs)}"

                print(f"{CLI_CYAN}  <- Subagent returned: {status_str}{CLI_CLR}")

                # Skip normal tool execution since subagent handled it
                tool_name = f"subagent_{task.subagent_id}"
                tool_args = task.model_dump()
            elif isinstance(next_step.function, ReportTaskCompletion):
                # --- Check for unresolved entities before accepting completion ---
                entity_graph = next_step.scratchpad_update.entity_graph
                unresolved = [
                    e for e in entity_graph
                    if e.status == "unresolved"
                ]
                if unresolved and next_step.function.outcome == "OUTCOME_OK":
                    unresolved_names = ", ".join(
                        f"{e.entity_type}:{e.identifier}" for e in unresolved
                    )
                    print(f"{CLI_YELLOW}  [Entity Check] Unresolved entities: {unresolved_names}{CLI_CLR}")
                    # Feed back to LLM instead of completing
                    result_text = (
                        f"[SYSTEM FEEDBACK]: You have unresolved entities in your entity_graph: {unresolved_names}. "
                        f"Each entity must be resolved to its authoritative file before reporting completion. "
                        f"Read the missing records and update entity_graph, then try report_completion again."
                    )
                    tool_name = "report_completion"
                    tool_args = next_step.function.model_dump()
                    state["scratchpad"] = next_step.scratchpad_update
                    state["conversation_history"].append(
                        {"role": "assistant", "content": next_step.current_state,
                         "tool_calls": [{"type": "function", "id": step_name,
                                         "function": {"name": "report_completion",
                                                      "arguments": next_step.function.model_dump_json()}}]}
                    )
                    state["conversation_history"].append(
                        {"role": "tool", "content": result_text, "tool_call_id": step_name}
                    )
                    continue

                # --- Build grounding_refs from entity_graph + LLM refs ---
                entity_refs = [
                    e.resolved_file for e in entity_graph
                    if e.resolved_file and e.status == "resolved"
                ]
                llm_refs = next_step.function.grounding_refs or []
                # Merge: entity graph refs + LLM refs, deduplicated, preserving order
                seen = set()
                grounding_refs = []
                for ref in entity_refs + llm_refs:
                    normalized = ref.lstrip("/")
                    if normalized not in seen:
                        seen.add(normalized)
                        grounding_refs.append(normalized)

                final_answer = next_step.function.message
                completed_steps = next_step.function.completed_steps_laconic
                state["final_outcome"] = next_step.function.outcome
                state["is_completed"] = True

                status = (
                    CLI_GREEN
                    if next_step.function.outcome == "OUTCOME_OK"
                    else CLI_YELLOW
                )
                print(f"{status}TASK COMPLETED: {next_step.function.outcome}{CLI_CLR}")
                print(f"Summary: {final_answer}")
                if entity_graph:
                    print(f"  Entity graph: {len(entity_graph)} entities ({len(entity_refs)} resolved)")
                if grounding_refs:
                    print(f"References: {', '.join(grounding_refs)}")
                break
            else:
                # 4d. Execute tool
                tool_name = next_step.function.tool
                tool_args = next_step.function.model_dump()
                # Remove 'tool' key from args since it's the tool name
                tool_args.pop("tool", None)

                tool_call = {"name": tool_name, "arguments": tool_args}

                # ----- Mutation plan check -----
                if tool_name in ("write", "delete", "move", "mkdir"):
                    mp = next_step.mutation_plan
                    if mp:
                        print(f"  📋 Mutation: {mp.action} {mp.target_file}")
                        print(f"     Why: {mp.why_this_file[:120]}")
                        if mp.similar_files_not_touched:
                            print(f"     Not touching: {', '.join(mp.similar_files_not_touched)[:150]}")
                    else:
                        print(f"{CLI_YELLOW}  [Guardrail] Mutation without mutation_plan!{CLI_CLR}")

                print(
                    f"  (Tool) {tool_name}: {json.dumps(tool_args, ensure_ascii=False)[:200]}"
                )

                result_text = execute_tool(
                    tool_call=tool_call,
                    vm_client=vm,
                    trace_logger=self.trace_logger,
                    step_name=step_name,
                )

            print(f"{CLI_GREEN}OUT{CLI_CLR}: {result_text[:200]}...")

            # ----- Step 4e: Post-context Security Guard -----
            # Heuristic flags suspicious content → LLM verifies → result
            # passed to execution agent as context (no hard block).
            if tool_name in ("read", "cat") and len(result_text) > 50:
                read_path = tool_args.get("path", "")
                security_check = run_post_context_security(
                    result_text, self.provider, self.trace_logger,
                    file_path=read_path,
                    workspace_rules=state["workspace_rules"],
                )
                if not security_check.allowed:
                    injection_type = security_check.injection_type or "unknown"
                    print(
                        f"{CLI_YELLOW}  [Security] LLM confirmed threat in {read_path}: "
                        f"{injection_type} — {security_check.reason[:120]}{CLI_CLR}"
                    )
                    result_text += (
                        f"\n\n[SECURITY ANALYSIS — {injection_type.upper()}]: "
                        f"{security_check.reason}"
                    )
                elif security_check.reason and "heuristic" not in (security_check.reason or "").lower():
                    # LLM was called but cleared the content — pass that context too
                    print(f"{CLI_GREEN}  [Security] LLM cleared {read_path}: {security_check.reason[:100]}{CLI_CLR}")
                    result_text += (
                        f"\n\n[SECURITY ANALYSIS]: {security_check.reason}"
                    )

            # ----- Step 4e2: Track reads + sequential read guardrail -----
            if tool_name in ("read", "cat"):
                read_path = tool_args.get("path", "").strip("/")
                # Track source files for delete protection (#1)
                read_source_files.add(read_path)
                # Track inbox messages for one-at-a-time (#2)
                if ("inbox" in read_path.lower() and
                        read_path.split("/")[-1].startswith("msg_")):
                    inbox_messages_read.add(read_path)
                    if len(inbox_messages_read) > 1:
                        result_text += (
                            "\n\n[SYSTEM FEEDBACK]: You have read "
                            f"{len(inbox_messages_read)} distinct inbox messages. "
                            "Workspace rules say 'handle one item at a time'. "
                            "Stop processing and report_completion for the first message."
                        )
                        print(f"{CLI_YELLOW}  [Guardrail] Multiple inbox messages read: {inbox_messages_read}{CLI_CLR}")
                # Sequential read guardrail
                read_dir = "/".join(read_path.split("/")[:-1])
                if read_dir:
                    sequential_read_dirs[read_dir] = sequential_read_dirs.get(read_dir, 0) + 1
                    if sequential_read_dirs[read_dir] >= 4:
                        result_text += (
                            "\n\n[SYSTEM FEEDBACK]: You have read 4+ files from '"
                            + read_dir + "'. Use `search` instead of reading one by one."
                        )
                        print(f"{CLI_YELLOW}  [Guardrail] 4+ reads from {read_dir}{CLI_CLR}")
            else:
                sequential_read_dirs.clear()

            # ----- Step 4e3: Delete protection — MINIMAL DIFF (#1) -----
            if tool_name == "delete":
                delete_path = tool_args.get("path", "").strip("/")
                if delete_path in read_source_files and not task_allows_delete:
                    result_text = (
                        f"[SYSTEM BLOCK]: Cannot delete '{delete_path}' — "
                        "this file was read as input data, and the task does NOT "
                        "explicitly request deletion (no 'delete'/'remove'/'discard' in task text). "
                        "MINIMAL DIFF rule: source files must not be deleted after processing."
                    )
                    print(f"{CLI_RED}  [Guardrail] DELETE BLOCKED: {delete_path} (source file, task has no delete keyword){CLI_CLR}")

            # ----- Step 4e4: Scope boundary alert (#3) -----
            if tool_name in ("write", "delete", "move") and sa:
                target = tool_args.get("path", "").strip("/")
                must_not = sa.scope_boundary.files_must_not_touch
                scope_violation = False
                for pattern in must_not:
                    pattern_clean = pattern.strip("/")
                    if pattern_clean.endswith("*"):
                        if target.startswith(pattern_clean.rstrip("*")):
                            scope_violation = True
                            break
                    elif target == pattern_clean or target.endswith("/" + pattern_clean):
                        scope_violation = True
                        break
                if scope_violation:
                    result_text += (
                        f"\n\n[SCOPE ALERT]: You are modifying '{target}' which is in the "
                        f"MUST_NOT_TOUCH list from strategic analysis: {must_not}. "
                        "Are you SURE this modification is required by the task? "
                        "If not, undo this action and proceed without it."
                    )
                    print(f"{CLI_YELLOW}  [Guardrail] SCOPE ALERT: {target} in must_not_touch{CLI_CLR}")

            # ----- Step 4e5: RuleCitation authority check (#4) -----
            if tool_name in ("write", "delete", "move", "mkdir"):
                cit = next_step.decision_justification
                if cit and cit.source_type == "DATA_HINT":
                    result_text += (
                        "\n\n[AUTHORITY ALERT]: Your decision_justification cites a DATA_HINT "
                        f"('{cit.source_file}') for a mutation. DATA_HINT has the LOWEST authority. "
                        "Check if a README_INVARIANT or PROCESS_DOC contradicts this. "
                        "If a higher-authority rule exists, follow it instead."
                    )
                    print(f"{CLI_YELLOW}  [Guardrail] DATA_HINT used for mutation — authority alert{CLI_CLR}")

            # ----- Step 4f: Post-mutation Invariant Validation -----
            if tool_name in ("write", "delete", "move", "mkdir"):
                print(f"{CLI_YELLOW}  [Validation] mutation invariants...{CLI_CLR}")
                warnings = run_post_mutation_validation(
                    state, vm, tool_call, self.trace_logger
                )
                if warnings:
                    print(f"{CLI_YELLOW}VALIDATION WARNING: {warnings[0]}{CLI_CLR}")
                    # Add as feedback to the next step
                    result_text += "\n\n[VALIDATION FEEDBACK]: " + "\n".join(warnings)

            # Track tool call for results
            tool_calls_log.append(
                {
                    "iteration": step_name,
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "result": result_text[:200],
                }
            )

            # Add to conversation history (with compressed tool results)
            compressed_result = _compress_tool_result(tool_name, result_text)
            state["conversation_history"].append(
                {
                    "role": "assistant",
                    "content": next_step.plan_remaining_steps_brief[0],
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": step_name,
                            "function": {
                                "name": tool_name,
                                "arguments": next_step.function.model_dump_json(),
                            },
                        }
                    ],
                }
            )
            state["conversation_history"].append(
                {
                    "role": "tool",
                    "content": compressed_result,
                    "tool_call_id": step_name,
                }
            )

        # Handle timeout
        if not state["is_completed"]:
            state["final_outcome"] = "OUTCOME_ERR_INTERNAL"
            final_answer = f"Task did not complete within {max_iterations} iterations."
            print(f"{CLI_RED}TIMEOUT: {final_answer}{CLI_CLR}")

        # =====================================================================
        # Step 7: Pre-Completion Review (1 LLM call)
        # =====================================================================
        if state["is_completed"] and state["final_outcome"] == "OUTCOME_OK":
            # Code-based pre-completion review (0 LLM calls)
            review_issues = []
            entity_graph = state["scratchpad"].entity_graph
            unresolved = [e for e in entity_graph if e.status == "unresolved"]
            if unresolved:
                review_issues.append(
                    f"Unresolved entities: {', '.join(e.identifier for e in unresolved)}"
                )
            sa = state.get("strategic_analysis")
            if sa:
                pending = [v for v in sa.verification_checklist if v.status == "pending"]
                if pending:
                    review_issues.append(
                        f"Pending checklist items: {', '.join(v.check for v in pending[:3])}"
                    )
            if review_issues:
                print(f"{CLI_YELLOW}[Review] ISSUES: {'; '.join(review_issues)}{CLI_CLR}")
            else:
                print(f"{CLI_GREEN}[Review] APPROVED (code check){CLI_CLR}")

        # =====================================================================
        # Step 8: Send AnswerRequest to PCM (ONLY here!)
        # =====================================================================
        try:
            send_answer(
                vm=vm,
                message=final_answer,
                outcome=state["final_outcome"],
                refs=grounding_refs,
            )
            print(f"{CLI_GREEN}Answer sent to PCM: {state['final_outcome']}{CLI_CLR}")
        except Exception as e:
            print(f"{CLI_RED}Failed to send answer to PCM: {e}{CLI_CLR}")

        # =====================================================================
        # Step 6: Log results
        # =====================================================================
        duration = time.time() - start_time
        self.trace_logger.log_agent_event(
            agent_name="orchestrator",
            event="task_complete",
            details={
                "outcome": state["final_outcome"],
                "duration_seconds": duration,
                "iterations_used": iteration + 1,
                "tool_calls_count": len(tool_calls_log),
                "rules_loaded": len(state["workspace_rules"]),
                "triage_intent": state["triage_result"].intent.value
                if state["triage_result"]
                else "",
            },
        )

        return {
            "task_id": task_id,
            "status": "completed" if final_answer else "incomplete",
            "outcome": state["final_outcome"],
            "final_answer": final_answer,
            "grounding_refs": grounding_refs,
            "completed_steps": completed_steps,
            "tool_calls": tool_calls_log,
            "iterations_used": iteration + 1,
            "duration_seconds": duration,
            "context": {
                "rules_loaded": len(state["workspace_rules"]),
                "rule_paths": list(state["workspace_rules"].keys()),
                "triage_intent": state["triage_result"].intent.value
                if state["triage_result"]
                else "",
            },
        }

    def _build_result(
        self,
        state: AgentState,
        task_id: str,
        start_time: float,
        iterations: int,
    ) -> Dict[str, Any]:
        """Build result dict for early exits (triage blocks, etc.)."""
        duration = time.time() - start_time
        reason = state["triage_result"].reason if state["triage_result"] else "Unknown"

        self.trace_logger.log_agent_event(
            agent_name="orchestrator",
            event="task_complete",
            details={
                "outcome": state["final_outcome"],
                "duration_seconds": duration,
                "iterations_used": iterations,
                "early_exit": True,
                "reason": reason,
            },
        )

        return {
            "task_id": task_id,
            "status": "blocked",
            "outcome": state["final_outcome"],
            "final_answer": f"Blocked: {reason}",
            "grounding_refs": [],
            "completed_steps": [],
            "tool_calls": [],
            "iterations_used": iterations,
            "duration_seconds": duration,
            "context": {
                "triage_intent": state["triage_result"].intent.value
                if state["triage_result"]
                else "",
            },
        }
