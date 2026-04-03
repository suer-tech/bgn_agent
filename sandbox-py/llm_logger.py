import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class LLMTraceLogger:
    """Logs LLM prompts and responses to a daily trace file."""

    def __init__(
        self,
        log_dir: str = "logs",
        keep_last_only: bool = False,
        per_task_files: bool = False,
    ):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.log_path = self.log_dir / f"llm_trace_{date_str}.json"
        self.step_counter = 0
        self.task_id = ""
        self.task_text = ""
        self.keep_last_only = keep_last_only
        self.per_task_files = per_task_files
        self._last_exchange: Dict[str, Any] = {}
        self._agent_events: List[Dict[str, Any]] = []

    def set_task(self, task_id: str, task_text: str) -> None:
        """Set the current task context for logging."""
        self.task_id = task_id
        self.task_text = task_text
        self.step_counter = 0
        self._last_exchange = {}
        self._agent_events = []
        if self.per_task_files:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_task = re.sub(r"[^a-zA-Z0-9._-]", "_", task_id or "task")
            self.log_path = self.log_dir / f"{safe_task}_{ts}.json"

    def log_exchange(
        self,
        messages: List[Dict[str, Any]],
        response: str,
        step_name: str = "",
        elapsed_ms: int = 0,
    ) -> None:
        """Log a single LLM request/response exchange."""
        self.step_counter += 1
        if self.keep_last_only:
            self._last_exchange = {
                "step_name": step_name,
                "elapsed_ms": elapsed_ms,
                "messages": messages,
                "response": response,
            }
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80

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
                f.write(f"Task: {self.task_text}\n")
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
        if self.keep_last_only:
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80
        status = "SUCCESS" if success else "FAILED"

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"{separator}\n")
            f.write(f"Step: {step_name} (tool)\n")
            f.write(f"Timestamp: {ts}")
            if elapsed_ms:
                f.write(f"  Elapsed: {elapsed_ms} ms")
            f.write("\n")
            if self.task_id:
                f.write(f"Task ID: {self.task_id}\n")
            if self.task_text:
                f.write(f"Task: {self.task_text}\n")
            f.write(f"Status: {status}\n")
            f.write(f"{separator}\n\n")

            f.write("--- TOOL CALL ---\n\n")
            f.write(f"Tool: {tool_name}\n")
            f.write(
                f"Arguments:\n{json.dumps(arguments, indent=2, ensure_ascii=False)}\n\n"
            )

            f.write("--- TOOL RESULT ---\n\n")
            f.write(f"{result}\n\n")

    def log_agent_event(
        self,
        agent_name: str,
        event: str,
        details: Dict[str, Any],
    ) -> None:
        """Log higher-level agent events (security/context/validation/etc)."""
        payload = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "agent": agent_name,
            "event": event,
            "details": details,
        }
        if self.keep_last_only:
            self._agent_events.append(payload)
            return

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write("--- AGENT EVENT ---\n")
            f.write(f"{json.dumps(payload, indent=2, ensure_ascii=False)}\n\n")

    def flush_task_summary(
        self,
        score: float,
        score_detail: List[str],
        bitgn_eval: Dict[str, Any] | None = None,
    ) -> None:
        """Write one compact task summary containing only the last LLM exchange + BitGN evaluation."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"{separator}\n")
            f.write("Task Summary (compact)\n")
            f.write(f"Timestamp: {ts}\n")
            if self.task_id:
                f.write(f"Task ID: {self.task_id}\n")
            if self.task_text:
                f.write(f"Task: {self.task_text}\n")
            f.write(f"BitGN Score: {score:.2f}\n")
            f.write(f"{separator}\n\n")

            f.write("--- BITGN SCORE DETAIL ---\n\n")
            if score_detail:
                for line in score_detail:
                    f.write(f"- {line}\n")
            else:
                f.write("(empty)\n")
            f.write("\n")

            f.write("--- BITGN EVAL PAYLOAD ---\n\n")
            if bitgn_eval:
                f.write(f"{json.dumps(bitgn_eval, indent=2, ensure_ascii=False)}\n\n")
            else:
                f.write("(empty)\n\n")

            f.write("--- AGENT EVENTS ---\n\n")
            if self._agent_events:
                f.write(f"{json.dumps(self._agent_events, indent=2, ensure_ascii=False)}\n\n")
            else:
                f.write("(empty)\n\n")

            f.write("--- LAST PROMPT (messages sent to LLM) ---\n\n")
            messages = self._last_exchange.get("messages", [])
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

            f.write("--- LAST RESPONSE (received from LLM) ---\n\n")
            f.write(f"{self._last_exchange.get('response', '')}\n\n")


def create_logger() -> LLMTraceLogger:
    """Create an LLMTraceLogger instance."""
    return LLMTraceLogger()
