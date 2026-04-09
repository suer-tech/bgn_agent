#!/usr/bin/env python3
"""
BitGN Benchmark Task Extractor

Extracts tasks from BitGN benchmarks with full workspace data.
For each task, creates a separate folder containing:
- instruction.txt: The task question/instruction
- workspace_tree.md: Directory structure visualization
- files/: All files from the workspace with their contents
"""

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    GetBenchmarkRequest,
    StartPlaygroundRequest,
    StatusRequest,
)
from connectrpc.errors import ConnectError

# Import both runtime clients - we'll detect which one to use
try:
    from bitgn.vm.mini_connect import MiniRuntimeClientSync
    from bitgn.vm.mini_pb2 import (
        ListRequest as MiniListRequest,
        OutlineRequest,
        ReadRequest as MiniReadRequest,
    )

    MINI_AVAILABLE = True
except ImportError:
    MINI_AVAILABLE = False

try:
    from bitgn.vm.pcm_connect import PcmRuntimeClientSync
    from bitgn.vm.pcm_pb2 import (
        ListRequest as PcmListRequest,
        ReadRequest as PcmReadRequest,
        TreeRequest,
    )

    PCM_AVAILABLE = True
except ImportError:
    PCM_AVAILABLE = False

BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
OUTPUT_DIR = os.getenv("OUTPUT_DIR") or "extracted_tasks"

CLI_RED = "\x1b[31m"
CLI_GREEN = "\x1b[32m"
CLI_CLR = "\x1b[0m"
CLI_BLUE = "\x1b[34m"
CLI_YELLOW = "\x1b[33m"


def format_tree_entry(entry, prefix: str = "", is_last: bool = True) -> list[str]:
    """Format a tree entry for display."""
    branch = "└── " if is_last else "├── "
    lines = [f"{prefix}{branch}{entry.name}"]
    child_prefix = f"{prefix}{'    ' if is_last else '│   '}"
    children = list(entry.children)
    for idx, child in enumerate(children):
        lines.extend(
            format_tree_entry(
                child,
                prefix=child_prefix,
                is_last=idx == len(children) - 1,
            )
        )
    return lines


def explore_mini_runtime(
    vm: MiniRuntimeClientSync, path: str = "/", depth: int = 0, max_depth: int = 5
) -> dict:
    """Recursively explore mini runtime workspace."""
    result = {"path": path, "is_dir": True, "children": []}

    try:
        outline = vm.outline(OutlineRequest(path=path))
        result["folders"] = list(outline.folders)
        result["files"] = []

        # Get file contents
        for file_outline in outline.files:
            file_path = file_outline.path

            # Construct full path if relative
            if not file_path.startswith("/") and path != "/":
                full_file_path = f"{path.rstrip('/')}/{file_path}"
            elif not file_path.startswith("/"):
                full_file_path = f"/{file_path}"
            else:
                full_file_path = file_path

            result["files"].append(
                {
                    "path": full_file_path,
                    "relative_path": file_path,
                    "headers": list(file_outline.headers),
                }
            )

            # Read file content
            if depth < max_depth:
                try:
                    read_result = vm.read(MiniReadRequest(path=full_file_path))
                    result["files"][-1]["content"] = read_result.content
                except ConnectError as e:
                    # Try with relative path as fallback
                    try:
                        read_result = vm.read(MiniReadRequest(path=file_path))
                        result["files"][-1]["content"] = read_result.content
                        result["files"][-1]["read_path"] = file_path
                    except:
                        error_msg = f"[Error reading: {e.code}: {e.message}]"
                        result["files"][-1]["content"] = error_msg
                        result["files"][-1]["error"] = True
                        result["files"][-1]["error_code"] = str(e.code)
                        result["files"][-1]["error_message"] = e.message
                        result["files"][-1]["tried_paths"] = [full_file_path, file_path]
                except Exception as e:
                    error_msg = f"[Error reading: {e}]"
                    result["files"][-1]["content"] = error_msg
                    result["files"][-1]["error"] = True
                    result["files"][-1]["error_code"] = "UNKNOWN"
                    result["files"][-1]["error_message"] = str(e)

        # Explore subfolders
        if depth < max_depth:
            for folder in outline.folders:
                folder_path = (
                    f"{path.rstrip('/')}/{folder}" if path != "/" else f"/{folder}"
                )
                child = explore_mini_runtime(vm, folder_path, depth + 1, max_depth)
                result["children"].append(child)

    except Exception as e:
        result["error"] = str(e)

    return result


def explore_pcm_runtime(
    vm: PcmRuntimeClientSync, path: str = "/", depth: int = 0, max_depth: int = 5
) -> dict:
    """Recursively explore pcm runtime workspace."""
    result = {"path": path, "is_dir": True, "children": []}

    try:
        # Get tree structure
        tree = vm.tree(TreeRequest(root=path, level=1))
        root = tree.root

        if root.is_dir:
            result["folders"] = []
            result["files"] = []

            for child in root.children:
                child_path = (
                    f"{path.rstrip('/')}/{child.name}"
                    if path != "/"
                    else f"/{child.name}"
                )

                if child.is_dir:
                    result["folders"].append(child.name)
                    # Recursively explore subdirectory
                    if depth < max_depth:
                        child_result = explore_pcm_runtime(
                            vm, child_path, depth + 1, max_depth
                        )
                        result["children"].append(child_result)
                else:
                    result["files"].append({"path": child_path, "name": child.name})

                    # Read file content
                    if depth < max_depth:
                        try:
                            read_result = vm.read(PcmReadRequest(path=child_path))
                            result["files"][-1]["content"] = read_result.content
                        except ConnectError as e:
                            # Try with just the filename as fallback
                            try:
                                read_result = vm.read(PcmReadRequest(path=child.name))
                                result["files"][-1]["content"] = read_result.content
                                result["files"][-1]["read_path"] = child.name
                            except:
                                error_msg = f"[Error reading: {e.code}: {e.message}]"
                                result["files"][-1]["content"] = error_msg
                                result["files"][-1]["error"] = True
                                result["files"][-1]["error_code"] = str(e.code)
                                result["files"][-1]["error_message"] = e.message
                                result["files"][-1]["tried_paths"] = [
                                    child_path,
                                    child.name,
                                ]
                        except Exception as e:
                            error_msg = f"[Error reading: {e}]"
                            result["files"][-1]["content"] = error_msg
                            result["files"][-1]["error"] = True
                            result["files"][-1]["error_code"] = "UNKNOWN"
                            result["files"][-1]["error_message"] = str(e)
        else:
            # It's a file, read it
            result["is_dir"] = False
            try:
                read_result = vm.read(PcmReadRequest(path=path))
                result["content"] = read_result.content
            except ConnectError as e:
                error_msg = f"[Error reading: {e.code}: {e.message}]"
                result["content"] = error_msg
                result["error"] = True
                result["error_code"] = str(e.code)
                result["error_message"] = e.message
            except Exception as e:
                error_msg = f"[Error reading: {e}]"
                result["content"] = error_msg
                result["error"] = True
                result["error_code"] = "UNKNOWN"
                result["error_message"] = str(e)

    except Exception as e:
        result["error"] = str(e)

    return result


def save_task_data(
    task_id: str, instruction: str, workspace_data: dict, output_base: str
):
    """Save task data to organized folder structure."""
    task_dir = Path(output_base) / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # Save instruction
    instruction_file = task_dir / "instruction.txt"
    instruction_file.write_text(instruction, encoding="utf-8")

    # Save workspace structure
    tree_file = task_dir / "workspace_tree.md"
    tree_content = generate_tree_markdown(workspace_data)
    tree_file.write_text(tree_content, encoding="utf-8")

    # Save files
    files_dir = task_dir / "files"
    files_dir.mkdir(exist_ok=True)

    # Save metadata
    metadata = {
        "task_id": task_id,
        "instruction": instruction,
        "workspace_structure": workspace_data,
    }
    metadata_file = task_dir / "metadata.json"
    metadata_file.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Save individual files
    save_files_recursive(workspace_data, files_dir)

    return task_dir


def generate_tree_markdown(data: dict, prefix: str = "", is_root: bool = True) -> str:
    """Generate markdown representation of workspace tree."""
    lines = []

    if is_root:
        lines.append("# Workspace Structure\n")
        lines.append(f"Root: {data.get('path', '/')}\n")

    # Add folders
    folders = data.get("folders", [])
    files = data.get("files", [])

    for i, folder in enumerate(folders):
        is_last_folder = i == len(folders) - 1 and len(files) == 0
        branch = "└── " if is_last_folder else "├── "
        lines.append(f"{prefix}{branch}📁 {folder}/")

        # Find child data for this folder
        child_prefix = f"{prefix}{'    ' if is_last_folder else '│   '}"
        for child in data.get("children", []):
            if (
                child.get("path", "").endswith(f"/{folder}")
                or child.get("path", "") == f"/{folder}"
            ):
                child_lines = generate_tree_markdown(child, child_prefix, False)
                if child_lines:
                    lines.append(child_lines)

    # Add files
    for i, file in enumerate(files):
        is_last = i == len(files) - 1
        branch = "└── " if is_last else "├── "
        file_name = file.get("name") or file.get("path", "").split("/")[-1]
        lines.append(f"{prefix}{branch}📄 {file_name}")

    return "\n".join(lines)


def save_files_recursive(data: dict, base_dir: Path, current_path: str = ""):
    """Recursively save files from workspace data."""
    # Save files in current directory
    for file in data.get("files", []):
        file_path = file.get("path", "")
        if not file_path:
            continue

        # Normalize path
        if file_path.startswith("/"):
            file_path = file_path[1:]

        full_path = base_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        content = file.get("content", "")
        if content:
            try:
                # Add error comment if file had read error
                if file.get("error"):
                    content = f"<!-- ⚠️ Ошибка чтения из BitGN runtime -->\n<!-- {content} -->\n<!-- Файл не удалось прочитать во время извлечения -->\n"
                full_path.write_text(content, encoding="utf-8")
            except Exception as e:
                print(f"  {CLI_RED}Error saving {file_path}: {e}{CLI_CLR}")

    # Recursively save files from children
    for child in data.get("children", []):
        save_files_recursive(child, base_dir)


def detect_runtime_type(harness_url: str) -> str:
    """Detect whether this is a mini or pcm runtime."""
    if "mini" in harness_url.lower() or "demo" in harness_url.lower():
        return "mini"
    elif "pcm" in harness_url.lower():
        return "pcm"
    else:
        # Try to detect by attempting to connect
        if MINI_AVAILABLE:
            try:
                vm = MiniRuntimeClientSync(harness_url)
                vm.outline(OutlineRequest(path="/"))
                return "mini"
            except:
                pass
        if PCM_AVAILABLE:
            try:
                vm = PcmRuntimeClientSync(harness_url)
                vm.tree(TreeRequest(root="/", level=1))
                return "pcm"
            except:
                pass
    return "unknown"


def extract_benchmark_tasks(
    benchmark_id: str,
    task_filter: Optional[list[str]] = None,
    output_dir: str = OUTPUT_DIR,
    max_depth: int = 3,
):
    """Extract all tasks from a benchmark."""
    print(f"{CLI_BLUE}Connecting to BitGN at {BITGN_URL}{CLI_CLR}")

    try:
        client = HarnessServiceClientSync(BITGN_URL)
        status = client.status(StatusRequest())
        print(f"Connected: {status.status} (version: {status.version})")

        # Get benchmark info
        res = client.get_benchmark(GetBenchmarkRequest(benchmark_id=benchmark_id))
        print(
            f"\nBenchmark: {res.benchmark_id}"
            f"\nHarness: {res.harness_id}"
            f"\nTasks: {len(res.tasks)}"
        )
        if res.description:
            print(f"Description: {res.description}")

        # Create output directory
        output_base = Path(output_dir) / benchmark_id.replace("/", "_")
        output_base.mkdir(parents=True, exist_ok=True)

        # Save benchmark info
        benchmark_info = {
            "benchmark_id": res.benchmark_id,
            "description": res.description,
            "harness_id": res.harness_id,
            "policy": res.policy,
            "tasks": [
                {"task_id": t.task_id, "preview": t.preview, "hint": t.hint}
                for t in res.tasks
            ],
        }
        (output_base / "benchmark_info.json").write_text(
            json.dumps(benchmark_info, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        extracted_count = 0
        for task in res.tasks:
            if task_filter and task.task_id not in task_filter:
                continue

            print(f"\n{'=' * 60}")
            print(f"{CLI_YELLOW}Extracting task: {task.task_id}{CLI_CLR}")
            print(f"{'=' * 60}")

            try:
                # Start playground trial
                trial = client.start_playground(
                    StartPlaygroundRequest(
                        benchmark_id=benchmark_id,
                        task_id=task.task_id,
                    )
                )

                print(f"Trial ID: {trial.trial_id}")
                print(f"Instruction:\n{CLI_GREEN}{trial.instruction}{CLI_CLR}")

                # Detect runtime type
                runtime_type = detect_runtime_type(trial.harness_url)
                print(f"Runtime type: {runtime_type}")

                # Explore workspace based on runtime type
                workspace_data = {}

                if runtime_type == "mini" and MINI_AVAILABLE:
                    print(f"Exploring mini runtime workspace...")
                    vm = MiniRuntimeClientSync(trial.harness_url)
                    workspace_data = explore_mini_runtime(vm, "/", max_depth=max_depth)
                elif runtime_type == "pcm" and PCM_AVAILABLE:
                    print(f"Exploring pcm runtime workspace...")
                    vm = PcmRuntimeClientSync(trial.harness_url)
                    workspace_data = explore_pcm_runtime(vm, "/", max_depth=max_depth)
                else:
                    print(
                        f"{CLI_YELLOW}Unknown runtime type, attempting both...{CLI_CLR}"
                    )
                    if MINI_AVAILABLE:
                        try:
                            vm = MiniRuntimeClientSync(trial.harness_url)
                            workspace_data = explore_mini_runtime(
                                vm, "/", max_depth=max_depth
                            )
                            runtime_type = "mini"
                        except:
                            pass
                    if not workspace_data and PCM_AVAILABLE:
                        try:
                            vm = PcmRuntimeClientSync(trial.harness_url)
                            workspace_data = explore_pcm_runtime(
                                vm, "/", max_depth=max_depth
                            )
                            runtime_type = "pcm"
                        except:
                            pass

                if workspace_data:
                    # Save task data
                    task_dir = save_task_data(
                        task.task_id,
                        trial.instruction,
                        workspace_data,
                        str(output_base),
                    )
                    print(f"{CLI_GREEN}Saved to: {task_dir}{CLI_CLR}")
                    extracted_count += 1
                else:
                    print(
                        f"{CLI_RED}Could not explore workspace for task {task.task_id}{CLI_CLR}"
                    )

            except Exception as e:
                print(f"{CLI_RED}Error extracting task {task.task_id}: {e}{CLI_CLR}")
                import traceback

                traceback.print_exc()

        # Create summary file
        summary_file = output_base / "SUMMARY.md"
        summary_content = f"# {benchmark_id} - Extracted Tasks\n\n"
        summary_content += f"Total tasks: {len(res.tasks)}\n"
        summary_content += f"Extracted: {extracted_count}\n\n"
        summary_content += "## Tasks\n\n"
        summary_content += "| Task ID | Instruction | Preview | Hint |\n"
        summary_content += "|---------|-------------|---------|------|\n"

        for task in res.tasks:
            task_dir = output_base / task.task_id
            instruction_file = task_dir / "instruction.txt"
            if instruction_file.exists():
                instruction = instruction_file.read_text(encoding="utf-8").split("\n")[
                    0
                ][:100]
                preview = task.preview[:50] if task.preview else ""
                hint = task.hint[:50] if task.hint else ""
                summary_content += (
                    f"| {task.task_id} | {instruction} | {preview} | {hint} |\n"
                )

        summary_file.write_text(summary_content, encoding="utf-8")
        print(f"\n{CLI_GREEN}Summary saved to: {summary_file}{CLI_CLR}")

        print(
            f"\n{CLI_GREEN}Extraction complete! {extracted_count} tasks extracted to {output_base}{CLI_CLR}"
        )
        return extracted_count

    except ConnectError as e:
        print(f"{CLI_RED}Connection error: {e.code}: {e.message}{CLI_CLR}")
        return 0
    except KeyboardInterrupt:
        print(f"\n{CLI_RED}Interrupted by user{CLI_CLR}")
        return 0


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract BitGN benchmark tasks with workspace data"
    )
    parser.add_argument(
        "benchmark",
        nargs="?",
        default="bitgn/sandbox",
        help="Benchmark ID (default: bitgn/sandbox)",
    )
    parser.add_argument(
        "--tasks",
        nargs="*",
        help="Specific task IDs to extract (default: all)",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=3,
        help="Maximum directory traversal depth (default: 3)",
    )

    args = parser.parse_args()

    # Fix Windows console encoding for Unicode output
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    print(f"{CLI_BLUE}BitGN Benchmark Task Extractor{CLI_CLR}")
    print(f"Benchmark: {args.benchmark}")
    print(f"Output: {args.output}")
    print(f"Max depth: {args.depth}")
    print()

    count = extract_benchmark_tasks(
        benchmark_id=args.benchmark,
        task_filter=args.tasks,
        output_dir=args.output,
        max_depth=args.depth,
    )

    sys.exit(0 if count > 0 else 1)


if __name__ == "__main__":
    main()
