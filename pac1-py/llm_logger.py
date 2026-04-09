import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class LLMTraceLogger:
    """Logs LLM prompts and responses to per-task trace files.

    Process-safe: each task gets its own log files, no shared state.
    Daily log is also per-task to avoid write collisions in parallel mode.
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.step_counter = 0
        self.task_id = ""
        self.task_text = ""
        self._agent_events: List[Dict[str, Any]] = []
        # Per-task trace log (set in set_task)
        self.log_path = None
        self.task_log_path = None

    def set_task(self, task_id: str, task_text: str) -> None:
        """Set the current task context for logging."""
        self.task_id = task_id
        self.task_text = task_text
        self.step_counter = 0
        self._agent_events = []

        # Create per-task log files with unique names
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_task = "".join(c if c.isalnum() or c in "._-" else "_" for c in task_id)

        # Daily trace log — per-task to avoid collisions
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.log_path = self.log_dir / f"llm_trace_{date_str}_{safe_task}.log"

        # Structured per-task JSON log
        self.task_log_path = self.log_dir / f"{safe_task}_{ts}.json"

    def _safe_append(self, path: Path, text: str) -> None:
        """Append text to a file. Each task has its own file, so no locking needed."""
        if path is None:
            return
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass

    def _safe_update_json(self, update_fn) -> None:
        """Read-modify-write per-task JSON log. Safe because each task has its own file."""
        if self.task_log_path is None:
            return
        try:
            if self.task_log_path.exists():
                with open(self.task_log_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {
                    "task_id": self.task_id,
                    "task_text": self.task_text,
                    "entries": [],
                    "agent_events": [],
                    "tool_events": [],
                }
            update_fn(data)
            with open(self.task_log_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def log_exchange(
        self,
        messages: List[Dict[str, Any]],
        response: str,
        step_name: str = "",
        elapsed_ms: int = 0,
    ) -> None:
        """Log a single LLM request/response exchange."""
        self.step_counter += 1
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80

        log_entry = {
            "step": self.step_counter,
            "step_name": step_name,
            "timestamp": ts,
            "elapsed_ms": elapsed_ms,
            "task_id": self.task_id,
            "task_text": self.task_text[:200] if self.task_text else "",
            "messages": messages,
            "response": response,
        }

        # Write to per-task trace log (append)
        lines = []
        lines.append(f"{separator}\n")
        lines.append(f"Step: {self.step_counter}")
        if step_name:
            lines.append(f" ({step_name})")
        lines.append(f"\nTimestamp: {ts}")
        if elapsed_ms:
            lines.append(f"  Elapsed: {elapsed_ms} ms")
        lines.append("\n")
        if self.task_id:
            lines.append(f"Task ID: {self.task_id}\n")
        if self.task_text:
            lines.append(f"Task: {self.task_text[:100]}...\n")
        lines.append(f"{separator}\n\n")

        lines.append("--- PROMPT (messages sent to LLM) ---\n\n")
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls")
            lines.append(f"[{role.upper()}]\n")
            if tool_calls:
                lines.append(f"Tool calls:\n{json.dumps(tool_calls, indent=2, ensure_ascii=False)}\n")
            if content:
                lines.append(f"{content}\n")
            lines.append("\n")

        lines.append("--- RESPONSE (received from LLM) ---\n\n")
        lines.append(f"{response}\n\n")

        self._safe_append(self.log_path, "".join(lines))

        # Write to per-task JSON log
        def update(data):
            data.setdefault("entries", []).append(log_entry)
        self._safe_update_json(update)

    def log_agent_event(
        self,
        agent_name: str,
        event: str,
        details: Dict[str, Any],
    ) -> None:
        """Log agent events (security checks, context extraction, etc.)."""
        payload = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "agent": agent_name,
            "event": event,
            "details": details,
        }
        self._agent_events.append(payload)

        # Write to per-task trace log
        text = "--- AGENT EVENT ---\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n\n"
        self._safe_append(self.log_path, text)

        # Write to per-task JSON log
        def update(data):
            data.setdefault("agent_events", []).append(payload)
        self._safe_update_json(update)

    def log_tool_event(
        self,
        step_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str,
        success: bool = True,
        elapsed_ms: int = 0,
    ) -> None:
        """Log a single tool call and its result."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80
        status = "SUCCESS" if success else "FAILED"

        payload = {
            "timestamp": ts,
            "step_name": step_name,
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result[:500],
            "success": success,
            "elapsed_ms": elapsed_ms,
        }

        lines = []
        lines.append(f"{separator}\n")
        lines.append(f"Step: {step_name} (tool)\n")
        lines.append(f"Timestamp: {ts}")
        if elapsed_ms:
            lines.append(f"  Elapsed: {elapsed_ms} ms")
        lines.append("\n")
        if self.task_id:
            lines.append(f"Task ID: {self.task_id}\n")
        lines.append(f"Status: {status}\n")
        lines.append(f"{separator}\n\n")
        lines.append("--- TOOL CALL ---\n\n")
        lines.append(f"Tool: {tool_name}\n")
        lines.append(f"Arguments:\n{json.dumps(arguments, indent=2, ensure_ascii=False)}\n\n")
        lines.append("--- TOOL RESULT ---\n\n")
        lines.append(f"{result}\n\n")

        self._safe_append(self.log_path, "".join(lines))

        # Write to per-task JSON log
        def update(data):
            data.setdefault("tool_events", []).append(payload)
        self._safe_update_json(update)

    def write_task_summary(
        self,
        score: float = None,
        score_detail: str = "",
        error: str = "",
    ) -> None:
        """Write a human-readable task summary log."""
        if self.task_log_path is None or not self.task_log_path.exists():
            return

        try:
            with open(self.task_log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        entries = data.get("entries", [])
        agent_events = data.get("agent_events", [])

        summary_lines = []
        separator = "=" * 80

        # Header
        summary_lines.append(separator)
        summary_lines.append(f"Task: {self.task_id}")
        summary_lines.append(f"User Prompt: {self.task_text}")
        summary_lines.append(separator)
        summary_lines.append("")

        # Phase 1: Context Extractor events
        ctx_events = [e for e in agent_events if e.get("agent") == "context_extractor"]
        if ctx_events:
            summary_lines.append("## CONTEXT EXTRACTOR")
            summary_lines.append(separator)
            for evt in ctx_events:
                event = evt.get("event", "")
                details = evt.get("details", {})
                ts = evt.get("timestamp", "")
                summary_lines.append(f"[{ts}] {event}")
                if details:
                    for k, v in details.items():
                        val = str(v)[:300] if v is not None else ""
                        if val:
                            summary_lines.append(f"  {k}: {val}")
                summary_lines.append("")

        # Phase 2: Security Gate events
        sec_events = [e for e in agent_events if e.get("agent") == "security_gate"]
        if sec_events:
            summary_lines.append("## SECURITY GATE")
            summary_lines.append(separator)
            for evt in sec_events:
                event = evt.get("event", "")
                details = evt.get("details", {})
                ts = evt.get("timestamp", "")
                summary_lines.append(f"[{ts}] {event}")
                if details:
                    for k, v in details.items():
                        val = str(v)[:300] if v is not None else ""
                        if val:
                            summary_lines.append(f"  {k}: {val}")
                summary_lines.append("")

        # Phase 3: Execution Agent steps
        exec_events = [e for e in agent_events if e.get("agent") == "execution_agent"]
        if entries or exec_events:
            summary_lines.append("## EXECUTION AGENT")
            summary_lines.append(separator)

            step_counter = 0
            for entry in entries:
                step_counter += 1
                step_name = entry.get("step_name", "")
                messages = entry.get("messages", [])
                response = entry.get("response", "")

                if response == "(calling LLM...)":
                    continue

                tool_call_name = ""
                tool_call_args = ""
                for msg in messages:
                    if msg.get("tool_calls"):
                        tc = msg["tool_calls"][0]["function"]
                        tool_call_name = tc.get("name", "")
                        tool_call_args = tc.get("arguments", "")[:200]

                tool_result = ""
                for msg in messages:
                    if msg.get("role") == "tool":
                        tool_result = msg.get("content", "")[:200]

                llm_action = ""
                llm_tool = ""
                llm_args = ""
                if response and response != "(calling LLM...)":
                    try:
                        resp_json = json.loads(response)
                        llm_action = resp_json.get("current_state", resp_json.get("reasoning", ""))[:300]
                        func = resp_json.get("function", {})
                        if func:
                            llm_tool = func.get("tool", "")
                            llm_args = json.dumps(func, ensure_ascii=False)[:200]
                    except (json.JSONDecodeError, TypeError):
                        pass

                summary_lines.append(f"--- Step {step_counter} ---")
                summary_lines.append("Agent: execution_agent")
                if llm_action:
                    summary_lines.append(f"Reasoning: {llm_action}")
                if tool_call_name or llm_tool:
                    summary_lines.append(f"Tool: {llm_tool or tool_call_name}")
                    summary_lines.append(f"Args: {llm_args or tool_call_args}")
                if tool_result:
                    summary_lines.append(f"Result: {tool_result}")
                summary_lines.append("")

            for evt in exec_events:
                event = evt.get("event", "")
                details = evt.get("details", {})
                ts = evt.get("timestamp", "")
                if "decision" in event or "completed" in event or "error" in event:
                    summary_lines.append(f"[{ts}] {event}")
                    if details:
                        for k, v in details.items():
                            val = str(v)[:300] if v is not None else ""
                            if val:
                                summary_lines.append(f"  {k}: {val}")
                    summary_lines.append("")

        # Result
        summary_lines.append(separator)
        summary_lines.append("RESULT")
        summary_lines.append(separator)
        if score is not None:
            summary_lines.append(f"Score: {score:.2f}")
        if score_detail:
            summary_lines.append(f"Detail: {score_detail}")
        if error:
            summary_lines.append(f"Error: {error}")
        summary_lines.append("")

        # Write summary to file
        ts = self.task_log_path.stem
        summary_path = self.log_dir / f"{ts}_summary.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(summary_lines))


def create_logger() -> LLMTraceLogger:
    """Create an LLMTraceLogger instance."""
    return LLMTraceLogger()
