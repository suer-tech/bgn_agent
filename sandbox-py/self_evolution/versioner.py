import json
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from self_evolution.prompt_store import PromptVersion


VERSIONER_PROMPT = """Ты — Versioner Agent. Твоя задача — создавать новые версии system prompt на основе предложений от Analyzer.

## Твоя работа:
1. Прочитай текущий system prompt
2. Прочитай предложения от Analyzer
3. Реши какие изменения необходимы
4. Создай НОВУЮ версию system prompt которая исправляет эти проблемы

## ПРАВИЛА:
- НЕ добавляй новые правила которые не относятся к проблемам из Analyzer
- Сохраняй основную структуру и формат system prompt
- Делай изменения МИНИМАЛЬНЫМИ — только то что нужно для исправления
- Добавляй комментарии в stylle "FIXED #N: причина"
- НЕ удаляй существующие правила которые работают

## Верни JSON:
{{
  "new_system_prompt": "полный текст нового system prompt",
  "changes_summary": "краткое описание что изменилось",
  "rationale": "почему именно эти изменения должны помочь"
}}

Важно: Верни ТОЛЬКО JSON, без markdown форматирования.
"""


class VersionerResponse(BaseModel):
    new_system_prompt: str
    changes_summary: str
    rationale: str


def create_new_version(
    current_prompt: str,
    analyzer_suggestions: str,
    provider: Any,  # LLMProvider
    parent_version: int,
) -> PromptVersion:
    """
    Create new version of system prompt based on analyzer suggestions.
    """
    prompt = f"""{VERSIONER_PROMPT}

## Текущий system prompt:
---
{current_prompt}
---

## Предложения от Analyzer:
---
{analyzer_suggestions}
---

Создай новую версию.
"""

    try:
        response = provider.complete([{"role": "user", "content": prompt}])

        # Extract JSON from response
        content = response.content if hasattr(response, "content") else str(response)

        # Find JSON
        json_start = content.find("{")
        json_end = content.rfind("}") + 1

        if json_start >= 0 and json_end > json_start:
            json_str = content[json_start:json_end]
            data = json.loads(json_str)

            version = PromptVersion(
                version_id=parent_version + 1,
                system_prompt=data.get("new_system_prompt", current_prompt),
                parent_version=parent_version,
                generation_method="evolution",
                changes_summary=data.get("changes_summary", ""),
                rationale=data.get("rationale", ""),
            )

            return version
        else:
            # Fallback: return current version with incremented ID
            return PromptVersion(
                version_id=parent_version + 1,
                system_prompt=current_prompt,
                parent_version=parent_version,
                generation_method="evolution",
                changes_summary="Failed to parse LLM response",
            )

    except Exception as e:
        print(f"Versioner error: {e}")
        # Return current with incremented version
        return PromptVersion(
            version_id=parent_version + 1,
            system_prompt=current_prompt,
            parent_version=parent_version,
            generation_method="evolution",
            changes_summary=f"Versioner error: {e}",
        )
