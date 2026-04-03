import json
import time
from typing import Any, Dict, List, Optional

from agents.execution_agent import (
    NextStep,
    ReportTaskCompletion,
    Req_Context,
    Req_Tree,
    Req_Find,
    Req_Search,
    Req_List,
    Req_Read,
    Req_Write,
    Req_Delete,
    Req_MkDir,
    Req_Move,
)
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import (
    AnswerRequest,
    ContextRequest,
    DeleteRequest,
    FindRequest,
    ListRequest,
    MkDirRequest,
    MoveRequest,
    Outcome,
    ReadRequest,
    SearchRequest,
    TreeRequest,
    WriteRequest,
)
from connectrpc.errors import ConnectError
from google.protobuf.json_format import MessageToDict

from agents import (
    SecurityGate,
    ContextExtractor,
    ExecutionAgent,
    TaskContext,
    SecurityCheckResult,
    ContextResult,
)
from llm_logger import LLMTraceLogger


CLI_RED = "\x1b[31m"
CLI_GREEN = "\x1b[32m"
CLI_CLR = "\x1b[0m"
CLI_YELLOW = "\x1b[33m"
CLI_BLUE = "\x1b[34m"

OUTCOME_BY_NAME = {
    "OUTCOME_OK": Outcome.OUTCOME_OK,
    "OUTCOME_DENIED_SECURITY": Outcome.OUTCOME_DENIED_SECURITY,
    "OUTCOME_NONE_CLARIFICATION": Outcome.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_NONE_UNSUPPORTED": Outcome.OUTCOME_NONE_UNSUPPORTED,
    "OUTCOME_ERR_INTERNAL": Outcome.OUTCOME_ERR_INTERNAL,
}


def dispatch_pac1(vm: PcmRuntimeClientSync, cmd):
    """Dispatch command to PCM runtime."""
    if isinstance(cmd, Req_Context):
        return vm.context(ContextRequest())
    if isinstance(cmd, Req_Tree):
        return vm.tree(TreeRequest(root=cmd.root, level=cmd.level))
    if isinstance(cmd, Req_Find):
        return vm.find(
            FindRequest(
                root=cmd.root,
                name=cmd.name,
                type={"all": 0, "files": 1, "dirs": 2}[cmd.kind],
                limit=cmd.limit,
            )
        )
    if isinstance(cmd, Req_Search):
        return vm.search(
            SearchRequest(root=cmd.root, pattern=cmd.pattern, limit=cmd.limit)
        )
    if isinstance(cmd, Req_List):
        return vm.list(ListRequest(name=cmd.path))
    if isinstance(cmd, Req_Read):
        return vm.read(
            ReadRequest(
                path=cmd.path,
                number=cmd.number,
                start_line=cmd.start_line,
                end_line=cmd.end_line,
            )
        )
    if isinstance(cmd, Req_Write):
        return vm.write(
            WriteRequest(
                path=cmd.path,
                content=cmd.content,
                start_line=cmd.start_line,
                end_line=cmd.end_line,
            )
        )
    if isinstance(cmd, Req_Delete):
        return vm.delete(DeleteRequest(path=cmd.path))
    if isinstance(cmd, Req_MkDir):
        return vm.mk_dir(MkDirRequest(path=cmd.path))
    if isinstance(cmd, Req_Move):
        return vm.move(MoveRequest(from_name=cmd.from_name, to_name=cmd.to_name))
    if isinstance(cmd, ReportTaskCompletion):
        return vm.answer(
            AnswerRequest(
                message=cmd.message,
                outcome=OUTCOME_BY_NAME[cmd.outcome],
                refs=cmd.grounding_refs,
            )
        )
    raise ValueError(f"Unknown command: {cmd}")


class Orchestrator:
    """
    Main orchestrator that coordinates all sub-agents for PAC1:

    1. Security Gate (input) -- validates task text for injections
    2. Context Extractor -- extracts workspace structure and instruction graph
    3. Security Gate (context) -- validates extracted context
    4. Execution Agent -- executes the task with enriched context
    5. Security Gate (tool calls) -- validates each tool call before execution

    All steps are logged to pac1-py/logs/
    """

    def __init__(
        self,
        provider=None,
        system_prompt: str = None,
        trace_logger: Optional[LLMTraceLogger] = None,
    ):
        self.provider = provider
        self.system_prompt = system_prompt

        # Initialize all agents
        self.security_gate = SecurityGate(provider=provider)
        self.context_extractor = ContextExtractor(provider=provider, trace_logger=trace_logger)
        self.execution_agent = ExecutionAgent(
            provider=provider, system_prompt=system_prompt, trace_logger=trace_logger
        )

        # Logger
        self.trace_logger = trace_logger or LLMTraceLogger()

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
        1. Security check on input
        2. Extract context (directory structure + instruction graph)
        3. Security check on extracted context
        4. Execute task with enriched context
        5. Log all steps

        Returns:
            Dictionary with results
        """
        start_time = time.time()
        tool_calls = []
        completed_steps = []
        final_answer = ""
        grounding_refs = []
        outcome = "OUTCOME_ERR_INTERNAL"

        print(f"\n{CLI_BLUE}{'=' * 60}")
        print(f"ORCHESTRATOR STARTING - Task: {task_id}")
        print(f"{'=' * 60}{CLI_CLR}\n")

        # Set up logger
        self.trace_logger.set_task(task_id, task_text)

        # ===== Phase 1: Security check on input =====
        print(f"{CLI_YELLOW}[1/5] Security check on input...{CLI_CLR}")
        input_security = self.security_gate.check_input(task_text)

        if not input_security.allowed:
            print(f"{CLI_RED}INPUT BLOCKED: {input_security.reason}{CLI_CLR}")
            return self._create_error_result(
                task_id, "blocked_by_security", input_security.reason
            )

        if input_security.injection_detected:
            print(
                f"{CLI_YELLOW}Injection detected: {input_security.injection_type}{CLI_CLR}"
            )
            task_text = input_security.sanitized_input or task_text

        self.trace_logger.log_agent_event(
            agent_name="security_gate",
            event="input_check",
            details={
                "allowed": input_security.allowed,
                "injection_detected": input_security.injection_detected,
                "injection_type": input_security.injection_type,
            },
        )

        # ===== Phase 2: Extract context =====
        print(f"{CLI_YELLOW}[2/5] Extracting context...{CLI_CLR}")
        try:
            context_result = self.context_extractor.extract_with_llm(
                harness_url=harness_url,
                task_text=task_text,
            )
            print(
                f"{CLI_GREEN}Context extracted: {context_result.extract_status}{CLI_CLR}"
            )

            # Show directory structure
            if context_result.directory_tree_formatted:
                print(f"{CLI_BLUE}Directory structure:{CLI_CLR}")
                try:
                    print(context_result.directory_tree_formatted[:500])
                except UnicodeEncodeError:
                    # Fallback for encoding issues
                    safe_output = (
                        context_result.directory_tree_formatted[:500]
                        .encode("utf-8", errors="replace")
                        .decode("utf-8", errors="replace")
                    )
                    print(safe_output)

            # Show instruction graph
            if context_result.instruction_dependency_graph:
                graph = context_result.instruction_dependency_graph
                print(f"{CLI_BLUE}Instruction graph hierarchy:{CLI_CLR}")
                print(f"  {' -> '.join(graph.hierarchy)}")

        except Exception as e:
            print(f"{CLI_RED}Context extraction failed: {e}{CLI_CLR}")
            context_result = ContextResult(extract_status="failed")

        self.trace_logger.log_agent_event(
            agent_name="context_extractor",
            event="extract_complete",
            details={
                "status": context_result.extract_status,
                "agents_md_path": context_result.agents_md_path,
                "referenced_files_count": len(context_result.referenced_files),
                "directory_structure_available": bool(
                    context_result.directory_structure
                ),
            },
        )

        # ===== Phase 3: Security check on extracted context =====
        print(f"{CLI_YELLOW}[3/5] Security check on context...{CLI_CLR}")
        context_content = context_result.agents_md_content
        for path, content in context_result.referenced_files.items():
            context_content += f"\n\n--- {path} ---\n{content}"

        context_security = self.security_gate.check_context(context_content)
        if context_security.injection_detected:
            print(
                f"{CLI_YELLOW}Hidden instructions in context: {context_security.injection_type}{CLI_CLR}"
            )

        self.trace_logger.log_agent_event(
            agent_name="security_gate",
            event="context_check",
            details={
                "allowed": context_security.allowed,
                "injection_detected": context_security.injection_detected,
                "injection_type": context_security.injection_type,
            },
        )

        # ===== Phase 4: Build task context =====
        print(f"{CLI_YELLOW}[4/5] Building task context...{CLI_CLR}")
        task_context = self.context_extractor.to_task_context(
            context_result=context_result,
            task_text=task_text,
        )
        print(f"{CLI_GREEN}Task context built{CLI_CLR}")

        # ===== Phase 5: Execute task =====
        print(f"{CLI_YELLOW}[5/5] Executing task...{CLI_CLR}")

        vm = PcmRuntimeClientSync(harness_url)
        conversation_log = []
        iteration = 0

        for iteration in range(max_iterations):
            iteration_name = f"step_{iteration + 1}"
            print(f"\n{CLI_YELLOW}--- {iteration_name} ---{CLI_CLR}")

            # Get next step from execution agent
            next_step, is_complete = self.execution_agent.execute(
                task_text=task_text,
                context=task_context,
                conversation_log=conversation_log,
            )

            # Check for completion BEFORE breaking - extract answer data
            if isinstance(next_step.function, ReportTaskCompletion):
                final_answer = next_step.function.message
                grounding_refs = next_step.function.grounding_refs
                completed_steps = next_step.function.completed_steps_laconic
                outcome = next_step.function.outcome

                status = CLI_GREEN if outcome == "OUTCOME_OK" else CLI_YELLOW
                print(f"{status}TASK COMPLETED: {outcome}{CLI_CLR}")
                print(f"Summary: {final_answer}")
                if grounding_refs:
                    print(f"References: {', '.join(grounding_refs)}")
                break

            if is_complete:
                break

            tool_name = next_step.function.__class__.__name__
            tool_args = next_step.function.model_dump()

            # Security check on tool call
            tool_security = self.security_gate.check_tool_call(
                tool_name=tool_name,
                arguments=tool_args,
            )

            if not tool_security.allowed:
                print(f"{CLI_RED}TOOL BLOCKED: {tool_security.reason}{CLI_CLR}")
                conversation_log.append(
                    {
                        "role": "assistant",
                        "content": next_step.plan_remaining_steps_brief[0]
                        if next_step.plan_remaining_steps_brief
                        else "",
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
                        "content": f"BLOCKED BY SECURITY: {tool_security.reason}",
                        "tool_call_id": iteration_name,
                    }
                )
                continue

            print(f"  -> {tool_name}: {tool_args}")

            # Add to conversation
            conversation_log.append(
                {
                    "role": "assistant",
                    "content": next_step.plan_remaining_steps_brief[0]
                    if next_step.plan_remaining_steps_brief
                    else "",
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

            # Execute tool
            result_output = ""
            try:
                result = dispatch_pac1(vm, next_step.function)
                if result is None:
                    result_output = '{"error": "Operation blocked"}'
                else:
                    result_dict = MessageToDict(result)
                    result_output = json.dumps(result_dict, indent=2)
            except ConnectError as e:
                result_output = str(e.message)
            except Exception as e:
                result_output = str(e)

            print(f"{CLI_GREEN}OUT{CLI_CLR}: {result_output[:200]}...")

            # Track tool call
            tool_calls.append(
                {
                    "iteration": iteration_name,
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "result": result_output[:200],
                }
            )

            conversation_log.append(
                {
                    "role": "tool",
                    "content": result_output,
                    "tool_call_id": iteration_name,
                }
            )

        # Log final result
        duration = time.time() - start_time
        self.trace_logger.log_agent_event(
            agent_name="orchestrator",
            event="task_complete",
            details={
                "outcome": outcome,
                "duration_seconds": duration,
                "iterations_used": iteration + 1,
                "tool_calls_count": len(tool_calls),
            },
        )

        return {
            "task_id": task_id,
            "status": "completed" if final_answer else "incomplete",
            "outcome": outcome,
            "final_answer": final_answer,
            "grounding_refs": grounding_refs,
            "completed_steps": completed_steps,
            "tool_calls": tool_calls,
            "iterations_used": iteration + 1,
            "duration_seconds": duration,
            "context": {
                "agents_md_path": context_result.agents_md_path,
                "referenced_files_count": len(context_result.referenced_files),
                "instruction_graph_nodes": len(
                    context_result.instruction_dependency_graph.nodes
                )
                if context_result.instruction_dependency_graph
                else 0,
            },
        }

    def _create_error_result(
        self, task_id: str, status: str, reason: str
    ) -> Dict[str, Any]:
        """Create error result."""
        return {
            "task_id": task_id,
            "status": status,
            "outcome": "OUTCOME_ERR_INTERNAL",
            "final_answer": f"Error: {reason}",
            "grounding_refs": [],
            "completed_steps": [],
            "tool_calls": [],
            "iterations_used": 0,
            "duration_seconds": 0,
            "context": {},
        }


def create_orchestrator(provider=None, system_prompt: str = None) -> Orchestrator:
    """Create an orchestrator instance."""
    return Orchestrator(provider=provider, system_prompt=system_prompt)
