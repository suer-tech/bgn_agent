import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class LLMTraceLogger:
    """Logs LLM prompts and responses to a daily trace file.
    Enhanced for multi-agent logging.
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.log_path = self.log_dir / f"llm_trace_{date_str}.json"
        self.step_counter = 0
        self.task_id = ""
        self.task_text = ""
        self._agent_events: List[Dict[str, Any]] = []

    def set_task(self, task_id: str, task_text: str) -> None:
        """Set the current task context for logging."""
        self.task_id = task_id
        self.task_text = task_text
        self.step_counter = 0
        self._agent_events = []

        # Create per-task log file
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_task = "".join(c if c.isalnum() or c in "._-" else "_" for c in task_id)
        self.task_log_path = self.log_dir / f"{safe_task}_{ts}.json"
        self.task_summary_path = self.log_dir / "task_summary.txt"

    def append_task_summary(self, title: str, details: Dict[str, Any]) -> None:
        """Append a compact audit entry to task_summary.txt."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[{ts}] {title}"]
        if self.task_id:
            lines.append(f"task_id: {self.task_id}")
        for key, value in details.items():
            if value is None:
                continue
            lines.append(f"{key}: {value}")
        lines.append("")
        with open(self.task_summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

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

        # Write to daily log
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"{separator}\n")
            f.write(f"Step: {self.step_counter}")
            if step_name:
                f.write(f" ({step_name})")
            f.write(f"\nTimestamp: {ts}")
            if elapsed_ms:
                f.write(f"  Elapsed: {elapsed_ms} ms")
            f.write("\n")
            if self.task_id:
                f.write(f"Task ID: {self.task_id}\n")
            if self.task_text:
                f.write(f"Task: {self.task_text[:100]}...\n")
            f.write(f"{separator}\n\n")

            f.write("--- PROMPT (messages sent to LLM) ---\n\n")
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")

                f.write(f"[{role.upper()}]\n")
                if tool_calls:
                    f.write(
                        f"Tool calls:\n{json.dumps(tool_calls, indent=2, ensure_ascii=False)}\n"
                    )
                if content:
                    f.write(f"{content}\n")
                f.write("\n")

            f.write("--- RESPONSE (received from LLM) ---\n\n")
            f.write(f"{response}\n\n")

        # Write to per-task log
        if hasattr(self, "task_log_path"):
            self._append_task_log(log_entry)

    def _append_task_log(self, entry: Dict[str, Any]) -> None:
        """Append entry to per-task log file."""
        try:
            data = self._read_task_log_data()
            data["entries"].append(entry)
            self._write_task_log_data(data)
        except Exception:
            pass  # Silently fail for logging

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

        # Write to daily log
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write("--- AGENT EVENT ---\n")
            f.write(f"{json.dumps(payload, indent=2, ensure_ascii=False)}\n\n")

        # Write to per-task log
        if hasattr(self, "task_log_path"):
            try:
                data = self._read_task_log_data()
                if "agent_events" not in data:
                    data["agent_events"] = []
                data["agent_events"].append(payload)
                self._write_task_log_data(data)
            except Exception:
                pass

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

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"{separator}\n")
            f.write(f"Step: {step_name} (tool)\n")
            f.write(f"Timestamp: {ts}")
            if elapsed_ms:
                f.write(f"  Elapsed: {elapsed_ms} ms")
            f.write("\n")
            if self.task_id:
                f.write(f"Task ID: {self.task_id}\n")
            f.write(f"Status: {status}\n")
            f.write(f"{separator}\n\n")

            f.write("--- TOOL CALL ---\n\n")
            f.write(f"Tool: {tool_name}\n")
            f.write(
                f"Arguments:\n{json.dumps(arguments, indent=2, ensure_ascii=False)}\n\n"
            )

            f.write("--- TOOL RESULT ---\n\n")
            f.write(f"{result}\n\n")

        # Write to per-task log
        if hasattr(self, "task_log_path"):
            try:
                data = self._read_task_log_data()
                if "tool_events" not in data:
                    data["tool_events"] = []
                data["tool_events"].append(payload)
                self._write_task_log_data(data)
            except Exception:
                pass

    def log_step_boundary(
        self,
        step_name: str,
        boundary: str,
        details: Dict[str, Any],
    ) -> None:
        self.log_agent_event(
            agent_name="orchestrator",
            event=f"step_{boundary}",
            details={"step_name": step_name, **details},
        )

    def log_decision(
        self,
        step_name: str,
        stage: str,
        outcome: str,
        reason: str,
        details: Dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "step_name": step_name,
            "stage": stage,
            "outcome": outcome,
            "reason": reason,
        }
        if details:
            payload["details"] = details
        self.log_agent_event(
            agent_name="decision_engine",
            event="decision_rationale",
            details=payload,
        )
        self.append_task_summary(
            title="decision_rationale",
            details=payload,
        )

    def log_state_diff(
        self,
        step_name: str,
        state_name: str,
        before: Any,
        after: Any,
    ) -> None:
        if before == after:
            return
        payload = {
            "step_name": step_name,
            "state_name": state_name,
            "before": self._truncate_value(before),
            "after": self._truncate_value(after),
        }
        self.log_agent_event(
            agent_name="state_tracker",
            event="state_diff",
            details=payload,
        )

    def log_completion_decision(
        self,
        outcome: str,
        message: str,
        completed_steps: List[str],
        grounding_refs: List[str],
    ) -> None:
        payload = {
            "outcome": outcome,
            "message": message[:500],
            "completed_steps": completed_steps,
            "grounding_refs": grounding_refs,
        }
        self.log_agent_event(
            agent_name="orchestrator",
            event="completion_decision",
            details=payload,
        )
        self.append_task_summary(
            title="completion_decision",
            details=payload,
        )

    def _read_task_log_data(self) -> Dict[str, Any]:
        if self.task_log_path.exists():
            with open(self.task_log_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "task_id": self.task_id,
            "task_text": self.task_text,
            "entries": [],
            "agent_events": [],
            "tool_events": [],
        }

    def _write_task_log_data(self, data: Dict[str, Any]) -> None:
        with open(self.task_log_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _truncate_value(self, value: Any, limit: int = 1200) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return text[:limit]


    def write_task_summary(
        self,
        score: float = None,
        score_detail: str = "",
        error: str = "",
    ) -> None:
        """Write a human-readable task summary log."""
        if not hasattr(self, "task_log_path") or not self.task_log_path.exists():
            return

        try:
            with open(self.task_log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
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
        ctx_events = [
            e
            for e in agent_events
            if e.get("agent") in {"context_extractor", "bootstrap_node"}
        ]
        if ctx_events:
            summary_lines.append("## BOOTSTRAP")
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
        sec_events = [
            e
            for e in agent_events
            if e.get("agent") in {"security_gate", "security_node", "triage_node"}
        ]
        if sec_events:
            summary_lines.append("## SECURITY")
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
