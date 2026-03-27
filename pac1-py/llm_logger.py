import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class LLMTraceLogger:
    """Logs LLM prompts and responses to a daily trace file."""

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.log_path = self.log_dir / f"llm_trace_{date_str}.json"
        self.step_counter = 0
        self.task_id = ""
        self.task_text = ""

    def set_task(self, task_id: str, task_text: str) -> None:
        """Set the current task context for logging."""
        self.task_id = task_id
        self.task_text = task_text
        self.step_counter = 0

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
                    import json

                    f.write(
                        f"Tool calls:\n{json.dumps(tool_calls, indent=2, ensure_ascii=False)}\n"
                    )
                if content:
                    f.write(f"{content}\n")
                f.write("\n")

            f.write("--- RESPONSE (received from LLM) ---\n\n")
            f.write(f"{response}\n\n")


def create_logger() -> LLMTraceLogger:
    """Create an LLMTraceLogger instance."""
    return LLMTraceLogger()
