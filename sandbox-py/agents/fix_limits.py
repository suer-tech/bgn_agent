import sys

sys.path = [p for p in sys.path if "BitGN" not in p]

filepath = r"C:/Users/user2/Documents/BitGN/sandbox-py/agents/context_extractor.py"
with open(filepath, "rb") as f:
    raw = f.read()

# Change max_llm_round default from 8 to 30
old1 = b"max_llm_round: int = 8,"
new1 = b"max_llm_round: int = 30,"
if old1 in raw:
    raw = raw.replace(old1, new1)
    print("Changed max_llm_round: 8 -> 30")
else:
    print("max_llm_round pattern not found")

# Change max_files default from 50 to 500
old2 = b"max_files: int = 50,"
new2 = b"max_files: int = 500,"
if old2 in raw:
    raw = raw.replace(old2, new2)
    print("Changed max_files: 50 -> 500")
else:
    print("max_files pattern not found")

with open(filepath, "wb") as f:
    f.write(raw)

# Verify syntax
try:
    import ast

    ast.parse(raw.decode("utf-8"))
    print("Syntax OK!")
except SyntaxError as e:
    print(f"Error at line {e.lineno}: {e.msg}")
