"""Orchestrator — State Machine pipeline for PAC1.

Flow:
1. Initialize AgentState
2. Triage (1 LLM call) → early exit if ATTACK/UNSUPPORTED
3. Bootstrap (0 LLM calls) → load workspace rules via regex
4. Execution Loop (max 30 steps):
   a. build_planner_prompt() + plan_next_step()
   b. Update Scratchpad from LLM response
   c. If report_completion → break
   d. execute_tool() → add to conversation_history
5. Send AnswerRequest to PCM (ONLY here!)
6. Log everything
"""

import json
import time
from typing import Any, Dict, Optional

from bitgn.vm.pcm_connect import PcmRuntimeClientSync

from agents.types import (
    AgentState,
    ScratchpadState,
    ReportTaskCompletion,
    get_outcome_map,
)
from agents.triage_node import run_triage
from agents.bootstrap_node import run_bootstrap
from agents.execution_agent import build_planner_prompt, plan_next_step
from agents.tool_executor import execute_tool
from agents.pcm_helpers import send_answer
from llm_logger import LLMTraceLogger


CLI_RED = "\x1b[31m"
CLI_GREEN = "\x1b[32m"
CLI_CLR = "\x1b[0m"
CLI_YELLOW = "\x1b[33m"
CLI_BLUE = "\x1b[34m"


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
            "workspace_rules": {},
            "scratchpad": ScratchpadState(),
            "conversation_history": [],
            "is_completed": False,
            "final_outcome": "",
        }

        # =====================================================================
        # Step 2: Triage (1 LLM call)
        # =====================================================================
        print(f"{CLI_YELLOW}[1/3] Triage — classifying request...{CLI_CLR}", flush=True)
        state = run_triage(state, self.provider, self.trace_logger)

        if state["is_completed"]:
            outcome = state["final_outcome"]
            reason = state["triage_result"].reason if state["triage_result"] else "Unknown"
            print(f"{CLI_RED}TRIAGE BLOCKED: {outcome} — {reason}{CLI_CLR}")

            # Send answer to PCM
            try:
                send_answer(vm, f"Request blocked by triage: {reason}", outcome)
            except Exception as e:
                print(f"Failed to submit triage block to VM: {e}")

            return self._build_result(state, task_id, start_time, 0)

        triage_info = state["triage_result"]
        print(f"{CLI_GREEN}Triage passed: {triage_info.intent.value} — {triage_info.reason}{CLI_CLR}")

        # =====================================================================
        # Step 3: Bootstrap (0 LLM calls)
        # =====================================================================
        print(f"{CLI_YELLOW}[2/3] Bootstrap — loading workspace rules...{CLI_CLR}")
        state = run_bootstrap(state, vm, self.trace_logger)

        rules_count = len(state["workspace_rules"])
        print(f"{CLI_GREEN}Loaded {rules_count} rule files{CLI_CLR}")
        for path in state["workspace_rules"]:
            print(f"  📄 {path}")

        # =====================================================================
        # Step 4: Execution Loop
        # =====================================================================
        print(f"{CLI_YELLOW}[3/3] Execution loop (max {max_iterations} steps)...{CLI_CLR}")

        tool_calls_log = []
        iteration = 0
        final_answer = ""
        grounding_refs = []
        completed_steps = []

        for iteration in range(max_iterations):
            step_name = f"step_{iteration + 1}"
            print(f"\n{CLI_YELLOW}--- {step_name} ---{CLI_CLR}")

            # 4a. Plan next step
            prompt = build_planner_prompt(state)

            try:
                next_step = plan_next_step(
                    prompt=prompt,
                    conversation_history=state["conversation_history"],
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

            # 4c. Check for completion
            if isinstance(next_step.function, ReportTaskCompletion):
                final_answer = next_step.function.message
                grounding_refs = next_step.function.grounding_refs
                completed_steps = next_step.function.completed_steps_laconic
                state["final_outcome"] = next_step.function.outcome
                state["is_completed"] = True

                status = CLI_GREEN if next_step.function.outcome == "OUTCOME_OK" else CLI_YELLOW
                print(f"{status}TASK COMPLETED: {next_step.function.outcome}{CLI_CLR}")
                print(f"Summary: {final_answer}")
                if grounding_refs:
                    print(f"References: {', '.join(grounding_refs)}")
                break

            # 4d. Execute tool
            tool_name = next_step.function.tool
            tool_args = next_step.function.model_dump()
            # Remove 'tool' key from args since it's the tool name
            tool_args.pop("tool", None)

            tool_call = {"name": tool_name, "arguments": tool_args}

            print(f"  🔧 {tool_name}: {json.dumps(tool_args, ensure_ascii=False)[:200]}")

            result_text = execute_tool(
                tool_call=tool_call,
                vm_client=vm,
                trace_logger=self.trace_logger,
                step_name=step_name,
            )

            print(f"{CLI_GREEN}OUT{CLI_CLR}: {result_text[:200]}...")

            # Track tool call for results
            tool_calls_log.append({
                "iteration": step_name,
                "tool_name": tool_name,
                "arguments": tool_args,
                "result": result_text[:200],
            })

            # Add to conversation history
            state["conversation_history"].append({
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
            })
            state["conversation_history"].append({
                "role": "tool",
                "content": result_text,
                "tool_call_id": step_name,
            })

        # Handle timeout
        if not state["is_completed"]:
            state["final_outcome"] = "OUTCOME_ERR_INTERNAL"
            final_answer = f"Task did not complete within {max_iterations} iterations."
            print(f"{CLI_RED}TIMEOUT: {final_answer}{CLI_CLR}")

        # =====================================================================
        # Step 5: Send AnswerRequest to PCM (ONLY here!)
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
                "triage_intent": state["triage_result"].intent.value if state["triage_result"] else "",
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
                "triage_intent": state["triage_result"].intent.value if state["triage_result"] else "",
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
                "triage_intent": state["triage_result"].intent.value if state["triage_result"] else "",
            },
        }
