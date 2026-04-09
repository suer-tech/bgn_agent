import argparse
import json
import os
import sys
from pathlib import Path


def _read_payload(source_path: str | None) -> str:
    if source_path:
        return Path(source_path).read_text(encoding="utf-8")

    print("Paste JSON response, then submit with Ctrl+Z Enter (Windows) or Ctrl+D:", file=sys.stderr)
    return sys.stdin.read()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write an Antigravity JSON response to logs/.llm_response.json.",
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="Optional path to a file containing the JSON response.",
    )
    args = parser.parse_args()

    log_dir = Path(os.getenv("LLM_IO_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    response_path = log_dir / ".llm_response.json"
    temp_path = log_dir / ".llm_response.json.tmp"

    raw_payload = _read_payload(args.source).strip()
    if not raw_payload:
        raise ValueError("Response payload is empty.")

    parsed = json.loads(raw_payload)

    temp_path.write_text(
        json.dumps(parsed, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(response_path)

    print(f"Wrote Antigravity response to {response_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
