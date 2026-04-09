import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from self_evolution.task_logger import TaskResult, format_task_summary


ANALYZER_PROMPT = """Ты — Analyzer Agent. Твоя задача анализировать логи выполнения задач и находить паттерны ошибок.

Анализируя фейлы, ищи повторяющиеся паттерны, а не отдельные инциденты.
Для каждого паттерна сформулируй гипотезу почему это происходит.

## Категории ошибок:
- security_denied: Запрос отклонен без проверки прав доступа
- missed_instruction: Пропущена инструкция из AGENTS.MD  
- wrong_tool: Выбран неправильный инструмент
- missing_step: Пропущен обязательный шаг (discovery/planning)
- format_error: Неверный формат ответа
- stuck_loop: Зацикливание на одном действии
- phase_skip: Пропущена фаза (discovery без tree)

## Твоя задача:
1. Проанализируй все failed tasks
2. Найди повторяющиеся паттерны (минимум 2 задачи с похожей проблемой)
3. Для каждого паттерна сформулируй гипотезу почему это происходит
4. Предложи конкретное исправление для system prompt

## Верни JSON в формате:
{
  "failure_patterns": [
    {
      "pattern_id": "pattern_1",
      "description": "Agent игнорирует правило 'never delete protected files'",
      "hypothesis": "Правило недостаточно эксплицитно в system prompt",
      "occurs_in_tasks": ["task_1", "task_5", "task_12"],
      "suggested_fix": "Добавить в system prompt явный запрет на удаление PROTECTED_FILES с примером"
    }
  ],
  "overall_observation": "Главная проблема — недостаточная конкретизация правил"
}

Если нет паттернов (все фейлы уникальны), верни:
{"failure_patterns": [], "overall_observation": "No clear patterns found"}
"""


class FailurePattern(BaseModel):
    pattern_id: str
    description: str
    hypothesis: str
    occurs_in_tasks: List[str] = Field(default_factory=list)
    suggested_fix: str


class AnalyzerResponse(BaseModel):
    failure_patterns: List[FailurePattern] = Field(default_factory=list)
    overall_observation: str


def analyze_failures(
    task_results: List[TaskResult],
    provider: Any,  # LLMProvider
    max_tasks: int = 30,
) -> List[FailurePattern]:
    """
    Analyze failed tasks and return failure patterns.
    """
    # Filter failed tasks
    failed = [r for r in task_results if r.status == "failed"]

    if not failed:
        return []

    # Build summary for LLM
    summary = format_task_summary(task_results, max_tasks)

    prompt = f"""{ANALYZER_PROMPT}

## Данные задач:
{summary}

Проанализируй и верни JSON с паттернами ошибок.
"""

    try:
        response = provider.complete([{"role": "user", "content": prompt}])

        # Try to parse JSON from response
        content = response.content if hasattr(response, "content") else str(response)

        # Extract JSON from response
        json_start = content.find("{")
        json_end = content.rfind("}") + 1

        if json_start >= 0 and json_end > json_start:
            json_str = content[json_start:json_end]
            data = json.loads(json_str)

            patterns = []
            for p_data in data.get("failure_patterns", []):
                if isinstance(p_data, dict):
                    patterns.append(FailurePattern(**p_data))

            return patterns
        else:
            return []

    except Exception as e:
        print(f"Analyzer error: {e}")
        return []


def format_suggestions(patterns: List[FailurePattern]) -> str:
    """Format failure patterns for Versioner prompt."""
    if not patterns:
        return "No specific patterns identified."

    lines = ["=== Предложения от Analyzer ==="]

    for i, p in enumerate(patterns, 1):
        lines.append(f"\n## Pattern {i}: {p.description}")
        lines.append(f"Hypothesis: {p.hypothesis}")
        lines.append(f"Occurs in: {', '.join(p.occurs_in_tasks)}")
        lines.append(f"Suggested fix: {p.suggested_fix}")

    return "\n".join(lines)
