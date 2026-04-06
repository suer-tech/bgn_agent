"""Tool Executor — executes tool calls with hardcoded guardrails.

Does NOT send AnswerRequest — only the orchestrator does that.
Uses pcm_helpers.dispatch_tool() for actual PCM communication.
"""

import time
from typing import Optional

from agents.pcm_helpers import dispatch_tool
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from llm_logger import LLMTraceLogger


# Maximum result size before truncation
MAX_RESULT_LENGTH = 10000

# Read-only paths — writing/deleting is blocked
READ_ONLY_PATHS = {"/AGENTS.md", "AGENTS.md", "AGENTS.MD"}
READ_ONLY_PREFIXES = ["/01_capture/", "01_capture/"]

# Dangerous tools that modify data
WRITE_TOOLS = {"write", "delete", "move", "mkdir"}


def execute_tool(
    tool_call: dict,
    vm_client: PcmRuntimeClientSync,
    trace_logger: Optional[LLMTraceLogger] = None,
    step_name: str = "",
) -> str:
    """Execute a tool call with security guardrails and truncation.

    Guardrails:
    1. Path traversal (..) → block
    2. Write/delete to read-only files → block
    3. Result too large → truncation

    Args:
        tool_call: dict with "name" and "arguments" keys.
        vm_client: PCM runtime client.
        trace_logger: Optional logger.
        step_name: Current step name for logging.

    Returns:
        String result (success or error message).
    """
    name = tool_call.get("name", "")
    args = tool_call.get("arguments", {})
    start_time = time.time()

    # ----- Guardrail 1: Path traversal -----
    for key in ("path", "from_name", "to_name", "root"):
        path_val = args.get(key, "")
        if ".." in path_val:
            result = f"SECURITY BLOCK: Path traversal detected in '{key}': {path_val}"
            _log_tool_event(trace_logger, step_name, name, args, result, False, start_time)
            return result

    # ----- Guardrail 2: Read-only protection -----
    if name in WRITE_TOOLS:
        target_path = args.get("path", "") or args.get("to_name", "")

        # Check exact matches
        for ro_path in READ_ONLY_PATHS:
            if ro_path.lower() in target_path.lower():
                result = f"SECURITY BLOCK: File is read-only: {target_path}"
                _log_tool_event(trace_logger, step_name, name, args, result, False, start_time)
                return result

        # Check prefix matches
        for prefix in READ_ONLY_PREFIXES:
            if target_path.lower().startswith(prefix.lower()):
                result = f"SECURITY BLOCK: Directory is read-only: {target_path}"
                _log_tool_event(trace_logger, step_name, name, args, result, False, start_time)
                return result

    # ----- Execute the tool -----
    result = dispatch_tool(vm_client, tool_call)

    # ----- Guardrail 3: Truncation -----
    if len(result) > MAX_RESULT_LENGTH:
        result = result[:MAX_RESULT_LENGTH] + \
            "\n...[TRUNCATED. Result too large. Please refine your search query.]"

    _log_tool_event(trace_logger, step_name, name, args, result, True, start_time)
    return result


def _log_tool_event(
    trace_logger: Optional[LLMTraceLogger],
    step_name: str,
    tool_name: str,
    arguments: dict,
    result: str,
    success: bool,
    start_time: float,
) -> None:
    """Log tool execution to trace logger."""
    if not trace_logger:
        return

    elapsed_ms = int((time.time() - start_time) * 1000)
    trace_logger.log_tool_event(
        step_name=step_name,
        tool_name=tool_name,
        arguments=arguments,
        result=result,
        success=success,
        elapsed_ms=elapsed_ms,
    )
