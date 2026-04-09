import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    is_safe: bool
    risk_level: str  # low, medium, high
    warnings: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class OverfittingGuard:
    """Guard against prompt overfitting."""
    
    OVERSPECIFIC_PATTERNS = [
        (r"never delete.*backup", "Tooo specific"),
        (r"always.*tree.*first", "Rigid order"),
        (r"forbidden.*\d+", "Hardcoded numbers"),
        (r"only.*task_\d+", "Task-specific"),
    ]
    
    CORE_PRINCIPLES = [
        "instruction hierarchy",
        "discovery planning execution",
        "security validation",
        "grounding references",
    ]
    
    def __init__(
        self,
        holdout_ratio: float = 0.2,
        min_holdout_score: float = 0.3,
    ):
        self.holdout_ratio = holdout_ratio
        self.min_holdout_score = min_holdout_score
        self.train_history: List[float] = []
        self.holdout_history: List[float] = []
    
    def split_train_holdout(
        self, tasks: List[Dict[str, str]]
    ) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """Split tasks into train and holdout sets."""
        if not tasks:
            return [], []
        
        n = len(tasks)
        n_holdout = max(1, int(n * self.holdout_ratio))
        
        train_tasks = []
        holdout_tasks = []
        
        for i, task in enumerate(tasks):
            if (i + 1) % (n // n_holdout + 1) == 0:
                holdout_tasks.append(task)
            else:
                train_tasks.append(task)
        
        return train_tasks, holdout_tasks
    
    def validate_new_rules(self, new_prompt: str, old_prompt: str) -> ValidationResult:
        """Validate that new rules aren't overspecific."""
        warnings = []
        recommendations = []
        
        new_content = new_prompt[len(old_prompt):] if new_prompt.startswith(old_prompt) else new_prompt
        
        for pattern, desc in self.OVERSPECIFIC_PATTERNS:
            if re.search(pattern, new_content, re.IGNORECASE):
                warnings.append(f"Overspecific pattern: {desc}")
        
        new_rules_count = len([l for l in new_content.split('\n') if l.strip().startswith(('-', '*'))])
        if new_rules_count > 3:
            warnings.append(f"Too many new rules at once ({new_rules_count}) - risk of overfitting")
        
        new_lower = new_prompt.lower()
        missing_core = [p for p in self.CORE_PRINCIPLES if p not in new_lower]
        
        if missing_core:
            warnings.append(f"Core principles missing: {', '.join(missing_core)}")
        
        if len(warnings) >= 2:
            risk_level = "high"
        elif warnings:
            risk_level = "medium"
        else:
            risk_level = "low"
        
        if missing_core:
            risk_level = "high"
            recommendations.append("CRITICAL: Restore core principles")
        
        is_safe = risk_level != "high"
        
        return ValidationResult(
            is_safe=is_safe,
            risk_level=risk_level,
            warnings=warnings,
            recommendations=recommendations,
        )
    
    def should_stop(
        self,
        generation: int,
        train_score: float,
        holdout_score: Optional[float],
    ) -> tuple[bool, str]:
        """Determine if training should stop due to overfitting."""
        self.train_history.append(train_score)
        if holdout_score is not None:
            self.holdout_history.append(holdout_score)
        
        if generation >= 20:
            return True, "max_generations"
        
        if len(self.train_history) < 2:
            return False, ""
        
        if holdout_score is not None and holdout_score < self.min_holdout_score:
            return True, f"holdout_low ({holdout_score:.2f})"
        
        if holdout_score is not None and len(self.holdout_history) >= 2:
            train_delta = self.train_history[-1] - self.train_history[-2]
            holdout_delta = self.holdout_history[-1] - self.holdout_history[-2]
            
            if train_delta > 0.05 and holdout_delta < -0.05:
                return True, "overfitting_detected"
        
        if len(self.train_history) >= 5:
            recent = self.train_history[-5:]
            if max(recent) - min(recent) < 0.01:
                return True, "plateau_reached"
        
        return False, ""
    
    def reset(self):
        """Reset history."""
        self.train_history = []
        self.holdout_history = []


def format_validation_report(result: ValidationResult) -> str:
    """Format validation result."""
    lines = [
        f"Risk Level: {result.risk_level.upper()}",
    ]
    
    if result.warnings:
        lines.append("Warnings:")
        for w in result.warnings:
            lines.append(f"  - {w}")
    
    if result.recommendations:
        lines.append("Recommendations:")
        for r in result.recommendations:
            lines.append(f"  -> {r}")
    
    return "\n".join(lines)
