import sys

sys.path = [p for p in sys.path if "BitGN" not in p]

filepath = r"C:/Users/user2/Documents/BitGN/pac1-py/llm_logger.py"
with open(filepath, "rb") as f:
    raw = f.read()

# Add write_task_summary method before create_logger
old = b'''def create_logger() -> LLMTraceLogger:
    """Create an LLMTraceLogger instance."""
    return LLMTraceLogger()'''

new = b'''    def write_task_summary(
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
        except Exception:
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

        # Build a map of agent events by step
        step_events: Dict[int, List[Dict]] = {}
        for evt in agent_events:
            details = evt.get("details", {})
            # Try to find which step this belongs to
            iteration = details.get("iteration", details.get("round", ""))
            step_num = 0
            if isinstance(iteration, str) and iteration.startswith("step_"):
                try:
                    step_num = int(iteration.split("_")[1])
                except (ValueError, IndexError):
                    pass
            if step_num not in step_events:
                step_events[step_num] = []
            step_events[step_num].append(evt)

        # Process entries (LLM exchanges)
        step_counter = 0
        for entry in entries:
            step_counter += 1
            step_name = entry.get("step_name", "")
            messages = entry.get("messages", [])
            response = entry.get("response", "")

            # Skip placeholder entries
            if response == "(calling LLM...)":
                continue

            # Determine which agent this belongs to
            agent_name = "unknown"
            if "execution_agent" in step_name:
                agent_name = "execution_agent"
            elif "context_extractor" in step_name:
                agent_name = "context_extractor"
            elif "security" in step_name:
                agent_name = "security_gate"

            # Extract tool call from messages
            tool_call_info = ""
            for msg in messages:
                if msg.get("tool_calls"):
                    tc = msg["tool_calls"][0]["function"]
                    tool_call_info = f"Tool: {tc.get('name', '?')} | Args: {tc.get('arguments', '')[:200]}"

            # Extract LLM response info
            llm_response_preview = ""
            llm_action = ""
            if response and response != "(calling LLM...)":
                try:
                    resp_json = json.loads(response)
                    llm_action = resp_json.get("current_state", resp_json.get("reasoning", ""))[:300]
                    func = resp_json.get("function", {})
                    if func:
                        tool_call_info = f"Tool: {func.get('tool', '?')} | Args: {json.dumps(func, ensure_ascii=False)[:200]}"
                except (json.JSONDecodeError, TypeError):
                    llm_response_preview = response[:300]

            # Find agent events for this step
            agent_action = ""
            for evt in step_events.get(step_counter, []):
                event_type = evt.get("event", "")
                if "decision" in event_type or "completed" in event_type:
                    details = evt.get("details", {})
                    if "tool_name" in details:
                        agent_action = f"Decided to use tool: {details['tool_name']}"
                    elif "files_read" in details:
                        agent_action = f"Read {details['files_read']} files"
                    elif "reasoning" in details:
                        agent_action = details["reasoning"][:200]

            summary_lines.append(f"--- Step {step_counter} ---")
            summary_lines.append(f"Agent: {agent_name}")
            if agent_action:
                summary_lines.append(f"Action: {agent_action}")
            elif llm_action:
                summary_lines.append(f"Action: {llm_action}")
            if tool_call_info:
                summary_lines.append(f"Tool Call: {tool_call_info}")
            if llm_response_preview:
                summary_lines.append(f"LLM Response: {llm_response_preview}")
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

        # Write summary to a separate file
        ts = self.task_log_path.stem
        summary_path = self.log_dir / f"{ts}_summary.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\\n".join(summary_lines))


def create_logger() -> LLMTraceLogger:
    """Create an LLMTraceLogger instance."""
    return LLMTraceLogger()'''

raw = raw.replace(old, new)

with open(filepath, "wb") as f:
    f.write(raw)

print("Added write_task_summary method")

# Verify syntax
import ast

ast.parse(raw.decode("utf-8"))
print("Syntax OK!")
