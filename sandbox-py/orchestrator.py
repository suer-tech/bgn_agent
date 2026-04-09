import json
import time
from typing import Any, Dict, List, Optional

from agent import (
    NextStep,
    Req_CreatePlan,
    Req_Delete,
    Req_List,
    Req_Read,
    Req_Search,
    Req_Tree,
    Req_UpdatePlanStatus,
    Req_Write,
    ReportTaskCompletion,
    generate_plan_md,
    parse_plan_md,
    update_plan_md_step,
    PLAN_FILE,
)
from bitgn.vm.mini_connect import MiniRuntimeClientSync
from connectrpc.errors import ConnectError
from google.protobuf.json_format import MessageToDict
from llm_logger import LLMTraceLogger

from agents import (
    SecurityGate,
    ContextExtractor,
    ExecutionAgent,
    ValidationAgent,
    TaskContext,
    SecurityCheckResult,
    ContextResult,
    ValidationResult,
)
from llm_provider import LLMProvider


CLI_RED = "\x1b[31m"
CLI_GREEN = "\x1b[32m"
CLI_CLR = "\x1b[0m"
CLI_YELLOW = "\x1b[33m"
CLI_BLUE = "\x1b[34m"


class Orchestrator:
    """
    Main orchestrator that coordinates all sub-agents:

    1. Context Extractor — gathers context at start (LLM-based)
    2. Execution Agent — executes the task (LLM-based)
    3. Security Gate — validates each tool call (hybrid: rules + LLM)
    4. Validation Agent — validates each result (hybrid: rules + LLM)

    All agents use the same LLM provider for consistency.
    """

    def __init__(
        self,
        provider: LLMProvider,
        system_prompt: str = None,
        trace_logger: LLMTraceLogger = None,
    ):
        self.provider = provider
        self.trace_logger = trace_logger

        # Initialize all agents with provider for LLM calls
        self.security_gate = SecurityGate(provider=provider)
        self.context_extractor = ContextExtractor(provider=provider)
        self.execution_agent = ExecutionAgent(provider, system_prompt)
        self.validation_agent = ValidationAgent(provider=provider)

    def run(
        self,
        harness_url: str,
        task_text: str,
        task_id: str,
        max_iterations: int = 30,
    ) -> Dict[str, Any]:
        """
        Run the full orchestrator pipeline.

        Flow:
        1. Context Extraction (LLM-based, once at start)
        2. Loop:
           a. Execution Agent decides next step
           b. Security Gate validates tool call (hybrid)
           c. Execute tool
           d. Validation Agent validates result (hybrid)
           e. Check if task completed

        Returns:
            Dictionary with results
        """
        start_time = time.time()
        tool_calls = []
        completed_steps = []
        final_answer = ""
        grounding_refs = []

        # Initialize trace logger for this task
        if self.trace_logger:
            self.trace_logger.set_task(task_id, task_text)

        print(f"\n{CLI_BLUE}{'=' * 60}")
        print(f"ORCHESTRATOR STARTING - Task: {task_id}")
        print(f"{'=' * 60}{CLI_CLR}\n")

        # Phase 1: Context Extraction (LLM-based)
        print(f"{CLI_YELLOW}[1/4] Context Extraction (LLM)...{CLI_CLR}")
        if self.trace_logger:
            self.trace_logger.log_agent_event(
                agent_name="context_extractor",
                event="extraction_started",
                details={"task_text": task_text[:500]},
            )
        context_result = self.context_extractor.extract_with_llm(harness_url, task_text)

        if self.trace_logger:
            self.trace_logger.log_agent_event(
                agent_name="context_extractor",
                event="extraction_completed",
                details={
                    "success": context_result.success,
                    "errors": context_result.errors,
                    "files_read": len(context_result.extraction_graph.get("files", [])) if context_result.extraction_graph else 0,
                    "extract_status": context_result.extract_status,
                },
            )

        if not context_result.success:
            print(
                f"{CLI_RED}Context extraction failed: {context_result.errors}{CLI_CLR}"
            )

        # Convert to TaskContext
        task_context = self.context_extractor.to_task_context(context_result)
        print(
            f"{CLI_GREEN}Context loaded: {len(task_context.project_rules)} rules{CLI_CLR}"
        )
        if context_result.instruction_hierarchy:
            print(f"  Hierarchy: {context_result.instruction_hierarchy}")

        # Initialize execution state
        conversation_log = []
        current_phase = "discovery"
        plan_content = None

        # Phase 2: Main execution loop
        print(f"{CLI_YELLOW}[2/4] Execution Loop...{CLI_CLR}")

        vm = MiniRuntimeClientSync(harness_url)
        iteration = 0

        for iteration in range(max_iterations):
            iteration_name = f"step_{iteration + 1}"
            print(f"\n{CLI_YELLOW}--- {iteration_name} ({current_phase}) ---{CLI_CLR}")

            # a) Get next step from Execution Agent
            if self.trace_logger:
                self.trace_logger.log_agent_event(
                    agent_name="execution_agent",
                    event="decision_requested",
                    details={
                        "iteration": iteration_name,
                        "phase": current_phase,
                        "conversation_length": len(conversation_log),
                    },
                )
            next_step, is_complete = self.execution_agent.execute(
                task_text=task_text,
                context=task_context,
                conversation_log=conversation_log,
            )

            tool_name = next_step.function.__class__.__name__
            tool_args = next_step.function.model_dump()

            if self.trace_logger:
                self.trace_logger.log_agent_event(
                    agent_name="execution_agent",
                    event="decision_made",
                    details={
                        "iteration": iteration_name,
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "reasoning": next_step.reasoning[:500],
                        "phase": next_step.phase,
                        "task_completed": next_step.task_completed,
                    },
                )

            # b) Security Gate validates the tool call (hybrid: rules + LLM)
            if self.trace_logger:
                self.trace_logger.log_agent_event(
                    agent_name="security_gate",
                    event="check_started",
                    details={
                        "iteration": iteration_name,
                        "tool_name": tool_name,
                        "arguments": tool_args,
                    },
                )
            security_check = self.security_gate.check_hybrid(
                tool_name=tool_name,
                arguments=tool_args,
                task_context=task_context,
                user_input=task_text,
            )

            if self.trace_logger:
                self.trace_logger.log_agent_event(
                    agent_name="security_gate",
                    event="check_completed",
                    details={
                        "iteration": iteration_name,
                        "allowed": security_check.allowed,
                        "reason": security_check.reason,
                        "injection_detected": security_check.injection_detected,
                        "injection_type": security_check.injection_type,
                        "conflicting_rules": security_check.conflicting_rules,
                    },
                )

            if not security_check.allowed:
                print(f"{CLI_RED}SECURITY BLOCKED: {security_check.reason}{CLI_CLR}")
                if security_check.injection_detected:
                    print(
                        f"{CLI_RED}  Injection type: {security_check.injection_type}{CLI_CLR}"
                    )
                if security_check.conflicting_rules:
                    print(
                        f"{CLI_RED}  Conflicting rules: {security_check.conflicting_rules}{CLI_CLR}"
                    )

                conversation_log.append(
                    {
                        "role": "assistant",
                        "content": next_step.reasoning,
                        "tool_calls": [
                            {
                                "type": "function",
                                "id": iteration_name,
                                "function": {
                                    "name": tool_name,
                                    "arguments": next_step.function.model_dump_json(),
                                },
                            }
                        ],
                    }
                )
                conversation_log.append(
                    {
                        "role": "tool",
                        "content": f"BLOCKED BY SECURITY: {security_check.reason}",
                        "tool_call_id": iteration_name,
                    }
                )
                continue

            print(f"  → {tool_name}: {tool_args}")

            # Add to conversation
            conversation_log.append(
                {
                    "role": "assistant",
                    "content": next_step.reasoning,
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": iteration_name,
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args),
                            },
                        }
                    ],
                }
            )

            # Handle create_plan
            if isinstance(next_step.function, Req_CreatePlan):
                plan_content = generate_plan_md(
                    next_step.function.steps,
                    next_step.function.reasoning,
                    task_text,
                )
                try:
                    vm.write(
                        type(
                            "WriteRequest",
                            (),
                            {"path": PLAN_FILE, "content": plan_content},
                        )()
                    )
                except:
                    pass
                conversation_log.append(
                    {
                        "role": "tool",
                        "content": "Plan created",
                        "tool_call_id": iteration_name,
                    }
                )
                current_phase = "execution"
                continue

            # Handle update_plan_status
            if isinstance(next_step.function, Req_UpdatePlanStatus):
                if plan_content:
                    plan_content = update_plan_md_step(
                        plan_content,
                        next_step.function.step_id,
                        next_step.function.status,
                        next_step.function.notes,
                    )
                    completed_steps.append(next_step.function.step_id)
                conversation_log.append(
                    {
                        "role": "tool",
                        "content": "Status updated",
                        "tool_call_id": iteration_name,
                    }
                )
                continue

            # c) Execute the tool
            result_output = ""
            execution_error = None

            try:
                from agent import dispatch

                result = dispatch(vm, next_step.function)
                if result is None:
                    result_output = '{"error": "Operation blocked"}'
                    execution_error = "Operation blocked"
                else:
                    result_dict = MessageToDict(result)
                    result_output = json.dumps(result_dict, indent=2)
            except ConnectError as e:
                result_output = str(e.message)
                execution_error = f"ConnectError: {e.message}"
            except Exception as e:
                result_output = str(e)
                execution_error = str(e)

            if self.trace_logger:
                self.trace_logger.log_tool_event(
                    step_name=iteration_name,
                    tool_name=tool_name,
                    arguments=tool_args,
                    result=result_output[:2000],
                    success=execution_error is None,
                )

            # d) Validation Agent validates result (hybrid: rules + LLM)
            if self.trace_logger:
                self.trace_logger.log_agent_event(
                    agent_name="validation_agent",
                    event="validation_started",
                    details={
                        "iteration": iteration_name,
                        "tool_name": tool_name,
                        "is_error": execution_error is not None,
                    },
                )
            validation = self.validation_agent.validate_hybrid(
                tool_name=tool_name,
                arguments=tool_args,
                result=result_output,
                is_error=execution_error is not None,
                task_text=task_text,
            )

            if self.trace_logger:
                self.trace_logger.log_agent_event(
                    agent_name="validation_agent",
                    event="validation_completed",
                    details={
                        "iteration": iteration_name,
                        "valid": validation.valid,
                        "errors": validation.errors,
                        "warnings": validation.warnings,
                        "retry_needed": validation.retry_needed,
                    },
                )

            if not validation.valid:
                print(f"{CLI_RED}VALIDATION FAILED: {validation.errors}{CLI_CLR}")
                if validation.retry_needed:
                    conversation_log.append(
                        {
                            "role": "tool",
                            "content": f"Result: {result_output[:200]}",
                            "tool_call_id": iteration_name,
                        }
                    )
                    continue

            if validation.warnings:
                print(f"{CLI_YELLOW}Warnings: {validation.warnings}{CLI_CLR}")

            # Add tool result to log
            conversation_log.append(
                {
                    "role": "tool",
                    "content": result_output,
                    "tool_call_id": iteration_name,
                }
            )

            # Track tool call
            tool_calls.append(
                {
                    "iteration": iteration_name,
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "result": result_output[:200],
                }
            )

            # e) Check for completion
            if isinstance(next_step.function, ReportTaskCompletion):
                final_answer = next_step.function.answer
                grounding_refs = next_step.function.grounding_refs
                completed_steps = next_step.function.completed_steps_laconic

                if self.trace_logger:
                    self.trace_logger.log_agent_event(
                        agent_name="execution_agent",
                        event="task_completed",
                        details={
                            "code": next_step.function.code,
                            "answer": final_answer[:500],
                            "grounding_refs": grounding_refs,
                            "completed_steps": completed_steps,
                        },
                    )

                if next_step.function.code == "completed":
                    print(f"\n{CLI_GREEN}{'=' * 60}")
                    print(f"TASK COMPLETED: {task_id}")
                    print(f"{'=' * 60}{CLI_CLR}")
                    break

        # Phase 3: Finalize
        duration = time.time() - start_time

        return {
            "task_id": task_id,
            "status": "completed" if final_answer else "incomplete",
            "final_answer": final_answer,
            "grounding_refs": grounding_refs,
            "completed_steps": completed_steps,
            "tool_calls": tool_calls,
            "iterations_used": iteration + 1,
            "duration_seconds": duration,
            "context": {
                "user_profile": context_result.user_profile,
                "project_rules_count": len(context_result.project_rules),
            },
        }


def create_orchestrator(
    provider: LLMProvider, system_prompt: str = None
) -> Orchestrator:
    """Create an orchestrator instance."""
    return Orchestrator(provider, system_prompt)
