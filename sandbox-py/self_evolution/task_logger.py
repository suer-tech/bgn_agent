import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ERROR_CATEGORIES = {
    "security_denied": "Запрос отклонен без проверки прав доступа",
    "missed_instruction": "Пропущена инструкция из AGENTS.MD",
    "wrong_tool": "Выбран неправильный инструмент",
    "missing_step": "Пропущен обязательный шаг (discovery/planning)",
    "format_error": "Неверный формат ответа",
    "stuck_loop": "Зацикливание на одном действии",
    "phase_skip": "Пропущена фаза (discovery без tree)",
}


class ToolCall(BaseModel):
    """Single tool invocation."""

    iteration: str
    tool_name: str
    arguments: Dict[str, Any]
    reasoning: str = ""
    result_summary: str = ""
    result_success: bool = True


class TaskResult(BaseModel):
    """Result of running a single task."""

    task_id: str
    input: str
    output: str
    expected: str = ""
    status: Literal["passed", "failed", "error"] = "error"
    error_type: Optional[str] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    duration_ms: float = 0.0
    iterations_used: int = 0
    completed_steps: List[str] = Field(default_factory=list)
    grounding_refs: List[str] = Field(default_factory=list)
    score: Optional[float] = None
    score_detail: List[str] = Field(default_factory=list)
    trial_id: str = ""
    context_docs: Dict[str, str] = Field(default_factory=dict)
    llm_reasoning_trace: List[str] = Field(default_factory=list)
    trace_log_path: str = ""


class TaskLogger:
    """Logger for tracking all task results."""

    def __init__(self, log_dir: str = "task_logs"):
        self.log_dir = Path(__file__).parent.parent / log_dir
        self.log_dir.mkdir(exist_ok=self.log_dir.exists() or True)
        self.task_results: List[TaskResult] = []

    def start_session(self, session_name: str):
        """Start a new logging session."""
        self.session_name = session_name
        self.session_start = datetime.now()
        self.task_results = []

    def log_result(self, result: TaskResult):
        """Log a task result."""
        self.task_results.append(result)

    def save_session(self):
        """Save current session to disk."""
        if not hasattr(self, "session_name"):
            return

        session_file = (
            self.log_dir
            / f"session_{self.session_name}_{self.session_start.strftime('%Y%m%d_%H%M%S')}.json"
        )
        data = {
            "session_name": self.session_name,
            "started_at": self.session_start.isoformat(),
            "finished_at": datetime.now().isoformat(),
            "tasks": [
                {
                    "task_id": r.task_id,
                    "status": r.status,
                    "score": r.score,
                    "score_detail": r.score_detail,
                    "error_type": r.error_type,
                    "iterations_used": r.iterations_used,
                    "duration_ms": r.duration_ms,
                    "tool_calls": [
                        {
                            "iteration": tc.iteration,
                            "tool_name": tc.tool_name,
                            "arguments": tc.arguments,
                            "result_success": tc.result_success,
                        }
                        for tc in r.tool_calls
                    ],
                }
                for r in self.task_results
            ],
        }
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return session_file

    def get_failed_tasks(self) -> List[TaskResult]:
        """Get all failed tasks from current session."""
        return [r for r in self.task_results if r.status == "failed"]

    def get_error_tasks(self) -> List[TaskResult]:
        """Get all error tasks from current session."""
        return [r for r in self.task_results if r.status == "error"]

    def get_passed_count(self) -> int:
        """Get count of passed tasks."""
        return sum(1 for r in self.task_results if r.status == "passed")

    def get_failed_count(self) -> int:
        """Get count of failed tasks."""
        return sum(1 for r in self.task_results if r.status == "failed")

    def get_score(self) -> float:
        """Calculate current score (passed / total)."""
        if not self.task_results:
            return 0.0
        return self.get_passed_count() / len(self.task_results)


# Global instance
task_logger = TaskLogger()


def format_task_summary(results: List[TaskResult], max_tasks: int = 30) -> str:
    """Format task results for Analyzer prompt."""
    lines = []

    # Show only failed tasks
    failed = [r for r in results if r.status != "passed"]

    if not failed:
        return "All tasks passed!"

    lines.append(f"=== FAILED TASKS ({len(failed)}/{len(results)}) ===\n")

    for result in failed[:max_tasks]:
        lines.append(f"## Task: {result.task_id}")
        lines.append(f"Input: {result.input[:200]}...")
        lines.append(f"Output: {result.output[:300]}")
        lines.append(f"Expected: {result.expected[:200]}")
        lines.append(f"Error Type: {result.error_type or 'unknown'}")
        if result.score is not None:
            lines.append(f"Score: {result.score:.2f}")
        if result.score_detail:
            lines.append("Score detail:")
            for d in result.score_detail[:5]:
                lines.append(f"  - {d}")
        lines.append(f"Iterations: {result.iterations_used}")

        if result.tool_calls:
            lines.append("Tool calls:")
            for tc in result.tool_calls:
                lines.append(
                    f"  - {tc.iteration}: {tc.tool_name}({tc.arguments}) -> {tc.result_summary[:100]}"
                )

        lines.append("")

    if len(failed) > max_tasks:
        lines.append(f"... and {len(failed) - max_tasks} more failed tasks")

    return "\n".join(lines)
