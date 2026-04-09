import subprocess
import os

def check_tree():
    root = "02_distill/cards"
    if not os.path.exists(root):
        print(f"Path {root} does not exist.")
        return
    
    print(f"--- Running tree -L 1 {root} ---")
    try:
        res = subprocess.run(["tree", "-L", "1", root], capture_output=True, text=True, encoding='utf-8')
        print(f"Full output:\n{res.stdout}")
        print("--- Line by line analysis ---")
        for i, line in enumerate(res.stdout.splitlines()):
            print(f"Line {i}: {line!r}")
            print(f"      Bytes: {line.encode('utf-8')}")
    except Exception as e:
        print(f"Error running tree: {e}")

if __name__ == "__main__":
    check_tree()
