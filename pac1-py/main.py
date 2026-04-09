import os
import sys
import textwrap

from dotenv import load_dotenv

load_dotenv()

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    EndTrialRequest,
    EvalPolicy,
    GetBenchmarkRequest,
    StartPlaygroundRequest,
    StartRunRequest,
    StartTrialRequest,
    SubmitRunRequest,
    StatusRequest,
)
from connectrpc.errors import ConnectError

from google.protobuf.json_format import MessageToDict

BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
BITGN_API_KEY = os.getenv("BITGN_API_KEY") or ""
BENCHMARK_ID = os.getenv("BENCHMARK_ID") or "bitgn/pac1-dev"
MODEL_ID = os.getenv("MODEL_ID") or "gpt-4.1-2025-04-14"
AGENT_NAME = os.getenv("AGENT_NAME") or "Suer Multi-Agent"

CLI_RED = "\x1b[31m"
CLI_GREEN = "\x1b[32m"
CLI_YELLOW = "\x1b[33m"
CLI_BLUE = "\x1b[34m"
CLI_CYAN = "\x1b[36m"
CLI_CLR = "\x1b[0m"


def _auth_headers() -> dict:
    """Build auth headers for BitGN API. Returns empty dict if no key configured."""
    if BITGN_API_KEY:
        return {
            "Authorization": f"Bearer {BITGN_API_KEY}",
            "x-api-key": BITGN_API_KEY,
        }
    return {}


def run_task(
    model: str, harness_url: str, task_text: str, task_id: str = ""
) -> dict:
    """Run agent using the State Machine orchestrator.

    Returns dict with: trace_logger, orchestrator_result, provider_stats.
    """
    from orchestrator import Orchestrator
    from llm_logger import LLMTraceLogger
    from llm_provider import create_provider

    provider = create_provider()
    trace_logger = LLMTraceLogger()
    orchestrator = Orchestrator(provider=provider, trace_logger=trace_logger)
    result = orchestrator.run(
        harness_url=harness_url,
        task_text=task_text,
        task_id=task_id,
    )

    print(f"\n{CLI_BLUE}[{task_id}] Orchestrator Result:{CLI_CLR}")
    print(f"  Status: {result['status']}")
    print(f"  Outcome: {result['outcome']}")
    print(f"  Answer: {result['final_answer'][:200]}...")
    print(f"  Iterations: {result['iterations_used']}")
    print(f"  Duration: {result['duration_seconds']:.2f}s")
    print(f"  LLM calls: {provider.stats['llm_calls']}")
    print(f"  Tokens: {provider.stats['total_tokens']} (prompt: {provider.stats['prompt_tokens']}, completion: {provider.stats['completion_tokens']})")

    return {
        "trace_logger": trace_logger,
        "orchestrator_result": result,
        "provider_stats": dict(provider.stats),
    }


def run_task_wrapper(task_info):
    """Wrapper to run a single task (trial). Works in both threads and processes.

    task_info is a tuple: (trial_id, bitgn_url, model_id)
    For playground mode: (task_dict, benchmark_id, bitgn_url, model_id)

    Returns: dict with task_id, score, score_detail, duration, llm_calls, tokens, iterations, outcome.
    """
    import sys
    import io
    import traceback
    import time as _time

    headers = _auth_headers()

    # Detect mode: run-based (trial_id) or playground-based (task_dict)
    if isinstance(task_info[0], str):
        # Run mode: (trial_id, bitgn_url, model_id)
        trial_id, bitgn_url, model_id = task_info
        mode = "run"
    else:
        # Playground mode (legacy): (task_dict, benchmark_id, bitgn_url, model_id)
        task_dict, benchmark_id, bitgn_url, model_id = task_info
        trial_id = None
        mode = "playground"

    task_result = {
        "task_id": "",
        "score": -1,
        "score_detail": [],
        "duration_seconds": 0,
        "llm_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "iterations": 0,
        "outcome": "ERROR",
    }
    wall_start = _time.time()

    from bitgn.harness_connect import HarnessServiceClientSync
    from bitgn.harness_pb2 import (
        StartPlaygroundRequest,
        StartTrialRequest,
        EndTrialRequest,
    )

    client = HarnessServiceClientSync(bitgn_url)

    # Start trial
    try:
        if mode == "run":
            trial = client.start_trial(
                StartTrialRequest(trial_id=trial_id),
                headers=headers,
            )
            task_id = trial.task_id
        else:
            task_id = task_dict["task_id"]
            trial = client.start_playground(
                StartPlaygroundRequest(benchmark_id=benchmark_id, task_id=task_id),
                headers=headers,
            )
    except Exception as exc:
        task_id = trial_id or (task_dict.get("task_id", "?") if mode == "playground" else "?")
        print(f"[{task_id}] Failed to start trial: {exc}", flush=True)
        task_result["task_id"] = task_id
        task_result["duration_seconds"] = _time.time() - wall_start
        return task_result

    task_result["task_id"] = task_id
    os.environ["PAC1_TASK_ID"] = task_id

    print(f"{'=' * 30} Starting task: {task_id} {'=' * 30}", flush=True)
    print(f"[{task_id}] Harness URL: {trial.harness_url}", flush=True)

    run_result = None
    try:
        run_result = run_task(
            model_id,
            trial.harness_url,
            trial.instruction,
            task_id=task_id,
        )
    except Exception as exc:
        print(f"[{task_id}] Error: {exc}", flush=True)
        traceback.print_exc()

    try:
        result = client.end_trial(
            EndTrialRequest(trial_id=trial.trial_id),
            headers=headers,
        )
    except Exception as exc:
        print(f"[{task_id}] Failed to end trial: {exc}", flush=True)
        task_result["duration_seconds"] = _time.time() - wall_start
        return task_result

    # Fill stats from run
    task_result["score"] = result.score
    task_result["score_detail"] = list(result.score_detail)
    task_result["duration_seconds"] = _time.time() - wall_start

    if run_result:
        orch = run_result["orchestrator_result"]
        stats = run_result["provider_stats"]
        task_result["iterations"] = orch.get("iterations_used", 0)
        task_result["outcome"] = orch.get("outcome", "UNKNOWN")
        task_result["llm_calls"] = stats.get("llm_calls", 0)
        task_result["prompt_tokens"] = stats.get("prompt_tokens", 0)
        task_result["completion_tokens"] = stats.get("completion_tokens", 0)
        task_result["total_tokens"] = stats.get("total_tokens", 0)

        # Write task summary
        trace_logger = run_result["trace_logger"]
        try:
            score_detail_str = "\n".join(result.score_detail) if result.score_detail else ""
            trace_logger.write_task_summary(
                score=result.score if result.score >= 0 else None,
                score_detail=score_detail_str,
                error="" if result.score >= 0 else "Low score",
            )
        except Exception as e:
            print(f"[{task_id}] Failed to write summary: {e}", flush=True)

    return task_result


def _save_run_stats(all_results: list, run_start: float) -> str:
    """Save run statistics to a JSON file in logs/. Returns the file path."""
    import json
    import time
    from datetime import datetime
    from pathlib import Path

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stats_path = logs_dir / f"run_stats_{ts}.json"

    # Sort by task_id for readability
    all_results.sort(key=lambda r: r["task_id"])

    scored = [r for r in all_results if r["score"] >= 0]
    avg_score = sum(r["score"] for r in scored) / len(scored) if scored else 0
    total_tokens = sum(r["total_tokens"] for r in all_results)
    total_llm_calls = sum(r["llm_calls"] for r in all_results)
    total_duration = time.time() - run_start

    run_data = {
        "run_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": os.getenv("LLM_MODEL", "unknown"),
        "provider": os.getenv("LLM_PROVIDER", "unknown"),
        "parallel_limit": int(os.getenv("PAC1_PARALLEL_LIMIT", "1")),
        "benchmark_id": BENCHMARK_ID,
        "summary": {
            "tasks_total": len(all_results),
            "tasks_scored": len(scored),
            "average_score": round(avg_score, 4),
            "total_wall_time_seconds": round(total_duration, 2),
            "total_llm_calls": total_llm_calls,
            "total_prompt_tokens": sum(r["prompt_tokens"] for r in all_results),
            "total_completion_tokens": sum(r["completion_tokens"] for r in all_results),
            "total_tokens": total_tokens,
        },
        "tasks": [
            {
                "task_id": r["task_id"],
                "score": r["score"],
                "outcome": r["outcome"],
                "duration_seconds": round(r["duration_seconds"], 2),
                "iterations": r["iterations"],
                "llm_calls": r["llm_calls"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "total_tokens": r["total_tokens"],
                "score_detail": r["score_detail"],
            }
            for r in all_results
        ],
    }

    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(run_data, f, indent=2, ensure_ascii=False)

    return str(stats_path)


def _print_stats_table(all_results: list) -> None:
    """Print a summary table to console."""
    # Header
    print(f"\n{'=' * 100}")
    print(f"{'Task':<8} {'Score':>6} {'Outcome':<28} {'Time':>8} {'Iters':>6} {'LLM':>5} {'Tokens':>10}")
    print(f"{'-' * 100}")

    all_results.sort(key=lambda r: r["task_id"])
    for r in all_results:
        score_str = f"{r['score']:.2f}" if r['score'] >= 0 else "ERR"
        style = CLI_GREEN if r['score'] == 1 else (CLI_RED if r['score'] >= 0 else CLI_RED)
        time_str = f"{r['duration_seconds']:.1f}s"
        token_str = f"{r['total_tokens']:,}" if r['total_tokens'] > 0 else "-"
        print(
            f"{style}{r['task_id']:<8} {score_str:>6} {r['outcome']:<28} "
            f"{time_str:>8} {r['iterations']:>6} {r['llm_calls']:>5} {token_str:>10}{CLI_CLR}"
        )

    # Totals
    scored = [r for r in all_results if r['score'] >= 0]
    total_tokens = sum(r['total_tokens'] for r in all_results)
    total_llm = sum(r['llm_calls'] for r in all_results)
    total_iters = sum(r['iterations'] for r in all_results)
    avg_score = sum(r['score'] for r in scored) / len(scored) * 100 if scored else 0

    print(f"{'-' * 100}")
    token_total_str = f"{total_tokens:,}" if total_tokens > 0 else "-"
    print(
        f"{'TOTAL':<8} {avg_score:>5.1f}% {len(scored)}/{len(all_results)} scored"
        f"{'':>16} {total_iters:>6} {total_llm:>5} {token_total_str:>10}"
    )
    print(f"{'=' * 100}\n")


def main() -> None:
    import time as _time

    # Force UTF-8 for Windows terminals
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    task_filter = sys.argv[1:]
    parallel_limit = int(os.getenv("PAC1_PARALLEL_LIMIT", "1"))
    run_start = _time.time()

    all_results = []
    headers = _auth_headers()

    try:
        print(f"[{BITGN_URL}] Connecting to BitGN Service...", flush=True)
        client = HarnessServiceClientSync(BITGN_URL)

        status = client.status(StatusRequest(), headers=headers)
        print(f"BitGN STATUS: {status}", flush=True)

        print(f"Fetching benchmark: {BENCHMARK_ID}...", flush=True)
        res = client.get_benchmark(
            GetBenchmarkRequest(benchmark_id=BENCHMARK_ID),
            headers=headers,
        )

        print(
            f"{EvalPolicy.Name(res.policy)} benchmark: {res.benchmark_id} "
            f"with {len(res.tasks)} tasks.\n{CLI_GREEN}{res.description}{CLI_CLR}",
            flush=True
        )

        # ── Decide mode: Run-based (with API key) or Playground-based (legacy) ──
        use_run_mode = bool(BITGN_API_KEY)
        run_id = None

        if use_run_mode:
            try:
                # Run mode: StartRun → get trial_ids → StartTrial per task
                print(f"{CLI_BLUE}Starting run '{AGENT_NAME}' (authenticated)...{CLI_CLR}", flush=True)
                run = client.start_run(
                    StartRunRequest(benchmark_id=BENCHMARK_ID, name=AGENT_NAME),
                    headers=headers,
                )
                run_id = run.run_id
                print(f"{CLI_GREEN}Run started: {run_id} ({len(run.trial_ids)} trials){CLI_CLR}", flush=True)
                target_tasks = [(tid, BITGN_URL, MODEL_ID) for tid in run.trial_ids]
            except Exception as exc:
                print(f"{CLI_YELLOW}Warning: Run mode failed ({exc}). Falling back to Playground mode.{CLI_CLR}", flush=True)
                use_run_mode = False

        if not use_run_mode:
            # Playground mode (no API key or Run mode failed): StartPlayground per task
            target_tasks = []
            for task in res.tasks:
                if task_filter and task.task_id not in task_filter:
                    continue
                task_dict = MessageToDict(task, preserving_proto_field_name=True)
                target_tasks.append((task_dict, BENCHMARK_ID, BITGN_URL, MODEL_ID))

        if not target_tasks:
            print(f"{CLI_RED}No tasks found matching filter: {task_filter}{CLI_CLR}")
            return

        print(f"{CLI_BLUE}Running {len(target_tasks)} tasks (Parallel: {parallel_limit}){CLI_CLR}")

        # ── Execute tasks ──
        def _run_and_collect(task_info):
            task_result = run_task_wrapper(task_info)
            all_results.append(task_result)
            score = task_result["score"]
            tid = task_result["task_id"]
            if score >= 0:
                style = CLI_GREEN if score == 1 else CLI_RED
                explain = textwrap.indent("\n".join(task_result["score_detail"]), "  ")
                print(f"\n{CLI_BLUE}[{tid}]{CLI_CLR} {style}Score: {score:0.2f}\n{explain}{CLI_CLR}")
            else:
                print(f"\n{CLI_RED}[{tid}] Score: {score} (error){CLI_CLR}")

        try:
            if parallel_limit > 1:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                with ThreadPoolExecutor(max_workers=parallel_limit) as executor:
                    futures = {
                        executor.submit(run_task_wrapper, ti): str(ti[0])[:20]
                        for ti in target_tasks
                    }
                    for future in as_completed(futures):
                        label = futures[future]
                        try:
                            task_result = future.result()
                        except Exception as exc:
                            print(f"\n{CLI_RED}[{label}] CRASHED: {exc}{CLI_CLR}")
                            all_results.append({
                                "task_id": label, "score": -1, "score_detail": [str(exc)],
                                "duration_seconds": 0, "llm_calls": 0, "prompt_tokens": 0,
                                "completion_tokens": 0, "total_tokens": 0, "iterations": 0, "outcome": "CRASH",
                            })
                            continue
                        all_results.append(task_result)
                        score = task_result["score"]
                        tid = task_result["task_id"]
                        if score >= 0:
                            style = CLI_GREEN if score == 1 else CLI_RED
                            explain = textwrap.indent("\n".join(task_result["score_detail"]), "  ")
                            print(f"\n{CLI_BLUE}[{tid}]{CLI_CLR} {style}Score: {score:0.2f}\n{explain}{CLI_CLR}")
                        else:
                            print(f"\n{CLI_RED}[{tid}] Score: {score} (error){CLI_CLR}")
            else:
                for task_info in target_tasks:
                    _run_and_collect(task_info)

        finally:
            # ── Submit run if in run mode ──
            if run_id:
                try:
                    client.submit_run(
                        SubmitRunRequest(run_id=run_id, force=True),
                        headers=headers,
                    )
                    print(f"{CLI_GREEN}Run submitted: {run_id}{CLI_CLR}", flush=True)
                except Exception as e:
                    print(f"{CLI_RED}Failed to submit run: {e}{CLI_CLR}", flush=True)

    except Exception as exc:
        print(f"Main Loop Error: {exc}")
    except KeyboardInterrupt:
        print(f"{CLI_RED}Interrupted{CLI_CLR}")

    # Print summary table and save stats
    if all_results:
        _print_stats_table(all_results)
        stats_file = _save_run_stats(all_results, run_start)
        print(f"{CLI_GREEN}Stats saved to: {stats_file}{CLI_CLR}")


if __name__ == "__main__":
    main()
