import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from agents.prompt_storage import AgentPromptStore, save_prompt, get_prompt


VERSIONER_PROMPT_TEMPLATE = """You are a Versioner Agent. Your task is to improve a specific agent's prompt based on failure analysis.

## Current prompt for {agent_name}:
---
{current_prompt}
---

## Failure analysis:
{failure_analysis}

## Suggestions from analyzer:
{suggestions}

## Your task:
1. Review the current prompt
2. Apply the suggestions to improve it
3. Keep improvements focused - don't change what works
4. Add FIXED comments for each change
5. Make improvements generalizable for similar tasks, not for one concrete task
6. Preserve existing strengths and avoid overfitting

Generate the improved version of the prompt. Return JSON:
{{
  "new_prompt": "full improved prompt text",
  "changes_summary": "what changed",
  "rationale": "why these changes should help"
}}
"""


class VersionerResponse(BaseModel):
    new_prompt: str
    changes_summary: str
    rationale: str


class PerAgentVersioner:
    """
    Versioner that updates only the failing agent's prompt.
    """

    def __init__(self):
        self.agent_names = [
            "context_extractor",
            "execution_agent",
            "validation_agent",
            "security_gate",
        ]

    def update_agent_prompt(
        self,
        agent_name: str,
        current_prompt: str,
        failure_analysis: str,
        suggestions: str,
        provider: Any,  # LLMProvider
    ) -> Optional[int]:
        """
        Update a specific agent's prompt.

        Args:
            agent_name: Name of agent to update
            current_prompt: Current prompt text
            failure_analysis: Analysis of what's wrong
            suggestions: Suggestions from analyzer
            provider: LLM provider for generating improved prompt

        Returns:
            New version ID if successful, None if failed
        """
        if agent_name not in self.agent_names:
            raise ValueError(f"Unknown agent: {agent_name}")

        prompt = VERSIONER_PROMPT_TEMPLATE.format(
            agent_name=agent_name,
            current_prompt=current_prompt,
            failure_analysis=failure_analysis,
            suggestions=suggestions,
        )

        try:
            response = provider.complete_as(
                [{"role": "user", "content": prompt}],
                VersionerResponse,
            )

            new_prompt = response.new_prompt or current_prompt
            changes_summary = response.changes_summary or ""
            rationale = response.rationale or ""

            # Save new version
            store = AgentPromptStore(agent_name)
            next_version = store.get_next_version_id()
            current_version, _ = store.load_version_with_highest_score()

            save_prompt(
                agent_name=agent_name,
                version_id=next_version,
                content=new_prompt,
                parent_version_id=current_version,
                changes_summary=changes_summary,
            )

            print(f"Updated {agent_name} to v{next_version}")
            print(f"Changes: {changes_summary}")

            return next_version

        except Exception as e:
            print(f"Versioner error for {agent_name}: {e}")
            # Fallback for providers that don't support complete_as
            try:
                response = provider.complete([{"role": "user", "content": prompt}])
                content = response.content if hasattr(response, "content") else str(response)
                json_start = content.find("{")
                json_end = content.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = content[json_start:json_end]
                    data = json.loads(json_str)
                    new_prompt = data.get("new_prompt", current_prompt)
                    changes_summary = data.get("changes_summary", "")
                    store = AgentPromptStore(agent_name)
                    next_version = store.get_next_version_id()
                    current_version, _ = store.load_version_with_highest_score()
                    save_prompt(
                        agent_name=agent_name,
                        version_id=next_version,
                        content=new_prompt,
                        parent_version_id=current_version,
                        changes_summary=changes_summary,
                    )
                    print(f"Updated {agent_name} to v{next_version} (fallback parser)")
                    return next_version
            except Exception:
                return None
            return None

    def update_all_agents(
        self,
        analysis_results: Dict[str, Any],
        provider: Any,
    ) -> Dict[str, Optional[int]]:
        """
        Update all failing agents based on analysis.

        Returns dict mapping agent_name -> new_version_id
        """
        updates = {}

        for agent_name in self.agent_names:
            if agent_name not in analysis_results:
                continue

            analysis = analysis_results[agent_name]

            if not analysis.get("failure_detected", False):
                continue

            # Get current prompt
            try:
                current_prompt = get_prompt(agent_name)
            except:
                current_prompt = f"You are a {agent_name} agent."

            # Format failure info
            failure_analysis = "\n".join(analysis.get("failure_reasons", []))
            suggestions = "\n".join(analysis.get("suggestions", []))

            if not failure_analysis:
                continue

            # Update the prompt
            new_version = self.update_agent_prompt(
                agent_name=agent_name,
                current_prompt=current_prompt,
                failure_analysis=failure_analysis,
                suggestions=suggestions,
                provider=provider,
            )

            updates[agent_name] = new_version

        return updates


def update_agent(
    agent_name: str,
    current_prompt: str,
    failure_analysis: str,
    suggestions: str,
    provider: Any,
) -> Optional[int]:
    """Convenience function to update a single agent."""
    versioner = PerAgentVersioner()
    return versioner.update_agent_prompt(
        agent_name=agent_name,
        current_prompt=current_prompt,
        failure_analysis=failure_analysis,
        suggestions=suggestions,
        provider=provider,
    )
