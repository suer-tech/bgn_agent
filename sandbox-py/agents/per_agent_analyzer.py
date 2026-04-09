import json
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class AgentFailureAnalysis(BaseModel):
    """Analysis result for each agent."""

    agent_name: str
    failure_detected: bool
    failure_reasons: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class LLMPerAgentAnalysis(BaseModel):
    agent_name: Literal[
        "context_extractor",
        "execution_agent",
        "validation_agent",
        "security_gate",
    ]
    failure_detected: bool
    failure_reasons: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class LLMAnalyzerResponse(BaseModel):
    analyses: List[LLMPerAgentAnalysis] = Field(default_factory=list)
    global_feedback: List[str] = Field(default_factory=list)


class PerAgentAnalyzer:
    """
    Analyzer that identifies which specific agent failed in a task.

    Checks:
    - Context Extractor: Did it properly read AGENTS.MD? Extract rules?
    - Execution Agent: Was the workflow (discovery->planning->execution) followed?
    - Validation Agent: Did it catch errors? Check grounding references?
    """

    def __init__(self):
        self.agent_names = [
            "context_extractor",
            "execution_agent",
            "validation_agent",
            "security_gate",
        ]

    def analyze_task_failure(self, task_result: Any, provider: Any = None) -> Dict[str, AgentFailureAnalysis]:
        """
        Analyze a failed task and identify which agent(s) caused the failure.

        Returns dict mapping agent_name -> AgentFailureAnalysis
        """
        results = {}

        # Use LLM analyzer first if provider supports structured output
        llm_results = self._analyze_with_llm(task_result, provider)
        if llm_results:
            return llm_results

        # Analyze each agent
        context_analysis = self._analyze_context_extractor(task_result)
        execution_analysis = self._analyze_execution_agent(task_result)
        validation_analysis = self._analyze_validation_agent(task_result)
        security_analysis = self._analyze_security_gate(task_result)

        results["context_extractor"] = context_analysis
        results["execution_agent"] = execution_analysis
        results["validation_agent"] = validation_analysis
        results["security_gate"] = security_analysis

        return results

    def _format_task_for_llm(self, task_result: Any) -> str:
        tool_calls = task_result.tool_calls if hasattr(task_result, "tool_calls") else []
        compact_calls = []
        for tc in tool_calls:
            compact_calls.append(
                {
                    "iteration": getattr(tc, "iteration", ""),
                    "tool_name": getattr(tc, "tool_name", ""),
                    "arguments": getattr(tc, "arguments", {}),
                    "result_success": getattr(tc, "result_success", True),
                    "result_summary": getattr(tc, "result_summary", ""),
                }
            )

        payload = {
            "task_id": getattr(task_result, "task_id", ""),
            "user_question": getattr(task_result, "input", ""),
            "status": getattr(task_result, "status", ""),
            "score": getattr(task_result, "score", None),
            "score_detail": getattr(task_result, "score_detail", []),
            "output": getattr(task_result, "output", ""),
            "context_docs": getattr(task_result, "context_docs", {}),
            "llm_reasoning_trace": getattr(task_result, "llm_reasoning_trace", []),
            "trace_log_path": getattr(task_result, "trace_log_path", ""),
            "grounding_refs": getattr(task_result, "grounding_refs", []),
            "completed_steps": getattr(task_result, "completed_steps", []),
            "iterations_used": getattr(task_result, "iterations_used", 0),
            "tool_calls": compact_calls,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _analyze_with_llm(
        self,
        task_result: Any,
        provider: Any,
    ) -> Dict[str, AgentFailureAnalysis]:
        if provider is None or not hasattr(provider, "complete_as"):
            return {}

        prompt = f"""You are analyzing one benchmark task failure in a multi-agent system.

Goal: identify which internal agent should be improved and how, using the evaluator feedback.
Important constraints:
- Use score/score_detail as source of truth.
- Propose UNIVERSAL improvements only.
- Do NOT overfit to this single task.
- Do NOT suggest hardcoded paths/phrases for this task.
- Focus on reusable policies and decision rules.

Agents:
- context_extractor: rule extraction from AGENTS/policy docs.
- execution_agent: planning + tool use + final answer shape.
- validation_agent: catches risky output before final completion.
- security_gate: blocks unsafe calls (injection/path traversal/protected files), allows safe calls.

Task data:
{self._format_task_for_llm(task_result)}

Return structured analyses for all 4 agents.
Mark failure_detected=true only when this agent likely contributed.
For suggestions: give concrete prompt-level behavior changes, still generic.
"""
        try:
            response = provider.complete_as([{"role": "user", "content": prompt}], LLMAnalyzerResponse)
        except Exception:
            return {}

        result_map: Dict[str, AgentFailureAnalysis] = {}
        for entry in response.analyses:
            result_map[entry.agent_name] = AgentFailureAnalysis(
                agent_name=entry.agent_name,
                failure_detected=entry.failure_detected,
                failure_reasons=entry.failure_reasons,
                suggestions=entry.suggestions,
            )

        # Guarantee all agents are present
        for name in self.agent_names:
            if name not in result_map:
                result_map[name] = AgentFailureAnalysis(
                    agent_name=name,
                    failure_detected=False,
                )
        return result_map

    def _analyze_context_extractor(self, task_result: Any) -> AgentFailureAnalysis:
        """Analyze if context extraction was the problem."""
        failure_reasons = []
        suggestions = []

        # Check if project rules were extracted
        tool_calls = (
            task_result.tool_calls if hasattr(task_result, "tool_calls") else []
        )

        # Look for read AGENTS.MD calls
        agents_md_read = any(
            tc.tool_name == "read" and "AGENTS" in str(tc.arguments)
            for tc in tool_calls
        )

        if not agents_md_read and task_result.status == "failed":
            failure_reasons.append("AGENTS.MD was not read at start")
            suggestions.append(
                "Always read AGENTS.MD in discovery phase before proceeding"
            )

        # Check for missing user profile
        if hasattr(task_result, "context") and task_result.context:
            ctx = task_result.context
            if not ctx.get("user_profile"):
                failure_reasons.append("User profile not collected")
                suggestions.append("Run whoami to get user profile")

        return AgentFailureAnalysis(
            agent_name="context_extractor",
            failure_detected=len(failure_reasons) > 0,
            failure_reasons=failure_reasons,
            suggestions=suggestions,
        )

    def _analyze_execution_agent(self, task_result: Any) -> AgentFailureAnalysis:
        """Analyze if execution workflow was the problem."""
        failure_reasons = []
        suggestions = []

        tool_calls = (
            task_result.tool_calls if hasattr(task_result, "tool_calls") else []
        )

        # Check for proper phase sequence
        tool_names = [tc.tool_name for tc in tool_calls]

        # Discovery phase should come before planning
        phase_errors = []

        # Check if stuck in loop
        if len(tool_calls) > 5:
            # Check for stagnation
            last_3 = tool_names[-3:] if len(tool_names) >= 3 else tool_names
            if len(set(last_3)) == 1:
                failure_reasons.append(
                    "Agent stuck in loop - same tool called 3+ times"
                )
                suggestions.append("If stuck, try different approach or report failure")

        # Check if skipped discovery
        if "create_plan" in tool_names and "tree" not in tool_names:
            failure_reasons.append(
                "Skipped discovery phase - tried to create plan without exploring"
            )
            suggestions.append("Always discover workspace structure with tree() first")

        # Check if skipped planning
        has_execution_without_plan = (
            any(tc.tool_name in ("write", "delete", "read") for tc in tool_calls)
            and "create_plan" not in tool_names
        )
        if has_execution_without_plan:
            failure_reasons.append("Skipped planning - started executing without plan")
            suggestions.append(
                "Create a plan with create_plan() before executing steps"
            )

        # Check for missing grounding refs in completion
        if any(tc.tool_name == "report_completion" for tc in tool_calls):
            completion_calls = [
                tc for tc in tool_calls if tc.tool_name == "report_completion"
            ]
            for tc in completion_calls:
                if tc.arguments.get("grounding_refs") == []:
                    failure_reasons.append("Missing grounding references in completion")
                    suggestions.append(
                        "Always include all files that influenced your answer in grounding_refs"
                    )

        score_detail = (
            task_result.score_detail
            if hasattr(task_result, "score_detail") and task_result.score_detail
            else []
        )
        score_detail_text = "\n".join(score_detail).lower()

        if "not precise" in score_detail_text or "exactly" in score_detail_text:
            failure_reasons.append(
                "Final answer format/precision did not match evaluator requirements"
            )
            suggestions.append(
                "Before report_completion, run a strict final-answer check: return exact required string with no extra words"
            )

        if "unexpected change" in score_detail_text:
            failure_reasons.append("Task caused unexpected workspace changes")
            suggestions.append(
                "Add final safety gate: perform only minimal necessary edits and avoid creating/modifying unrelated files"
            )

        return AgentFailureAnalysis(
            agent_name="execution_agent",
            failure_detected=len(failure_reasons) > 0,
            failure_reasons=failure_reasons,
            suggestions=suggestions,
        )

    def _analyze_validation_agent(self, task_result: Any) -> AgentFailureAnalysis:
        """Analyze if validation was the problem."""
        failure_reasons = []
        suggestions = []

        # Check if errors were not caught
        tool_calls = (
            task_result.tool_calls if hasattr(task_result, "tool_calls") else []
        )

        for tc in tool_calls:
            result_summary = tc.result_summary if hasattr(tc, "result_summary") else ""

            # Check for common error patterns that weren't caught
            error_patterns = [
                ("permission denied", "Permission errors not detected"),
                ("not found", "File not found errors not detected"),
                ("error", "Generic errors not caught"),
                ("timeout", "Timeout errors not caught"),
            ]

            for pattern, reason in error_patterns:
                if pattern in result_summary.lower():
                    failure_reasons.append(f"Validation missed: {pattern}")
                    suggestions.append(
                        "Check tool results for error indicators before proceeding"
                    )

        score_detail = (
            task_result.score_detail
            if hasattr(task_result, "score_detail") and task_result.score_detail
            else []
        )
        score_detail_text = "\n".join(score_detail).lower()
        if "unexpected change" in score_detail_text:
            failure_reasons.append("Validation did not block unintended filesystem diffs")
            suggestions.append(
                "Before completion, validate that only expected files changed; if extra changes exist, rollback plan and re-check"
            )
        if "not precise" in score_detail_text:
            failure_reasons.append("Validation did not enforce strict output format")
            suggestions.append(
                "Add final output conformance check against likely expected format (exact path/value, no wrappers)"
            )

        return AgentFailureAnalysis(
            agent_name="validation_agent",
            failure_detected=len(failure_reasons) > 0,
            failure_reasons=failure_reasons,
            suggestions=suggestions,
        )

    def _analyze_security_gate(self, task_result: Any) -> AgentFailureAnalysis:
        """Analyze if security gate behavior was the problem."""
        failure_reasons = []
        suggestions = []

        score_detail = (
            task_result.score_detail
            if hasattr(task_result, "score_detail") and task_result.score_detail
            else []
        )
        score_detail_text = "\n".join(score_detail).lower()

        if "unexpected change" in score_detail_text:
            failure_reasons.append(
                "Security gate did not prevent unintended workspace modifications"
            )
            suggestions.append(
                "Strengthen safe-change policy: block operations likely to introduce unrelated changes"
            )

        tool_calls = (
            task_result.tool_calls if hasattr(task_result, "tool_calls") else []
        )
        blocked_count = sum(
            1
            for tc in tool_calls
            if "blocked by security gate" in str(getattr(tc, "result_summary", "")).lower()
        )
        if blocked_count >= 3 and (task_result.score or 0.0) == 0.0:
            failure_reasons.append(
                "Security gate may be over-blocking and preventing task completion"
            )
            suggestions.append(
                "Refine blocking criteria to reduce false positives while preserving core security constraints"
            )

        return AgentFailureAnalysis(
            agent_name="security_gate",
            failure_detected=len(failure_reasons) > 0,
            failure_reasons=failure_reasons,
            suggestions=suggestions,
        )

    def get_failing_agents(
        self, analysis: Dict[str, AgentFailureAnalysis]
    ) -> List[str]:
        """Get list of agent names that failed."""
        return [name for name, result in analysis.items() if result.failure_detected]

    def format_suggestions(self, analysis: Dict[str, AgentFailureAnalysis]) -> str:
        """Format suggestions for all failing agents."""
        lines = []

        for agent_name, result in analysis.items():
            if result.failure_detected:
                lines.append(f"## {agent_name}")
                for reason in result.failure_reasons:
                    lines.append(f"- {reason}")
                for suggestion in result.suggestions:
                    lines.append(f"  Suggestion: {suggestion}")
                lines.append("")

        return "\n".join(lines) if lines else "No failures detected"


def analyze_task_failures(task_results: List[Any]) -> Dict[str, AgentFailureAnalysis]:
    """Analyze multiple task results and aggregate agent failures."""
    analyzer = PerAgentAnalyzer()

    aggregated = {
        "context_extractor": AgentFailureAnalysis(
            agent_name="context_extractor", failure_detected=False
        ),
        "execution_agent": AgentFailureAnalysis(
            agent_name="execution_agent", failure_detected=False
        ),
        "validation_agent": AgentFailureAnalysis(
            agent_name="validation_agent", failure_detected=False
        ),
        "security_gate": AgentFailureAnalysis(
            agent_name="security_gate", failure_detected=False
        ),
    }

    for task_result in task_results:
        if task_result.status == "passed":
            continue

        analysis = analyzer.analyze_task_failure(task_result)

        for agent_name, agent_result in analysis.items():
            if agent_result.failure_detected:
                # Mark as failed and add reasons
                if not aggregated[agent_name].failure_detected:
                    aggregated[agent_name].failure_detected = True
                aggregated[agent_name].failure_reasons.extend(
                    agent_result.failure_reasons
                )
                aggregated[agent_name].suggestions.extend(agent_result.suggestions)

    return aggregated
