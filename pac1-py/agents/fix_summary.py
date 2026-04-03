import sys

sys.path = [p for p in sys.path if "BitGN" not in p]

filepath = r"C:/Users/user2/Documents/BitGN/pac1-py/llm_logger.py"
with open(filepath, "rb") as f:
    raw = f.read()

old_start = b"    def write_task_summary("
old_end = b"\ndef create_logger()"

start_idx = raw.find(old_start)
end_idx = raw.find(old_end)

if start_idx >= 0 and end_idx >= 0:
    NL = chr(10)
    DQ = chr(34)
    BS = chr(92)

    lines = []
    lines.append("    def write_task_summary(")
    lines.append("        self,")
    lines.append("        score: float = None,")
    lines.append("        score_detail: str = " + DQ + DQ + ",")
    lines.append("        error: str = " + DQ + DQ + ",")
    lines.append("    ) -> None:")
    lines.append(
        "        "
        + DQ
        + DQ
        + DQ
        + "Write a human-readable task summary log."
        + DQ
        + DQ
        + DQ
    )
    lines.append(
        "        if not hasattr(self, "
        + DQ
        + "task_log_path"
        + DQ
        + ") or not self.task_log_path.exists():"
    )
    lines.append("            return")
    lines.append("")
    lines.append("        try:")
    lines.append(
        "            with open(self.task_log_path, "
        + DQ
        + "r"
        + DQ
        + ", encoding="
        + DQ
        + "utf-8"
        + DQ
        + ") as f:"
    )
    lines.append("                data = json.load(f)")
    lines.append("        except Exception:")
    lines.append("            return")
    lines.append("")
    lines.append("        entries = data.get(" + DQ + "entries" + DQ + ", [])")
    lines.append(
        "        agent_events = data.get(" + DQ + "agent_events" + DQ + ", [])"
    )
    lines.append("")
    lines.append("        summary_lines = []")
    lines.append("        separator = " + DQ + "=" + DQ + " * 80")
    lines.append("")
    lines.append("        # Header")
    lines.append("        summary_lines.append(separator)")
    lines.append(
        "        summary_lines.append(f" + DQ + "Task: {self.task_id}" + DQ + ")"
    )
    lines.append(
        "        summary_lines.append(f"
        + DQ
        + "User Prompt: {self.task_text}"
        + DQ
        + ")"
    )
    lines.append("        summary_lines.append(separator)")
    lines.append("        summary_lines.append(" + DQ + DQ + ")")
    lines.append("")
    lines.append("        # Phase 1: Context Extractor events")
    lines.append(
        "        ctx_events = [e for e in agent_events if e.get("
        + DQ
        + "agent"
        + DQ
        + ") == "
        + DQ
        + "context_extractor"
        + DQ
        + "]"
    )
    lines.append("        if ctx_events:")
    lines.append(
        "            summary_lines.append(" + DQ + "## CONTEXT EXTRACTOR" + DQ + ")"
    )
    lines.append("            summary_lines.append(separator)")
    lines.append("            for evt in ctx_events:")
    lines.append(
        "                event = evt.get(" + DQ + "event" + DQ + ", " + DQ + DQ + ")"
    )
    lines.append("                details = evt.get(" + DQ + "details" + DQ + ", {})")
    lines.append(
        "                ts = evt.get(" + DQ + "timestamp" + DQ + ", " + DQ + DQ + ")"
    )
    lines.append(
        "                summary_lines.append(f" + DQ + "[{ts}] {event}" + DQ + ")"
    )
    lines.append("                if details:")
    lines.append("                    for k, v in details.items():")
    lines.append(
        "                        val = str(v)[:300] if v is not None else " + DQ + DQ
    )
    lines.append("                        if val:")
    lines.append(
        "                            summary_lines.append(f"
        + DQ
        + "  {k}: {val}"
        + DQ
        + ")"
    )
    lines.append("                summary_lines.append(" + DQ + DQ + ")")
    lines.append("")
    lines.append("        # Phase 2: Security Gate events")
    lines.append(
        "        sec_events = [e for e in agent_events if e.get("
        + DQ
        + "agent"
        + DQ
        + ") == "
        + DQ
        + "security_gate"
        + DQ
        + "]"
    )
    lines.append("        if sec_events:")
    lines.append(
        "            summary_lines.append(" + DQ + "## SECURITY GATE" + DQ + ")"
    )
    lines.append("            summary_lines.append(separator)")
    lines.append("            for evt in sec_events:")
    lines.append(
        "                event = evt.get(" + DQ + "event" + DQ + ", " + DQ + DQ + ")"
    )
    lines.append("                details = evt.get(" + DQ + "details" + DQ + ", {})")
    lines.append(
        "                ts = evt.get(" + DQ + "timestamp" + DQ + ", " + DQ + DQ + ")"
    )
    lines.append(
        "                summary_lines.append(f" + DQ + "[{ts}] {event}" + DQ + ")"
    )
    lines.append("                if details:")
    lines.append("                    for k, v in details.items():")
    lines.append(
        "                        val = str(v)[:300] if v is not None else " + DQ + DQ
    )
    lines.append("                        if val:")
    lines.append(
        "                            summary_lines.append(f"
        + DQ
        + "  {k}: {val}"
        + DQ
        + ")"
    )
    lines.append("                summary_lines.append(" + DQ + DQ + ")")
    lines.append("")
    lines.append("        # Phase 3: Execution Agent steps")
    lines.append(
        "        exec_events = [e for e in agent_events if e.get("
        + DQ
        + "agent"
        + DQ
        + ") == "
        + DQ
        + "execution_agent"
        + DQ
        + "]"
    )
    lines.append("        if entries or exec_events:")
    lines.append(
        "            summary_lines.append(" + DQ + "## EXECUTION AGENT" + DQ + ")"
    )
    lines.append("            summary_lines.append(separator)")
    lines.append("")
    lines.append("            step_counter = 0")
    lines.append("            for entry in entries:")
    lines.append("                step_counter += 1")
    lines.append(
        "                step_name = entry.get("
        + DQ
        + "step_name"
        + DQ
        + ", "
        + DQ
        + DQ
        + ")"
    )
    lines.append(
        "                messages = entry.get(" + DQ + "messages" + DQ + ", [])"
    )
    lines.append(
        "                response = entry.get("
        + DQ
        + "response"
        + DQ
        + ", "
        + DQ
        + DQ
        + ")"
    )
    lines.append("")
    lines.append("                if response == " + DQ + "(calling LLM...)" + DQ + ":")
    lines.append("                    continue")
    lines.append("")
    lines.append("                tool_call_name = " + DQ + DQ)
    lines.append("                tool_call_args = " + DQ + DQ)
    lines.append("                for msg in messages:")
    lines.append("                    if msg.get(" + DQ + "tool_calls" + DQ + "):")
    lines.append(
        "                        tc = msg["
        + DQ
        + "tool_calls"
        + DQ
        + "][0]["
        + DQ
        + "function"
        + DQ
        + "]"
    )
    lines.append(
        "                        tool_call_name = tc.get("
        + DQ
        + "name"
        + DQ
        + ", "
        + DQ
        + DQ
        + ")"
    )
    lines.append(
        "                        tool_call_args = tc.get("
        + DQ
        + "arguments"
        + DQ
        + ", "
        + DQ
        + DQ
        + ")[:200]"
    )
    lines.append("")
    lines.append("                tool_result = " + DQ + DQ)
    lines.append("                for msg in messages:")
    lines.append(
        "                    if msg.get("
        + DQ
        + "role"
        + DQ
        + ") == "
        + DQ
        + "tool"
        + DQ
        + ":"
    )
    lines.append(
        "                        tool_result = msg.get("
        + DQ
        + "content"
        + DQ
        + ", "
        + DQ
        + DQ
        + ")[:200]"
    )
    lines.append("")
    lines.append("                llm_action = " + DQ + DQ)
    lines.append("                llm_tool = " + DQ + DQ)
    lines.append("                llm_args = " + DQ + DQ)
    lines.append(
        "                if response and response != "
        + DQ
        + "(calling LLM...)"
        + DQ
        + ":"
    )
    lines.append("                    try:")
    lines.append("                        resp_json = json.loads(response)")
    lines.append(
        "                        llm_action = resp_json.get("
        + DQ
        + "current_state"
        + DQ
        + ", resp_json.get("
        + DQ
        + "reasoning"
        + DQ
        + ", "
        + DQ
        + DQ
        + "))[:300]"
    )
    lines.append(
        "                        func = resp_json.get(" + DQ + "function" + DQ + ", {})"
    )
    lines.append("                        if func:")
    lines.append(
        "                            llm_tool = func.get("
        + DQ
        + "tool"
        + DQ
        + ", "
        + DQ
        + DQ
        + ")"
    )
    lines.append(
        "                            llm_args = json.dumps(func, ensure_ascii=False)[:200]"
    )
    lines.append("                    except (json.JSONDecodeError, TypeError):")
    lines.append("                        pass")
    lines.append("")
    lines.append(
        "                summary_lines.append(f"
        + DQ
        + "--- Step {step_counter} ---"
        + DQ
        + ")"
    )
    lines.append(
        "                summary_lines.append("
        + DQ
        + "Agent: execution_agent"
        + DQ
        + ")"
    )
    lines.append("                if llm_action:")
    lines.append(
        "                    summary_lines.append(f"
        + DQ
        + "Reasoning: {llm_action}"
        + DQ
        + ")"
    )
    lines.append("                if tool_call_name or llm_tool:")
    lines.append(
        "                    summary_lines.append(f"
        + DQ
        + "Tool: {llm_tool or tool_call_name}"
        + DQ
        + ")"
    )
    lines.append(
        "                    summary_lines.append(f"
        + DQ
        + "Args: {llm_args or tool_call_args}"
        + DQ
        + ")"
    )
    lines.append("                if tool_result:")
    lines.append(
        "                    summary_lines.append(f"
        + DQ
        + "Result: {tool_result}"
        + DQ
        + ")"
    )
    lines.append("                summary_lines.append(" + DQ + DQ + ")")
    lines.append("")
    lines.append("            for evt in exec_events:")
    lines.append(
        "                event = evt.get(" + DQ + "event" + DQ + ", " + DQ + DQ + ")"
    )
    lines.append("                details = evt.get(" + DQ + "details" + DQ + ", {})")
    lines.append(
        "                ts = evt.get(" + DQ + "timestamp" + DQ + ", " + DQ + DQ + ")"
    )
    lines.append(
        "                if "
        + DQ
        + "decision"
        + DQ
        + " in event or "
        + DQ
        + "completed"
        + DQ
        + " in event or "
        + DQ
        + "error"
        + DQ
        + " in event:"
    )
    lines.append(
        "                    summary_lines.append(f" + DQ + "[{ts}] {event}" + DQ + ")"
    )
    lines.append("                    if details:")
    lines.append("                        for k, v in details.items():")
    lines.append(
        "                            val = str(v)[:300] if v is not None else "
        + DQ
        + DQ
    )
    lines.append("                            if val:")
    lines.append(
        "                                summary_lines.append(f"
        + DQ
        + "  {k}: {val}"
        + DQ
        + ")"
    )
    lines.append("                    summary_lines.append(" + DQ + DQ + ")")
    lines.append("")
    lines.append("        # Result")
    lines.append("        summary_lines.append(separator)")
    lines.append("        summary_lines.append(" + DQ + "RESULT" + DQ + ")")
    lines.append("        summary_lines.append(separator)")
    lines.append("        if score is not None:")
    lines.append(
        "            summary_lines.append(f" + DQ + "Score: {score:.2f}" + DQ + ")"
    )
    lines.append("        if score_detail:")
    lines.append(
        "            summary_lines.append(f" + DQ + "Detail: {score_detail}" + DQ + ")"
    )
    lines.append("        if error:")
    lines.append(
        "            summary_lines.append(f" + DQ + "Error: {error}" + DQ + ")"
    )
    lines.append("        summary_lines.append(" + DQ + DQ + ")")
    lines.append("")
    lines.append("        # Write summary to file")
    lines.append("        ts = self.task_log_path.stem")
    lines.append(
        "        summary_path = self.log_dir / f" + DQ + "{ts}_summary.txt" + DQ
    )
    lines.append(
        "        with open(summary_path, "
        + DQ
        + "w"
        + DQ
        + ", encoding="
        + DQ
        + "utf-8"
        + DQ
        + ") as f:"
    )
    lines.append("            f.write(" + DQ + BS + "n" + DQ + ".join(summary_lines))")
    lines.append("")

    new_method = NL.join(lines)
    raw = raw[:start_idx] + new_method.encode("utf-8") + raw[end_idx:]

    with open(filepath, "wb") as f:
        f.write(raw)

    import ast

    ast.parse(raw.decode("utf-8"))
    print("Updated write_task_summary, syntax OK!")
else:
    print(f"Could not find method boundaries: start={start_idx}, end={end_idx}")
