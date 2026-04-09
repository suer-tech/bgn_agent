import json
import time
from typing import Any, Dict, Optional

from agents.ambiguity import check_action_ambiguity, check_triage_violation
from bitgn.vm.pcm_connect import PcmRuntimeClientSync

from agents.bootstrap_node import run_bootstrap
from agents.execution_agent import ExecutionAgent
from agents.pcm_helpers import extract_candidate_path, parent_dir, pcm_dispatch, pcm_list
from agents.security import check_tool_call, check_user_input, check_workspace_rules
from agents.state import AgentState, Scratchpad
from agents.trust_policy import check_trust_policy, extract_trust_facts
from agents.triage_node import reroute_triage_with_workspace, run_triage
from agents.types import PROTECTED_FILES, SYSTEM_DIRECTORIES
from agents.workflow_validators import validate_tool_against_workflow
from llm_logger import LLMTraceLogger


CLI_RED = "\x1b[31m"
CLI_GREEN = "\x1b[32m"
CLI_CLR = "\x1b[0m"
CLI_YELLOW = "\x1b[33m"
CLI_BLUE = "\x1b[34m"


class Orchestrator:
    def __init__(
        self,
        provider=None,
        trace_logger: Optional[LLMTraceLogger] = None,
    ):
        self.provider = provider
        self.trace_logger = trace_logger or LLMTraceLogger()
        self.execution_agent = ExecutionAgent(
            provider=provider,
            trace_logger=self.trace_logger,
        )
        self.protected_files = {item.lower() for item in PROTECTED_FILES}
        self.system_directories = tuple(item.lower() for item in SYSTEM_DIRECTORIES)

    def run(
        self,
        harness_url: str,
        task_text: str,
        task_id: str,
        max_iterations: int = 30,
    ) -> Dict[str, Any]:
        start_time = time.time()
        self.trace_logger.set_task(task_id, task_text)
        vm = PcmRuntimeClientSync(harness_url)

        state: AgentState = {
            "task_id": task_id,
            "task_text": task_text,
            "triage_result": None,
            "workspace_rules": {},
            "workspace_metadata": {},
            "scratchpad": Scratchpad(),
            "grounded_paths": [],
            "candidate_entities": {},
            "trust_facts": {},
            "validated_invariants": [],
            "history": [],
            "is_completed": False,
            "final_outcome": "",
        }

        tool_calls = []
        grounded_paths: set[str] = set()
        completion_args: Dict[str, Any] = {}

        print(f"\n{CLI_BLUE}{'=' * 60}")
        print(f"ORCHESTRATOR STARTING - Task: {task_id}")
        print(f"{'=' * 60}{CLI_CLR}\n")

        input_security = check_user_input(task_text)
        self.trace_logger.log_agent_event(
            agent_name="security_node",
            event="input_check",
            details=input_security.model_dump(),
        )
        if not input_security.allowed:
            self.trace_logger.log_decision(
                step_name="preflight",
                stage="input_security",
                outcome="OUTCOME_DENIED_SECURITY",
                reason=input_security.reason or "Blocked unsafe input.",
                details=input_security.model_dump(),
            )
            return self._complete_with_result(
                vm=vm,
                state=state,
                message=input_security.reason or "Blocked unsafe input.",
                outcome="OUTCOME_DENIED_SECURITY",
                grounding_refs=[],
                completed_steps=[],
                tool_calls=tool_calls,
                start_time=start_time,
            )

        triage = run_triage(task_text)
        state["triage_result"] = triage.model_dump()
        self.trace_logger.log_agent_event(
            agent_name="triage_node",
            event="triage_completed",
            details=triage.model_dump(),
        )

        if not triage.is_safe:
            self.trace_logger.log_decision(
                step_name="preflight",
                stage="triage",
                outcome="OUTCOME_DENIED_SECURITY",
                reason=triage.reason,
                details=triage.model_dump(),
            )
            result = self._complete_with_result(
                vm=vm,
                state=state,
                message=triage.reason,
                outcome="OUTCOME_DENIED_SECURITY",
                grounding_refs=[],
                completed_steps=[],
                tool_calls=tool_calls,
                start_time=start_time,
            )
            return result

        state = run_bootstrap(state, vm, self.trace_logger)
        triage = reroute_triage_with_workspace(task_text, state["workspace_rules"], triage)
        state["triage_result"] = triage.model_dump()
        self.trace_logger.log_agent_event(
            agent_name="triage_node",
            event="triage_rerouted",
            details=triage.model_dump(),
        )
        if triage.intent.value == "UNSUPPORTED":
            self.trace_logger.log_decision(
                step_name="preflight",
                stage="triage_rerouted",
                outcome="OUTCOME_NONE_UNSUPPORTED",
                reason=triage.reason,
                details=triage.model_dump(),
            )
            return self._complete_with_result(
                vm=vm,
                state=state,
                message=triage.reason,
                outcome="OUTCOME_NONE_UNSUPPORTED",
                grounding_refs=[],
                completed_steps=[],
                tool_calls=tool_calls,
                start_time=start_time,
            )
        state["trust_facts"] = extract_trust_facts(state["workspace_rules"])
        trust_policy_result = check_trust_policy(task_text, state["trust_facts"])
        self.trace_logger.log_agent_event(
            agent_name="trust_policy",
            event="trust_facts_extracted",
            details=state["trust_facts"],
        )
        if trust_policy_result is not None:
            self.trace_logger.log_agent_event(
                agent_name="trust_policy",
                event="trust_policy_block",
                details=trust_policy_result.model_dump(),
            )
            self.trace_logger.log_decision(
                step_name="preflight",
                stage="trust_policy",
                outcome="OUTCOME_DENIED_SECURITY",
                reason=trust_policy_result.reason or "Blocked by trust policy.",
                details=trust_policy_result.model_dump(),
            )
            return self._complete_with_result(
                vm=vm,
                state=state,
                message=trust_policy_result.reason or "Blocked by trust policy.",
                outcome="OUTCOME_DENIED_SECURITY",
                grounding_refs=[],
                completed_steps=[],
                tool_calls=tool_calls,
                start_time=start_time,
            )
        context_security = check_workspace_rules(state["workspace_rules"])
        self.trace_logger.log_agent_event(
            agent_name="security_node",
            event="context_check",
            details=context_security.model_dump(),
        )
        if not context_security.allowed:
            self.trace_logger.log_decision(
                step_name="preflight",
                stage="context_security",
                outcome="OUTCOME_DENIED_SECURITY",
                reason=context_security.reason or "Blocked suspicious bootstrap context.",
                details=context_security.model_dump(),
            )
            return self._complete_with_result(
                vm=vm,
                state=state,
                message=context_security.reason or "Blocked suspicious bootstrap context.",
                outcome="OUTCOME_DENIED_SECURITY",
                grounding_refs=[],
                completed_steps=[],
                tool_calls=tool_calls,
                start_time=start_time,
            )

        for key in state["workspace_rules"].keys():
            if key.startswith("/"):
                grounded_paths.add(key.lstrip("/").lower())
        self._sync_grounded_paths(state, grounded_paths)

        self._audit_scratchpad(
            previous=Scratchpad(),
            current=Scratchpad.model_validate(state["scratchpad"]),
            reason="bootstrap_complete",
        )

        for iteration in range(max_iterations):
            step_name = f"step_{iteration + 1}"
            self.trace_logger.log_step_boundary(
                step_name=step_name,
                boundary="start",
                details={
                    "grounded_paths_count": len(grounded_paths),
                    "candidate_groups": list(state["candidate_entities"].keys()),
                    "validated_invariants_count": len(state["validated_invariants"]),
                },
            )
            next_step = self.execution_agent.execute(state)
            next_scratchpad = Scratchpad.model_validate(next_step.scratchpad_update)

            self._audit_scratchpad(
                previous=Scratchpad.model_validate(state["scratchpad"]),
                current=next_scratchpad,
                reason=step_name,
            )
            state["scratchpad"] = next_scratchpad

            tool_name = next_step.tool_call.name
            arguments = dict(next_step.tool_call.arguments)
            triage_violation = check_triage_violation(state["triage_result"], tool_name)
            ambiguity_reason = check_action_ambiguity(
                tool_name,
                arguments,
                Scratchpad.model_validate(state["scratchpad"]),
                state["task_text"],
                state["candidate_entities"],
            )

            if triage_violation:
                self.trace_logger.log_decision(
                    step_name=step_name,
                    stage="triage_violation",
                    outcome="OUTCOME_NONE_UNSUPPORTED",
                    reason=triage_violation,
                    details={"tool_name": tool_name, "arguments": arguments},
                )
                return self._complete_with_result(
                    vm=vm,
                    state=state,
                    message=triage_violation,
                    outcome="OUTCOME_NONE_UNSUPPORTED",
                    grounding_refs=[],
                    completed_steps=Scratchpad.model_validate(state["scratchpad"]).completed_steps,
                    tool_calls=tool_calls,
                    start_time=start_time,
                )

            if ambiguity_reason:
                self.trace_logger.log_decision(
                    step_name=step_name,
                    stage="ambiguity_gate",
                    outcome="OUTCOME_NONE_CLARIFICATION",
                    reason=ambiguity_reason,
                    details={"tool_name": tool_name, "arguments": arguments},
                )
                return self._complete_with_result(
                    vm=vm,
                    state=state,
                    message=ambiguity_reason,
                    outcome="OUTCOME_NONE_CLARIFICATION",
                    grounding_refs=[],
                    completed_steps=Scratchpad.model_validate(state["scratchpad"]).completed_steps,
                    tool_calls=tool_calls,
                    start_time=start_time,
                )

            tool_security = check_tool_call(
                tool_name,
                arguments,
                seen_paths=grounded_paths,
            )
            block_reason = self._validate_tool_call(tool_name, arguments, grounded_paths)
            if not tool_security.allowed:
                self.trace_logger.log_agent_event(
                    agent_name="security_node",
                    event="tool_check",
                    details={
                        "tool_name": tool_name,
                        **tool_security.model_dump(),
                    },
                )
                self.trace_logger.log_decision(
                    step_name=step_name,
                    stage="tool_security",
                    outcome="OUTCOME_DENIED_SECURITY",
                    reason=tool_security.reason or "Blocked unsafe tool call.",
                    details={"tool_name": tool_name, **tool_security.model_dump()},
                )
                return self._complete_with_result(
                    vm=vm,
                    state=state,
                    message=tool_security.reason or "Blocked unsafe tool call.",
                    outcome="OUTCOME_DENIED_SECURITY",
                    grounding_refs=[],
                    completed_steps=Scratchpad.model_validate(state["scratchpad"]).completed_steps,
                    tool_calls=tool_calls,
                    start_time=start_time,
                )
            workflow_violation = validate_tool_against_workflow(state, tool_name, arguments)
            if workflow_violation:
                self.trace_logger.log_agent_event(
                    agent_name="workflow_validator",
                    event="validation_failed",
                    details={
                        "tool_name": tool_name,
                        "reason": workflow_violation.reason,
                        "outcome": workflow_violation.outcome,
                    },
                )
                self.trace_logger.log_decision(
                    step_name=step_name,
                    stage="workflow_validator",
                    outcome=workflow_violation.outcome,
                    reason=workflow_violation.reason,
                    details={"tool_name": tool_name, "arguments": arguments},
                )
                return self._complete_with_result(
                    vm=vm,
                    state=state,
                    message=workflow_violation.reason,
                    outcome=workflow_violation.outcome,
                    grounding_refs=[],
                    completed_steps=Scratchpad.model_validate(state["scratchpad"]).completed_steps,
                    tool_calls=tool_calls,
                    start_time=start_time,
                )
            elif block_reason:
                result_output = f"BLOCKED BY GUARDRAILS: {block_reason}"
                self.trace_logger.log_agent_event(
                    agent_name="actuator_node",
                    event="tool_blocked",
                    details={"tool_name": tool_name, "reason": block_reason},
                )
                self.trace_logger.log_decision(
                    step_name=step_name,
                    stage="guardrail_block",
                    outcome="CONTINUE",
                    reason=block_reason,
                    details={"tool_name": tool_name, "arguments": arguments},
                )
            else:
                self.trace_logger.log_agent_event(
                    agent_name="security_node",
                    event="tool_check",
                    details={
                        "tool_name": tool_name,
                        **tool_security.model_dump(),
                    },
                )
                before_grounded = list(state["grounded_paths"])
                before_candidates = dict(state["candidate_entities"])
                before_validated = list(state["validated_invariants"])
                self._record_validated_invariant(state, tool_name, arguments)
                result_output = pcm_dispatch(vm, tool_name, arguments)
                if tool_name == "delete":
                    verification = pcm_list(vm, parent_dir(arguments.get("path", "")))
                    result_output = f"{result_output}\n\nPOST_DELETE_CHECK\n{verification}"
                previous_candidates = json.dumps(state["candidate_entities"], ensure_ascii=False)
                previous_scratchpad = Scratchpad.model_validate(state["scratchpad"])
                self._mark_seen_paths(tool_name, arguments, result_output, grounded_paths)
                self._update_batch_pending_items(state, tool_name, arguments, result_output)
                self._update_candidate_entities(state, tool_name, arguments, result_output)
                self._sync_grounded_paths(state, grounded_paths)
                current_scratchpad = Scratchpad.model_validate(state["scratchpad"])
                self._audit_scratchpad(
                    previous=previous_scratchpad,
                    current=current_scratchpad,
                    reason=f"{step_name}_runtime_state",
                )
                self.trace_logger.log_state_diff(
                    step_name=step_name,
                    state_name="grounded_paths",
                    before=before_grounded,
                    after=state["grounded_paths"],
                )
                self.trace_logger.log_state_diff(
                    step_name=step_name,
                    state_name="candidate_entities",
                    before=before_candidates,
                    after=state["candidate_entities"],
                )
                self.trace_logger.log_state_diff(
                    step_name=step_name,
                    state_name="validated_invariants",
                    before=before_validated,
                    after=state["validated_invariants"],
                )
                current_candidates = json.dumps(state["candidate_entities"], ensure_ascii=False)
                if previous_candidates != current_candidates:
                    self.trace_logger.append_task_summary(
                        title="candidate_entities_update",
                        details={
                            "tool_name": tool_name,
                            "candidates": current_candidates,
                        },
                    )

            assistant_content = (
                next_step.plan_remaining_steps_brief[0]
                if next_step.plan_remaining_steps_brief
                else next_step.current_state
            )
            state["history"].append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": step_name,
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        }
                    ],
                }
            )
            state["history"].append(
                {
                    "role": "tool",
                    "content": result_output,
                    "tool_call_id": step_name,
                }
            )

            tool_calls.append(
                {
                    "iteration": step_name,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result": result_output[:500],
                }
            )
            self.trace_logger.log_tool_event(
                step_name=step_name,
                tool_name=tool_name,
                arguments=arguments,
                result=result_output,
                success=not result_output.startswith("ERROR") and not result_output.startswith("BLOCKED"),
            )
            self.trace_logger.log_step_boundary(
                step_name=step_name,
                boundary="end",
                details={
                    "tool_name": tool_name,
                    "success": not result_output.startswith("ERROR") and not result_output.startswith("BLOCKED"),
                    "result_preview": result_output[:300],
                    "grounded_paths_count": len(state["grounded_paths"]),
                    "candidate_groups": list(state["candidate_entities"].keys()),
                    "validated_invariants_count": len(state["validated_invariants"]),
                },
            )

            if tool_name == "report_completion":
                state["is_completed"] = True
                state["final_outcome"] = arguments.get("outcome", "OUTCOME_ERR_INTERNAL")
                completion_args = arguments
                break

        duration = time.time() - start_time
        if state["is_completed"]:
            return {
                "task_id": task_id,
                "status": "completed",
                "outcome": state["final_outcome"],
                "final_answer": completion_args.get("message", ""),
                "grounding_refs": completion_args.get("grounding_refs", []),
                "completed_steps": completion_args.get("completed_steps_laconic", []),
                "tool_calls": tool_calls,
                "iterations_used": len(tool_calls),
                "duration_seconds": duration,
                "context": {"workspace_rule_keys": list(state["workspace_rules"].keys())},
            }

        return {
            "task_id": task_id,
            "status": "incomplete",
            "outcome": "OUTCOME_ERR_INTERNAL",
            "final_answer": "Iteration limit reached before completion.",
            "grounding_refs": [],
            "completed_steps": Scratchpad.model_validate(state["scratchpad"]).completed_steps,
            "tool_calls": tool_calls,
            "iterations_used": len(tool_calls),
            "duration_seconds": duration,
            "context": {"workspace_rule_keys": list(state["workspace_rules"].keys())},
        }

    def _complete_with_result(
        self,
        vm: PcmRuntimeClientSync,
        state: AgentState,
        message: str,
        outcome: str,
        grounding_refs: list[str],
        completed_steps: list[str],
        tool_calls: list[dict[str, Any]],
        start_time: float,
    ) -> Dict[str, Any]:
        self.trace_logger.log_completion_decision(
            outcome=outcome,
            message=message,
            completed_steps=completed_steps,
            grounding_refs=grounding_refs,
        )
        pcm_dispatch(
            vm,
            "report_completion",
            {
                "message": message,
                "outcome": outcome,
                "grounding_refs": grounding_refs,
                "completed_steps_laconic": completed_steps,
            },
        )
        duration = time.time() - start_time
        state["is_completed"] = True
        state["final_outcome"] = outcome
        return {
            "task_id": state["task_id"],
            "status": "completed",
            "outcome": outcome,
            "final_answer": message,
            "grounding_refs": grounding_refs,
            "completed_steps": completed_steps,
            "tool_calls": tool_calls,
            "iterations_used": len(tool_calls),
            "duration_seconds": duration,
            "context": {"workspace_rule_keys": list(state["workspace_rules"].keys())},
        }

    def _validate_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        grounded_paths: set[str],
    ) -> Optional[str]:
        candidate_path = extract_candidate_path(tool_name, arguments)
        normalized = (candidate_path or "").replace("\\", "/").lstrip("/").lower()

        if candidate_path:
            for system_dir in self.system_directories:
                if normalized.startswith(system_dir.replace("\\", "/").lstrip("/")):
                    return f"System path access is forbidden: {candidate_path}"

        if tool_name in {"write", "delete", "move"}:
            if normalized and any(part in normalized for part in self.protected_files):
                return f"Protected path is immutable: {candidate_path}"
            if tool_name in {"write", "delete"} and normalized and normalized not in grounded_paths:
                return f"Path was not discovered earlier in session: {candidate_path}"
            if tool_name == "move":
                source = (arguments.get("from_name", "") or "").replace("\\", "/").lstrip("/").lower()
                if source and source not in grounded_paths:
                    return f"Move source was not discovered earlier in session: {arguments.get('from_name', '')}"

        return None

    def _mark_seen_paths(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result_output: str,
        grounded_paths: set[str],
    ) -> None:
        candidate_path = extract_candidate_path(tool_name, arguments)
        if candidate_path:
            grounded_paths.add(candidate_path.replace("\\", "/").lstrip("/").lower())

        if tool_name == "find":
            for line in result_output.splitlines():
                stripped = line.strip()
                if '"path":' in stripped:
                    path = stripped.split(":", 1)[1].strip().strip('",')
                    grounded_paths.add(path.replace("\\", "/").lstrip("/").lower())
        if tool_name in {"search"}:
            for line in result_output.splitlines():
                if ":" in line and "/" in line:
                    path = line.split(":", 1)[0].strip()
                    grounded_paths.add(path.replace("\\", "/").lstrip("/").lower())
        if tool_name in {"list", "ls"}:
            base = (arguments.get("path", "/") or "/").replace("\\", "/").strip("/")
            for line in result_output.splitlines()[1:]:
                entry = line.strip().rstrip("/")
                if not entry or entry == ".":
                    continue
                full_path = f"{base}/{entry}".strip("/")
                grounded_paths.add(full_path.lower())
        if tool_name == "tree":
            root = (arguments.get("root", "/") or "/").replace("\\", "/").strip("/")
            lines = result_output.splitlines()
            if not lines:
                return
            
            # The first line is usually the root name or the command result header
            # We initialize the stack with the root provided in arguments
            stack = [root] if root else []
            
            for line in lines[1:]:
                # Detect indentation level (4 characters per level: '|   ' or '    ')
                # line looks like '|   |-- filename' or '|-- filename'
                prefix_match = re.match(r"^([| ]   )*", line)
                indent_len = len(prefix_match.group(0)) if prefix_match else 0
                depth = indent_len // 4
                
                # Extract clean name by removing branch symbols
                # We handle ASCII (|--, `--) and standard tree branch characters
                candidate = re.sub(r"^[| `\t]*[|-]{2,}\s*", "", line[indent_len:]).strip()
                candidate = candidate.rstrip("/")
                
                if not candidate or candidate == "." or "directory" in candidate.lower():
                    continue
                
                # Adjust stack to current depth
                # Level 0 files/dirs are children of root
                while len(stack) > depth + (1 if root else 0):
                    stack.pop()
                
                # Construct full path
                current_full_path = "/".join(stack + [candidate]).strip("/")
                grounded_paths.add(current_full_path.replace("\\", "/").lstrip("/").lower())
                
                # If it's a directory (no extension or explicit trailing slash in tree output)
                # we don't know for sure if it's a dir, but if it has no dot it's a candidate for stack
                # Actually, tree -F adds / but we can't rely on it.
                # However, for grounding purposes, we can optimistically push to stack 
                # if the next line has more indentation.
                # A more robust way: push if it's not a known file type
                if "." not in candidate:
                    stack.append(candidate)
        if tool_name in {"read", "cat"}:
            path = arguments.get("path", "")
            if path:
                grounded_paths.add(path.replace("\\", "/").lstrip("/").lower())

    def _sync_grounded_paths(self, state: AgentState, grounded_paths: set[str]) -> None:
        state["grounded_paths"] = sorted(grounded_paths)

    def _update_candidate_entities(
        self,
        state: AgentState,
        tool_name: str,
        arguments: Dict[str, Any],
        result_output: str,
    ) -> None:
        candidates = {key: list(value) for key, value in state["candidate_entities"].items()}

        def add_candidate(group: str, value: str) -> None:
            normalized = value.strip().strip('",} ]')
            if not normalized:
                return
            bucket = candidates.setdefault(group, [])
            if normalized not in bucket:
                bucket.append(normalized)

        if tool_name == "find":
            name = str(arguments.get("name", "")).strip()
            group = "entity"
            lowered_name = name.lower()
            for key in ("contact", "account", "invoice", "thread", "card", "channel", "message"):
                if key in lowered_name:
                    group = key
                    break
            for line in result_output.splitlines():
                stripped = line.strip()
                if '"path":' in stripped:
                    value = stripped.split(":", 1)[1].strip().strip('",')
                    add_candidate(group, value)

        if tool_name == "search":
            pattern = str(arguments.get("pattern", "")).strip()
            group = "entity"
            lowered_pattern = pattern.lower()
            for key in ("contact", "account", "invoice", "thread", "card", "channel", "message", "recipient", "sender"):
                if key in lowered_pattern:
                    group = key
                    break
            for line in result_output.splitlines():
                if ":" in line and "/" in line:
                    add_candidate(group, line.split(":", 1)[0].strip())

        if tool_name in {"list", "ls"} and not self._is_batch_directory_discovery(state, arguments):
            base = str(arguments.get("path", "")).lower()
            group = "entity"
            if "threads" in base:
                group = "thread"
            elif "cards" in base:
                group = "card"
            elif "accounts" in base:
                group = "account"
            elif "contacts" in base:
                group = "contact"
            elif "invoices" in base:
                group = "invoice"
            for line in result_output.splitlines()[1:]:
                entry = line.strip().rstrip("/")
                if entry and entry != ".":
                    add_candidate(group, entry)

        state["candidate_entities"] = candidates

    def _update_batch_pending_items(
        self,
        state: AgentState,
        tool_name: str,
        arguments: Dict[str, Any],
        result_output: str,
    ) -> None:
        scratchpad = Scratchpad.model_validate(state["scratchpad"])
        pending = list(scratchpad.pending_items)

        if tool_name in {"list", "ls"} and self._is_batch_directory_discovery(state, arguments):
            base = (arguments.get("path", "/") or "/").replace("\\", "/").strip("/")
            for line in result_output.splitlines()[1:]:
                entry = line.strip().rstrip("/")
                if not entry or entry == ".":
                    continue
                full_path = f"{base}/{entry}".strip("/")
                if full_path not in pending:
                    pending.append(full_path)

        if tool_name == "delete":
            deleted_path = (arguments.get("path", "") or "").replace("\\", "/").lstrip("/")
            pending = [item for item in pending if item != deleted_path]

        scratchpad.pending_items = pending
        state["scratchpad"] = scratchpad

    def _is_batch_directory_discovery(
        self,
        state: AgentState,
        arguments: Dict[str, Any],
    ) -> bool:
        base = str(arguments.get("path", "")).lower()
        if not any(token in base for token in ("cards", "threads", "invoices", "messages", "items")):
            return False

        scratchpad = Scratchpad.model_validate(state["scratchpad"])
        haystack = " ".join(
            part.lower()
            for part in (state["task_text"], scratchpad.current_goal)
            if part
        )
        return any(
            token in haystack
            for token in (
                "all",
                "every",
                "cleanup",
                "clean",
                "start over",
                "remove all",
                "delete all",
                "process all",
            )
        )

    def _record_validated_invariant(
        self,
        state: AgentState,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> None:
        if tool_name not in {"write", "move", "report_completion"}:
            return
        path = arguments.get("path") or arguments.get("from_name") or arguments.get("to_name") or ""
        marker = f"{tool_name}:{path}"
        validated = list(state["validated_invariants"])
        if marker not in validated:
            validated.append(marker)
        state["validated_invariants"] = validated

    def _audit_scratchpad(self, previous: Scratchpad, current: Scratchpad, reason: str) -> None:
        if previous.model_dump() == current.model_dump():
            return
        self.trace_logger.append_task_summary(
            title="scratchpad_update",
            details={
                "reason": reason,
                "previous_goal": previous.current_goal,
                "current_goal": current.current_goal,
                "found_entities": json.dumps(current.found_entities, ensure_ascii=False),
                "missing_info": current.missing_info,
                "pending_items": json.dumps(current.pending_items, ensure_ascii=False),
                "completed_steps": json.dumps(current.completed_steps, ensure_ascii=False),
            },
        )


def create_orchestrator(provider=None) -> Orchestrator:
    return Orchestrator(provider=provider)
