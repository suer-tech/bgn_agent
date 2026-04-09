import sys

sys.path = [p for p in sys.path if "BitGN" not in p]

filepath = r"C:/Users/user2/Documents/BitGN/sandbox-py/agents/context_extractor.py"
with open(filepath, "rb") as f:
    raw = f.read()

# Fix all broken patterns where literal 0x0A appears inside string literals
fixes = [
    (b'return "\n".join(lines)', b'return "\\n".join(lines)'),
    (b'.replace("\n", " ")', b'.replace("\\n", " ")'),
    (
        b'parts.append(f"### {p}\n{preview}...")',
        b'parts.append(f"### {p}\\n{preview}...")',
    ),
    (
        b'read_files_summary = "\n\n".join(parts)',
        b'read_files_summary = "\\n\\n".join(parts)',
    ),
    (b'available_paths = "\n".join', b'available_paths = "\\n".join'),
]

for i, (old, new) in enumerate(fixes):
    count = raw.count(old)
    if count > 0:
        print(f"Fix {i + 1}: Replacing {count} occurrences")
        raw = raw.replace(old, new)
    else:
        print(f"Fix {i + 1}: Pattern not found")

# Handle the user_msg f-string block
idx = raw.find(b"user_msg = (")
if idx >= 0:
    start = idx
    depth = 0
    end = start
    for i in range(start, min(start + 3000, len(raw))):
        if raw[i : i + 1] == b"(":
            depth += 1
        elif raw[i : i + 1] == b")":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    block = raw[start:end]

    # Fix f-strings with embedded newlines
    fstring_fixes = [
        (b'f"Task: {task_text}\n\n"', b'f"Task: {task_text}\\n\\n"'),
        (
            b'f"## Directory Tree\n{tree_summary}\n\n"',
            b'f"## Directory Tree\\n{tree_summary}\\n\\n"',
        ),
        (
            b'f"## All Available File Paths\n{available_paths}\n\n"',
            b'f"## All Available File Paths\\n{available_paths}\\n\\n"',
        ),
        (
            b'f"## AGENTS.MD Content\n{agents_content}\n\n"',
            b'f"## AGENTS.MD Content\\n{agents_content}\\n\\n"',
        ),
        (
            b'f"## Already Read Files (content shown)\n"',
            b'f"## Already Read Files (content shown)\\n"',
        ),
    ]

    for old, new in fstring_fixes:
        if old in block:
            block = block.replace(old, new)
            print(f"Fixed f-string")

    # Fix the conditional expression: find the em-dash pattern and fix newlines after it
    search = b"AGENTS.MD was read but is not listed here)'}"
    idx2 = block.find(search)
    if idx2 >= 0:
        after = block[idx2 : idx2 + 10]
        print(f"Found conditional, after: {repr(after)}")
        # The pattern is: '}\n\n" -> '}\n\n"
        old_cond = b"'}\n\n\""
        new_cond = b"'}\\n\\n\""
        if old_cond in block:
            block = block.replace(old_cond, new_cond, 1)
            print("Fixed conditional newlines")

    raw = raw[:start] + block + raw[end:]

with open(filepath, "wb") as f:
    f.write(raw)

# Verify
try:
    import ast

    ast.parse(raw.decode("utf-8"))
    print("Syntax OK!")
except SyntaxError as e:
    print(f"Error at line {e.lineno}: {e.msg}")
    lines = raw.decode("utf-8").split("\n")
    for i in range(max(0, e.lineno - 3), min(len(lines), e.lineno + 3)):
        marker = ">>>" if i == e.lineno - 1 else "   "
        print(f"{marker} Line {i + 1}: {repr(lines[i])}")
