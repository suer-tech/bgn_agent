import json
import shlex
from pathlib import PurePosixPath
from typing import Any, Dict, Optional

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


def _tree_lines(entry, prefix: str = "", is_last: bool = True) -> list[str]:
    branch = "`-- " if is_last else "|-- "
    lines = [f"{prefix}{branch}{entry.name}"]
    child_prefix = f"{prefix}{'    ' if is_last else '|   '}"
    children = list(entry.children)
    for index, child in enumerate(children):
        lines.extend(_tree_lines(child, prefix=child_prefix, is_last=index == len(children) - 1))
    return lines


def pcm_read(
    vm: PcmRuntimeClientSync,
    path: Optional[str],
    *,
    number: bool = False,
    start_line: int = 0,
    end_line: int = 0,
    allow_missing: bool = False,
) -> Optional[str]:
    if not path:
        return None
    try:
        result = vm.read(
            ReadRequest(
                path=path,
                number=number,
                start_line=start_line,
                end_line=end_line,
            )
        )
        parsed = MessageToDict(result)
        return parsed.get("content", "")
    except Exception:
        if allow_missing:
            return None
        raise


def pcm_list(vm: PcmRuntimeClientSync, path: str) -> str:
    result = vm.list(ListRequest(name=path))
    if not result.entries:
        return f"ls {path}\n."
    body = "\n".join(f"{entry.name}/" if entry.is_dir else entry.name for entry in result.entries)
    return f"ls {path}\n{body}"


def pcm_tree(vm: PcmRuntimeClientSync, root: str, level: int = 2) -> str:
    result = vm.tree(TreeRequest(root=root, level=level))
    root_entry = result.root
    if not root_entry.name:
        body = "."
    else:
        lines = [root_entry.name]
        children = list(root_entry.children)
        for index, child in enumerate(children):
            lines.extend(_tree_lines(child, is_last=index == len(children) - 1))
        body = "\n".join(lines)
    level_arg = f" -L {level}" if level > 0 else ""
    return f"tree{level_arg} {root or '/'}\n{body}"


def pcm_dispatch(vm: PcmRuntimeClientSync, tool_name: str, arguments: Dict[str, Any]) -> str:
    try:
        if tool_name == "context":
            result = vm.context(ContextRequest())
            return json.dumps(MessageToDict(result), indent=2)
        if tool_name == "tree":
            return pcm_tree(vm, arguments.get("root", "/"), level=arguments.get("level", 2))
        if tool_name in ("list", "ls"):
            return pcm_list(vm, arguments.get("path", "/"))
        if tool_name in ("read", "cat"):
            content = pcm_read(
                vm,
                arguments.get("path", ""),
                number=arguments.get("number", False),
                start_line=arguments.get("start_line", 0),
                end_line=arguments.get("end_line", 0),
            )
            path = arguments.get("path", "")
            if arguments.get("start_line", 0) > 0 or arguments.get("end_line", 0) > 0:
                start = arguments.get("start_line", 0) or 1
                end = arguments.get("end_line", 0) or "$"
                command = f"sed -n '{start},{end}p' {path}"
            elif arguments.get("number", False):
                command = f"cat -n {path}"
            else:
                command = f"cat {path}"
            return f"{command}\n{content or ''}"
        if tool_name == "search":
            result = vm.search(
                SearchRequest(
                    root=arguments.get("root", "/"),
                    pattern=arguments.get("pattern", ""),
                    limit=arguments.get("limit", 10),
                )
            )
            body = "\n".join(
                f"{match.path}:{match.line}:{match.line_text}" for match in result.matches
            )
            root = shlex.quote(arguments.get("root", "/"))
            pattern = shlex.quote(arguments.get("pattern", ""))
            return f"rg -n --no-heading -e {pattern} {root}\n{body}"
        if tool_name == "find":
            result = vm.find(
                FindRequest(
                    root=arguments.get("root", "/"),
                    name=arguments.get("name", ""),
                    type={"all": 0, "files": 1, "dirs": 2}[arguments.get("kind", "all")],
                    limit=arguments.get("limit", 10),
                )
            )
            return json.dumps(MessageToDict(result), indent=2)
        if tool_name == "write":
            result = vm.write(
                WriteRequest(
                    path=arguments.get("path", ""),
                    content=arguments.get("content", ""),
                    start_line=arguments.get("start_line", 0),
                    end_line=arguments.get("end_line", 0),
                )
            )
            return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'
        if tool_name == "delete":
            result = vm.delete(DeleteRequest(path=arguments.get("path", "")))
            return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'
        if tool_name == "mkdir":
            result = vm.mk_dir(MkDirRequest(path=arguments.get("path", "")))
            return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'
        if tool_name == "move":
            result = vm.move(
                MoveRequest(
                    from_name=arguments.get("from_name", ""),
                    to_name=arguments.get("to_name", ""),
                )
            )
            return json.dumps(MessageToDict(result), indent=2) if result else '{"status": "ok"}'
        if tool_name == "report_completion":
            outcome_map = get_outcome_map()
            vm.answer(
                AnswerRequest(
                    message=arguments.get("message", ""),
                    outcome=outcome_map[arguments.get("outcome", "OUTCOME_ERR_INTERNAL")],
                    refs=arguments.get("grounding_refs", []),
                )
            )
            return json.dumps(
                {
                    "status": "reported",
                    "outcome": arguments.get("outcome", "OUTCOME_ERR_INTERNAL"),
                },
                indent=2,
            )
        return json.dumps({"error": f"Unknown tool: {tool_name}"}, indent=2)
    except ConnectError as exc:
        return f"ERROR: {exc.message}"
    except Exception as exc:
        return f"ERROR: {exc}"


def extract_candidate_path(tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
    if tool_name in {"read", "cat", "write", "delete"}:
        return arguments.get("path")
    if tool_name in {"list", "ls"}:
        return arguments.get("path")
    if tool_name == "tree":
        return arguments.get("root")
    if tool_name == "move":
        return arguments.get("from_name")
    return None


def parent_dir(path: str) -> str:
    normalized = (path or "").replace("\\", "/")
    pure = PurePosixPath(normalized)
    parent = str(pure.parent)
    return "." if parent == "" else parent
