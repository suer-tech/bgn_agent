import os
import sys
import textwrap

# Fix Windows console encoding for Unicode output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    StatusRequest,
    GetBenchmarkRequest,
    StartPlaygroundRequest,
    EvalPolicy,
    EndTrialRequest,
)
from connectrpc.errors import ConnectError

from self_evolution.executor import run_task_with_prompt
from orchestrator import Orchestrator
from agents.prompt_storage import get_prompt
from llm_provider import create_provider
from llm_logger import LLMTraceLogger

BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"

CLI_RED = "\x1b[31m"
CLI_GREEN = "\x1b[32m"
CLI_CLR = "\x1b[0m"
CLI_BLUE = "\x1b[34m"


def main() -> None:

    # optional task ids could be included as tasks to run, e.g. `python main.py task1 task2`
    task_filter = os.sys.argv[1:]

    provider = create_provider()

    scores = []
    try:
        client = HarnessServiceClientSync(BITGN_URL)
        print("Connecting to BitGN", client.status(StatusRequest()))
        res = client.get_benchmark(GetBenchmarkRequest(benchmark_id="bitgn/sandbox"))
        print(
            f"{EvalPolicy.Name(res.policy)} benchmark: {res.benchmark_id} with {len(res.tasks)} tasks.\n{CLI_GREEN}{res.description}{CLI_CLR}"
        )

        for t in res.tasks:
            if task_filter and t.task_id not in task_filter:
                continue
            print(f"{'=' * 30} Starting task: {t.task_id} {'=' * 30}")

            trial = client.start_playground(
                StartPlaygroundRequest(
                    benchmark_id="bitgn/sandbox",
                    task_id=t.task_id,
                )
            )

            print(f"{CLI_BLUE}{trial.instruction}{CLI_CLR}\n{'-' * 80}")

            try:
                trace_logger = LLMTraceLogger(
                    log_dir="logs/main",
                    keep_last_only=False,
                    per_task_files=True,
                )
                result = run_task_with_prompt(
                    provider=provider,
                    harness_url=trial.harness_url,
                    task_text=trial.instruction,
                    task_id=t.task_id,
                    system_prompt=get_prompt("execution_agent"),
                    max_iterations=30,
                    silent=False,
                    trace_logger=trace_logger,
                )
            except Exception as e:
                print(e)

            result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))

            if result.score >= 0:
                scores.append((t.task_id, result.score))

                style = CLI_GREEN if result.score == 1 else CLI_RED

                explain = textwrap.indent("\n".join(result.score_detail), "  ")
                print(f"\n{style}Score: {result.score:0.2f}\n{explain}\n{CLI_CLR}")

    except ConnectError as e:
        print(f"{e.code}: {e.message}")
    except KeyboardInterrupt:
        print(f"{CLI_RED}Interrupted{CLI_CLR}")

    # print scores as table
    if scores:
        for tid, score in scores:
            style = CLI_GREEN if score == 1 else CLI_RED
            print(f"{tid}: {style}{score:0.2f}{CLI_CLR}")

        # print average
        total = sum([t[1] for t in scores]) / len(scores) * 100.0
        print(f"FINAL: {total:0.2f}%")


if __name__ == "__main__":
    main()
