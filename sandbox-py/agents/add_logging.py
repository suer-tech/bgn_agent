import sys

sys.path = [p for p in sys.path if "BitGN" not in p]

# ============================================================
# 1. Update orchestrator.py - add trace_logger and logging
# ============================================================
filepath = r"C:/Users/user2/Documents/BitGN/sandbox-py/orchestrator.py"
with open(filepath, "rb") as f:
    raw = f.read()

# Add import for LLMTraceLogger
old = b"from google.protobuf.json_format import MessageToDict"
new = b"from google.protobuf.json_format import MessageToDict\nfrom llm_logger import LLMTraceLogger"
raw = raw.replace(old, new)

# Add trace_logger parameter to __init__
old = b"""    def __init__(
        self,
        provider: LLMProvider,
        system_prompt: str = None,
    ):
        self.provider = provider

        # Initialize all agents with provider for LLM calls
        self.security_gate = SecurityGate(provider=provider)
        self.context_extractor = ContextExtractor(provider=provider)
        self.execution_agent = ExecutionAgent(provider, system_prompt)
        self.validation_agent = ValidationAgent(provider=provider)"""

new = b"""    def __init__(
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
        self.validation_agent = ValidationAgent(provider=provider)"""

raw = raw.replace(old, new)

# Add trace_logger to run() signature and set it
old = b'''    def run(
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

        print(f"\\n{CLI_BLUE}{'=' * 60}")
        print(f"ORCHESTRATOR STARTING - Task: {task_id}")
        print(f"{'=' * 60}{CLI_CLR}\\n")'''

new = b'''    def run(
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

        print(f"\\n{CLI_BLUE}{'=' * 60}")
        print(f"ORCHESTRATOR STARTING - Task: {task_id}")
        print(f"{'=' * 60}{CLI_CLR}\\n")'''

raw = raw.replace(old, new)

# Add logging for context extraction
old = b"""        # Phase 1: Context Extraction (LLM-based)
        print(f"{CLI_YELLOW}[1/4] Context Extraction (LLM)...{CLI_CLR}")
        context_result = self.context_extractor.extract_with_llm(harness_url, task_text)

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
            print(f"  Hierarchy: {context_result.instruction_hierarchy}")"""

new = b"""        # Phase 1: Context Extraction (LLM-based)
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
            print(f"  Hierarchy: {context_result.instruction_hierarchy}")"""

raw = raw.replace(old, new)

# Add logging for execution agent decision
old = b"""            # a) Get next step from Execution Agent
            next_step, is_complete = self.execution_agent.execute(
                task_text=task_text,
                context=task_context,
                conversation_log=conversation_log,
            )

            tool_name = next_step.function.__class__.__name__
            tool_args = next_step.function.model_dump()"""

new = b"""            # a) Get next step from Execution Agent
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
                )"""

raw = raw.replace(old, new)

# Add logging for security gate check
old = b"""            # b) Security Gate validates the tool call (hybrid: rules + LLM)
            security_check = self.security_gate.check_hybrid(
                tool_name=tool_name,
                arguments=tool_args,
                task_context=task_context,
                user_input=task_text,
            )

            if not security_check.allowed:
                print(f"{CLI_RED}SECURITY BLOCKED: {security_check.reason}{CLI_CLR}")"""

new = b"""            # b) Security Gate validates the tool call (hybrid: rules + LLM)
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
                print(f"{CLI_RED}SECURITY BLOCKED: {security_check.reason}{CLI_CLR}")"""

raw = raw.replace(old, new)

# Add logging for tool execution
old = b"""            print(f"  \\u2192 {tool_name}: {tool_args}")

            # Add to conversation"""

new = b"""            print(f"  \\u2192 {tool_name}: {tool_args}")

            if self.trace_logger:
                self.trace_logger.log_tool_event(
                    step_name=iteration_name,
                    tool_name=tool_name,
                    arguments=tool_args,
                    result="(pending)",
                    success=True,
                )

            # Add to conversation"""

raw = raw.replace(old, new)

# Add logging for tool execution result
old = b"""            # c) Execute the tool
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
                execution_error = str(e)"""

new = b"""            # c) Execute the tool
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
                )"""

raw = raw.replace(old, new)

# Add logging for validation
old = b"""            # d) Validation Agent validates result (hybrid: rules + LLM)
            validation = self.validation_agent.validate_hybrid(
                tool_name=tool_name,
                arguments=tool_args,
                result=result_output,
                is_error=execution_error is not None,
                task_text=task_text,
            )

            if not validation.valid:
                print(f"{CLI_RED}VALIDATION FAILED: {validation.errors}{CLI_CLR}")"""

new = b"""            # d) Validation Agent validates result (hybrid: rules + LLM)
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
                print(f"{CLI_RED}VALIDATION FAILED: {validation.errors}{CLI_CLR}")"""

raw = raw.replace(old, new)

# Add logging for task completion
old = b"""            # e) Check for completion
            if isinstance(next_step.function, ReportTaskCompletion):
                final_answer = next_step.function.answer
                grounding_refs = next_step.function.grounding_refs
                completed_steps = next_step.function.completed_steps_laconic

                if next_step.function.code == "completed":
                    print(f"\\n{CLI_GREEN}{'=' * 60}")
                    print(f"TASK COMPLETED: {task_id}")
                    print(f"{'=' * 60}{CLI_CLR}")
                    break"""

new = b"""            # e) Check for completion
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
                    print(f"\\n{CLI_GREEN}{'=' * 60}")
                    print(f"TASK COMPLETED: {task_id}")
                    print(f"{'=' * 60}{CLI_CLR}")
                    break"""

raw = raw.replace(old, new)

with open(filepath, "wb") as f:
    f.write(raw)

print("Updated orchestrator.py")

# Verify syntax
try:
    import ast

    ast.parse(raw.decode("utf-8"))
    print("Syntax OK!")
except SyntaxError as e:
    print(f"Error at line {e.lineno}: {e.msg}")
