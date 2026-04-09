#!/usr/bin/env python3
"""Test script for self-evolving prompt with OpenRouter provider."""

import os
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

from self_evolution import (
    evolve_prompt,
    load_baseline_prompt,
    PromptStore,
    run_benchmark,
)
from llm_provider import OpenRouterProvider


def get_tasks_from_bitgn(count: int = 5):
    """Get tasks from BitGN sandbox benchmark."""
    from bitgn.harness_connect import HarnessServiceClientSync
    from bitgn.harness_pb2 import GetBenchmarkRequest, StartPlaygroundRequest

    BITGN_URL = os.getenv("BENCHMARK_HOST", "https://api.bitgn.com")
    client = HarnessServiceClientSync(BITGN_URL)

    print("Fetching benchmark tasks...")
    res = client.get_benchmark(GetBenchmarkRequest(benchmark_id="bitgn/sandbox"))
    print(f"Got {len(res.tasks)} total tasks")

    tasks = []
    for t in res.tasks[:count]:
        trial = client.start_playground(
            StartPlaygroundRequest(
                benchmark_id="bitgn/sandbox",
                task_id=t.task_id,
            )
        )
        tasks.append(
            {
                "id": t.task_id,
                "input": trial.instruction,
                "harness_url": trial.harness_url,
            }
        )
        print(f"  - {t.task_id}: {t.task_id[:50]}...")

    return tasks


def main():
    print("=" * 60)
    print("SELF-EVOLVING PROMPT TEST WITH OPENROUTER")
    print("=" * 60)

    # Get tasks
    tasks = get_tasks_from_bitgn(3)
    print(f"\nGot {len(tasks)} tasks for testing\n")

    # Create OpenRouter provider - use cheaper model for testing
    model = os.getenv("LLM_MODEL", "openai/gpt-4o")
    print(f"Using model: {model}")

    provider = OpenRouterProvider(model=model)
    print(f"Provider: {provider.__class__.__name__}")

    # Run baseline benchmark
    print("\n" + "=" * 60)
    print("Running baseline benchmark...")
    print("=" * 60)

    baseline = load_baseline_prompt()
    print(f"Using prompt v{baseline.version_id} ({len(baseline.system_prompt)} chars)")

    # Run benchmark for each task
    results = []
    for task in tasks:
        print(f"\n--- Task: {task['id']} ---")
        print(f"Instruction: {task['input'][:100]}...")

        from self_evolution.executor import run_task_with_prompt

        result = run_task_with_prompt(
            provider=provider,
            harness_url=task["harness_url"],
            task_text=task["input"],
            task_id=task["id"],
            system_prompt=baseline.system_prompt,
            max_iterations=20,
        )

        print(f"Status: {result.status}")
        print(f"Iterations: {result.iterations_used}")
        results.append(result)

        if result.status == "passed":
            print(f"✓ PASSED")
        else:
            print(f"✗ FAILED: {result.error_type}")
            print(f"Output: {result.output[:200]}...")

    # Calculate score
    passed = sum(1 for r in results if r.status == "passed")
    score = passed / len(results)
    print(f"\n{'=' * 60}")
    print(f"BASELINE SCORE: {score:.2%} ({passed}/{len(results)})")
    print(f"{'=' * 60}")

    print("\nTest completed!")
    print("To run full evolution, use evolve_prompt() with more tasks.")


if __name__ == "__main__":
    main()
