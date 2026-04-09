import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GenerationLog(BaseModel):
    """Log entry for one generation of evolution."""

    generation: int
    version_id: int
    parent_version_id: Optional[int]

    # Scores
    train_score: float
    holdout_score: Optional[float] = None

    # What analyzer found
    failure_patterns_found: List[str] = Field(default_factory=list)
    analyzer_summary: str = ""

    # What versioner changed
    changes_summary: str = ""
    rationale: str = ""

    # Timing
    duration_seconds: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class EvolutionLogger:
    """Logger for tracking full evolution process."""

    def __init__(self, log_dir: str = "evolution_logs"):
        self.log_dir = Path(__file__).parent.parent / log_dir
        self.log_dir.mkdir(exist_ok=True)
        self.logs: List[GenerationLog] = []
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def start_session(self, model_name: str, task_count: int):
        """Start a new evolution session."""
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.logs = []

        meta_file = self.log_dir / f"session_{self.session_id}_meta.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "session_id": self.session_id,
                    "model": model_name,
                    "task_count": task_count,
                    "started_at": datetime.now().isoformat(),
                },
                f,
                indent=2,
            )

    def log_generation(self, gen_log: GenerationLog):
        """Log a generation."""
        self.logs.append(gen_log)

        # Save to file immediately
        log_file = (
            self.log_dir / f"session_{self.session_id}_gen{gen_log.generation:02d}.json"
        )
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(gen_log.model_dump(), f, indent=2, ensure_ascii=False)

    def finish_session(self, best_version_id: int, best_score: float):
        """Finish session and save summary."""
        summary_file = self.log_dir / f"session_{self.session_id}_summary.json"

        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "session_id": self.session_id,
                    "finished_at": datetime.now().isoformat(),
                    "total_generations": len(self.logs),
                    "best_version_id": best_version_id,
                    "best_score": best_score,
                    "generations": [
                        {
                            "gen": l.generation,
                            "version": l.version_id,
                            "train_score": l.train_score,
                            "holdout_score": l.holdout_score,
                            "changes": l.changes_summary[:200],
                        }
                        for l in self.logs
                    ],
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

        print(f"\n📝 Evolution logs saved to: {self.log_dir}/")
        return summary_file

    def get_summary(self) -> str:
        """Get printable summary."""
        if not self.logs:
            return "No logs yet"

        lines = [
            f"{'=' * 60}",
            "EVOLUTION LOG SUMMARY",
            f"{'=' * 60}",
        ]

        for l in self.logs:
            h = f", H:{l.holdout_score:.2f}" if l.holdout_score else ""
            lines.append(
                f"Gen {l.generation}: v{l.version_id} | "
                f"Train: {l.train_score:.2f}{h} | "
                f"{l.changes_summary[:50]}..."
            )

        lines.append(f"{'=' * 60}")
        return "\n".join(lines)


# Global logger instance
evolution_logger = EvolutionLogger()


def get_log_path() -> Path:
    """Get path to evolution logs."""
    return Path(__file__).parent.parent / "evolution_logs"
