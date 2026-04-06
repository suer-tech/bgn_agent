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
    StatusRequest,
)
from connectrpc.errors import ConnectError

BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
BENCHMARK_ID = os.getenv("BENCHMARK_ID") or "bitgn/pac1-dev"
MODEL_ID = os.getenv("MODEL_ID") or "gpt-4.1-2025-04-14"

CLI_RED = "\x1b[31m"
CLI_GREEN = "\x1b[32m"
CLI_CLR = "\x1b[0m"
CLI_BLUE = "\x1b[34m"


def run_task(
    model: str, harness_url: str, task_text: str, task_id: str = ""
) -> "LLMTraceLogger":
    """Run agent using the State Machine orchestrator."""
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

    print(f"\n{CLI_BLUE}Orchestrator Result:{CLI_CLR}")
    print(f"  Status: {result['status']}")
    print(f"  Outcome: {result['outcome']}")
    print(f"  Answer: {result['final_answer'][:200]}...")
    print(f"  Iterations: {result['iterations_used']}")
    print(f"  Duration: {result['duration_seconds']:.2f}s")

    return trace_logger


def main() -> None:
    task_filter = os.sys.argv[1:]

    scores = []
    try:
        print(f"[{BITGN_URL}] Connecting to BitGN Service...", flush=True)
        client = HarnessServiceClientSync(BITGN_URL)
        
        status = client.status(StatusRequest())
        print(f"BitGN STATUS: {status}", flush=True)

        print(f"Fetching benchmark: {BENCHMARK_ID}...", flush=True)
        res = client.get_benchmark(GetBenchmarkRequest(benchmark_id=BENCHMARK_ID))
        
        print(
            f"{EvalPolicy.Name(res.policy)} benchmark: {res.benchmark_id} "
            f"with {len(res.tasks)} tasks.\n{CLI_GREEN}{res.description}{CLI_CLR}",
            flush=True
        )

        print(f"{CLI_BLUE}Running in STATE MACHINE mode{CLI_CLR}")

        for task in res.tasks:
            if task_filter and task.task_id not in task_filter:
                continue

            print(f"{'=' * 30} Starting task: {task.task_id} {'=' * 30}", flush=True)
            print(f"Requesting playground from BitGN for {task.task_id}...", flush=True)
            
            trial = client.start_playground(
                StartPlaygroundRequest(
                    benchmark_id=BENCHMARK_ID,
                    task_id=task.task_id,
                )
            )

            print(f"Playground READY. Harness URL: {trial.harness_url}", flush=True)
            print(
                f"{CLI_BLUE}INSTRUCTION:{CLI_CLR}\n{trial.instruction.encode('utf-8', errors='replace').decode('utf-8')}\n{'-' * 80}",
                flush=True
            )

            trace_logger = None
            try:
                trace_logger = run_task(
                    MODEL_ID,
                    trial.harness_url,
                    trial.instruction,
                    task_id=task.task_id,
                )
            except Exception as exc:
                print(exc)

            result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))

            # Write task summary with score
            if trace_logger is not None:
                try:
                    score_detail_str = (
                        chr(10).join(result.score_detail) if result.score_detail else ""
                    )
                    trace_logger.write_task_summary(
                        score=result.score if result.score >= 0 else None,
                        score_detail=score_detail_str,
                        error="" if result.score >= 0 else "Low score",
                    )
                except Exception as e:
                    print(f"Failed to write summary: {e}")

            if result.score >= 0:
                scores.append((task.task_id, result.score))
                style = CLI_GREEN if result.score == 1 else CLI_RED
                explain = textwrap.indent("\n".join(result.score_detail), "  ")
                print(f"\n{style}Score: {result.score:0.2f}\n{explain}\n{CLI_CLR}")

    except ConnectError as exc:
        print(f"{exc.code}: {exc.message}")
    except KeyboardInterrupt:
        print(f"{CLI_RED}Interrupted{CLI_CLR}")

    if scores:
        for task_id, score in scores:
            style = CLI_GREEN if score == 1 else CLI_RED
            print(f"{task_id}: {style}{score:0.2f}{CLI_CLR}")

        total = sum(score for _, score in scores) / len(scores) * 100.0
        print(f"FINAL: {total:0.2f}%")


if __name__ == "__main__":
    main()
