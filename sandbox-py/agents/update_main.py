import sys

sys.path = [p for p in sys.path if "BitGN" not in p]

# ============================================================
# 2. Update main.py - create trace_logger for orchestrator
# ============================================================
filepath = r"C:/Users/user2/Documents/BitGN/sandbox-py/main.py"
with open(filepath, "rb") as f:
    raw = f.read()

# Add import for Orchestrator
old = b"from self_evolution.executor import run_task_with_prompt"
new = b"from self_evolution.executor import run_task_with_prompt\nfrom orchestrator import Orchestrator"
raw = raw.replace(old, new)

# Update the trace_logger creation to not use keep_last_only
old = b"""                trace_logger = LLMTraceLogger(
                    log_dir="logs/main",
                    keep_last_only=True,
                    per_task_files=True,
                )"""
new = b"""                trace_logger = LLMTraceLogger(
                    log_dir="logs/main",
                    keep_last_only=False,
                    per_task_files=True,
                )"""
raw = raw.replace(old, new)

with open(filepath, "wb") as f:
    f.write(raw)

print("Updated main.py")

# Verify syntax
try:
    import ast

    ast.parse(raw.decode("utf-8"))
    print("Syntax OK!")
except SyntaxError as e:
    print(f"Error at line {e.lineno}: {e.msg}")
