import re

def new_tree_parser(result_output, root_arg):
    grounded_paths = set()
    root = (root_arg or "/").replace("\\", "/").strip("/")
    lines = result_output.splitlines()
    if not lines:
        return grounded_paths
    
    # The first line is usually the root name or the command result header
    # We initialize the stack with the root provided in arguments
    stack = [root] if root else []
    
    for line in lines[1:]:
        # Detect indentation level (4 characters per level: '|   ' or '    ')
        # line looks like '|   |-- filename' or '|-- filename'
        prefix_match = re.match(r"^([| ]   )*", line)
        indent_len = len(prefix_match.group(0)) if prefix_match else 0
        depth = indent_len // 4
        
        # Extract clean name by removing branch symbols
        candidate = re.sub(r"^[| `\t]*[|-]{2,}\s*", "", line[indent_len:]).strip()
        candidate = candidate.rstrip("/")
        
        if not candidate or candidate == "." or "directory" in candidate.lower():
            continue
        
        # Adjust stack to current depth
        while len(stack) > depth + (1 if root else 0):
            stack.pop()
        
        # Construct full path
        current_full_path = "/".join(stack + [candidate]).strip("/")
        grounded_paths.add(current_full_path.replace("\\", "/").lstrip("/").lower())
        
        # Push to stack if it looks like a directory (no extension)
        if "." not in candidate:
            stack.append(candidate)
            
    return grounded_paths

def test_fix():
    tree_output = """02_distill
|-- AGENTS.md
|-- cards
|   |-- 2026-02-10__how-i-use-claude-code.md
|   |-- 2026-02-15__openai-harness-engineering.md
|   `-- _card-template.md
`-- threads
    |-- 2026-03-23__agent-platforms-and-runtime.md
    `-- _thread-template.md"""

    root = "02_distill"
    paths = new_tree_parser(tree_output, root)
    
    print(f"Root: {root}")
    print("Parsed grounded_paths:")
    for p in sorted(list(paths)):
        print(f"  - {p}")
    
    target1 = "02_distill/cards/2026-02-10__how-i-use-claude-code.md".lower()
    target2 = "02_distill/threads/2026-03-23__agent-platforms-and-runtime.md".lower()
    
    success = True
    if target1 in paths:
        print(f"\nSUCCESS: Target 1 '{target1}' found!")
    else:
        print(f"\nFAILURE: Target 1 '{target1}' NOT found!")
        success = False

    if target2 in paths:
        print(f"SUCCESS: Target 2 '{target2}' found!")
    else:
        print(f"FAILURE: Target 2 '{target2}' NOT found!")
        success = False
        
    if success:
        print("\nALL TARGETS FOUND! The fix is working perfectly.")

if __name__ == "__main__":
    test_fix()
