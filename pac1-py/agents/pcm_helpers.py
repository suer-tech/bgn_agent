"""PCM runtime helpers — thin wrappers over Protobuf gRPC calls.

Every function here takes a PcmRuntimeClientSync and returns plain
Python types (str, dict, list) so that graph nodes never touch
protobuf directly.
"""

import json
import shlex
from typing import Any, Dict, List, Optional

from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import (
    AnswerRequest,
    ContextRequest,
    DeleteRequest,
    FindRequest,
    ListRequest,
    MkDirRequest,
    MoveRequest,
    ReadRequest,
    SearchRequest,
    TreeRequest,
    WriteRequest,
)
from connectrpc.errors import ConnectError
from google.protobuf.json_format import MessageToDict

from agents.types import get_outcome_map


# =============================================================================
# Low-level safe wrappers (return Python primitives)
# =============================================================================


def safe_read_file(vm: PcmRuntimeClientSync, path: str) -> Optional[str]:
    """Read a file and return its text content, or None on error."""
    try:
        result = vm.read(ReadRequest(path=path))
        parsed = MessageToDict(result)
        content = parsed.get("content", "")
        return content if isinstance(content, str) else None
    except Exception:
        return None


def safe_tree(vm: PcmRuntimeClientSync, root: str = "/", level: int = 3) -> Dict[str, Any]:
    """Get directory tree as a plain dict."""
    try:
        result = vm.tree(TreeRequest(root=root, level=level))
        return MessageToDict(result)
    except Exception:
        return {}


def safe_list(vm: PcmRuntimeClientSync, path: str = "/") -> List[Dict[str, Any]]:
    """List directory entries as a list of dicts."""
    try:
        result = vm.list(ListRequest(name=path))
        return [MessageToDict(e) for e in result.entries] if result.entries else []
    except Exception:
        return []


def safe_find(
    vm: PcmRuntimeClientSync,
    name: str,
    root: str = "/",
    kind: str = "all",
    limit: int = 10,
) -> List[str]:
    """Find files by name pattern, return list of paths."""
    try:
        kind_map = {"all": 0, "files": 1, "dirs": 2}
        result = vm.find(FindRequest(root=root, name=name, type=kind_map.get(kind, 0), limit=limit))
        return [m.path for m in result.matches] if result.matches else []
    except Exception:
        return []


def safe_search(
    vm: PcmRuntimeClientSync,
    pattern: str,
    root: str = "/",
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Grep-search for a pattern, return list of match dicts."""
    try:
        result = vm.search(SearchRequest(root=root, pattern=pattern, limit=limit))
        return [
            {"path": m.path, "line": m.line, "line_text": m.line_text}
            for m in result.matches
        ] if result.matches else []
    except Exception:
        return []


def safe_write(
    vm: PcmRuntimeClientSync,
    path: str,
    content: str,
    start_line: int = 0,
    end_line: int = 0,
) -> str:
    """Write file content. Returns status string."""
    try:
        result = vm.write(WriteRequest(
            path=path, content=content, start_line=start_line, end_line=end_line,
        ))
        return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'
    except ConnectError as e:
        return f"ERROR: {e.message}"
    except Exception as e:
        return f"ERROR: {e}"


def safe_delete(vm: PcmRuntimeClientSync, path: str) -> str:
    """Delete a file. Returns status string."""
    try:
        result = vm.delete(DeleteRequest(path=path))
        return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'
    except ConnectError as e:
        return f"ERROR: {e.message}"
    except Exception as e:
        return f"ERROR: {e}"


def safe_mkdir(vm: PcmRuntimeClientSync, path: str) -> str:
    """Create a directory. Returns status string."""
    try:
        result = vm.mk_dir(MkDirRequest(path=path))
        return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'
    except ConnectError as e:
        return f"ERROR: {e.message}"
    except Exception as e:
        return f"ERROR: {e}"


def safe_move(vm: PcmRuntimeClientSync, from_name: str, to_name: str) -> str:
    """Move/rename a file. Returns status string."""
    try:
        result = vm.move(MoveRequest(from_name=from_name, to_name=to_name))
        return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'
    except ConnectError as e:
        return f"ERROR: {e.message}"
    except Exception as e:
        return f"ERROR: {e}"


def safe_context(vm: PcmRuntimeClientSync) -> str:
    """Get context. Returns JSON string."""
    try:
        result = vm.context(ContextRequest())
        return json.dumps(MessageToDict(result), indent=2) if result else "{}"
    except ConnectError as e:
        return f"ERROR: {e.message}"
    except Exception as e:
        return f"ERROR: {e}"


def send_answer(
    vm: PcmRuntimeClientSync,
    message: str,
    outcome: str,
    refs: List[str] = None,
) -> None:
    """Send final AnswerRequest to PCM. Only the orchestrator should call this."""
    outcome_map = get_outcome_map()
    vm.answer(AnswerRequest(
        message=message,
        outcome=outcome_map.get(outcome, outcome_map["OUTCOME_ERR_INTERNAL"]),
        refs=refs or [],
    ))


# =============================================================================
# Unified tool dispatcher (used by tool_executor.py)
# =============================================================================


def dispatch_tool(vm: PcmRuntimeClientSync, tool_call: dict) -> str:
    """Dispatch a tool call dict to the appropriate PCM method.

    Args:
        vm: PCM runtime client
        tool_call: dict with "name" and "arguments" keys

    Returns:
        Formatted string result for LLM consumption.
    """
    name = tool_call.get("name", "")
    args = tool_call.get("arguments", {})

    try:
        if name == "tree":
            result = vm.tree(TreeRequest(
                root=args.get("root", ""),
                level=args.get("level", 2),
            ))
            return format_tree(args, result)

        elif name in ("list", "ls"):
            result = vm.list(ListRequest(name=args.get("path", "/")))
            return format_list(args, result)

        elif name in ("read", "cat"):
            result = vm.read(ReadRequest(
                path=args.get("path", ""),
                number=args.get("number", False),
                start_line=args.get("start_line", 0),
                end_line=args.get("end_line", 0),
            ))
            return format_read(args, result)

        elif name == "search":
            result = vm.search(SearchRequest(
                root=args.get("root", "/"),
                pattern=args.get("pattern", ""),
                limit=args.get("limit", 10),
            ))
            return format_search(args, result)

        elif name == "find":
            kind_map = {"all": 0, "files": 1, "dirs": 2}
            result = vm.find(FindRequest(
                root=args.get("root", "/"),
                name=args.get("name", ""),
                type=kind_map.get(args.get("kind", "all"), 0),
                limit=args.get("limit", 10),
            ))
            return json.dumps(MessageToDict(result), indent=2)

        elif name == "write":
            result = vm.write(WriteRequest(
                path=args.get("path", ""),
                content=args.get("content", ""),
                start_line=args.get("start_line", 0),
                end_line=args.get("end_line", 0),
            ))
            return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'

        elif name == "delete":
            result = vm.delete(DeleteRequest(path=args.get("path", "")))
            return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'

        elif name == "mkdir":
            result = vm.mk_dir(MkDirRequest(path=args.get("path", "")))
            return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'

        elif name == "move":
            result = vm.move(MoveRequest(
                from_name=args.get("from_name", ""),
                to_name=args.get("to_name", ""),
            ))
            return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'

        elif name == "context":
            result = vm.context(ContextRequest())
            return json.dumps(MessageToDict(result), indent=2) if result else "{}"

        else:
            return f'{{"error": "Unknown tool: {name}"}}'

    except ConnectError as e:
        return str(e.message)
    except Exception as e:
        return str(e)


# =============================================================================
# Output formatters (LLM-friendly, shell-like)
# =============================================================================


def format_tree(args: dict, result) -> str:
    """Format tree result in a shell-like tree output."""
    root = result.root
    if not root.name:
        body = "."
    else:
        lines = [root.name]
        children = list(root.children)
        for idx, child in enumerate(children):
            lines.extend(format_tree_entry(child, is_last=idx == len(children) - 1))
        body = "\n".join(lines)

    root_arg = args.get("root", "") or "/"
    level = args.get("level", 2)
    level_arg = f" -L {level}" if level > 0 else ""
    return f"tree{level_arg} {root_arg}\n{body}"


def format_tree_entry(entry, prefix: str = "", is_last: bool = True) -> List[str]:
    branch = "└── " if is_last else "├── "
    lines = [f"{prefix}{branch}{entry.name}"]
    child_prefix = f"{prefix}{'    ' if is_last else '│   '}"
    children = list(entry.children)
    for idx, child in enumerate(children):
        lines.extend(format_tree_entry(child, prefix=child_prefix, is_last=idx == len(children) - 1))
    return lines


def format_list(args: dict, result) -> str:
    if not result.entries:
        body = "."
    else:
        body = "\n".join(
            f"{entry.name}/" if entry.is_dir else entry.name
            for entry in result.entries
        )
    return f"ls {args.get('path', '/')}\n{body}"


def format_read(args: dict, result) -> str:
    path = args.get("path", "")
    start = args.get("start_line", 0)
    end = args.get("end_line", 0)
    number = args.get("number", False)

    if start > 0 or end > 0:
        s = start if start > 0 else 1
        e = end if end > 0 else "$"
        command = f"sed -n '{s},{e}p' {path}"
    elif number:
        command = f"cat -n {path}"
    else:
        command = f"cat {path}"
    return f"{command}\n{result.content}"


def format_search(args: dict, result) -> str:
    root = shlex.quote(args.get("root", "/"))
    pattern = shlex.quote(args.get("pattern", ""))
    body = "\n".join(
        f"{match.path}:{match.line}:{match.line_text}"
        for match in result.matches
    )
    return f"rg -n --no-heading -e {pattern} {root}\n{body}"
