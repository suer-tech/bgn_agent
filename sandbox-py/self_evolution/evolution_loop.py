import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from self_evolution.analyzer import analyze_failures, format_suggestions
from self_evolution.executor import run_task_with_prompt
from self_evolution.prompt_store import PromptStore, load_baseline_prompt
from self_evolution.task_logger import TaskResult, task_logger


CLI_RED = "\x1b[31m"
CLI_GREEN = "\x1b[32m"
CLI_CLR = "\x1b[0m"
CLI_YELLOW = "\x1b[33m"
CLI_BLUE = "\x1b[34m"


def run_benchmark(
    provider: Any,
    harness_url: str,
    tasks: List[Dict[str, str]],  # [{"id": "...", "input": "..."}]
    system_prompt: str,
    max_iterations: int = 30,
    parallel: bool = False,
    workers: int = 5,
) -> List[TaskResult]:
    """
    Run benchmark with given system prompt.
    tasks: list of dicts with "id" and "input" keys
    """
    results: List[TaskResult] = []

    if parallel:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for task in tasks:
                future = executor.submit(
                    run_task_with_prompt,
                    provider,
                    harness_url,
                    task["input"],
                    task["id"],
                    system_prompt,
                    max_iterations,
                )
                futures.append(future)

            for future in tqdm(
                as_completed(futures), total=len(futures), desc="Running"
            ):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    print(f"Task error: {e}")
                    results.append(
                        TaskResult(
                            task_id=task.get("id", "unknown"),
                            input=task.get("input", ""),
                            output="",
                            status="error",
                            error_type="execution_error",
                        )
                    )
    else:
        for task in tqdm(tasks, desc="Running"):
            try:
                result = run_task_with_prompt(
                    provider,
                    harness_url,
                    task["input"],
                    task["id"],
                    system_prompt,
                    max_iterations,
                )
                results.append(result)
            except Exception as e:
                print(f"Task error: {e}")
                results.append(
                    TaskResult(
                        task_id=task.get("id", "unknown"),
                        input=task.get("input", ""),
                        output="",
                        status="error",
                        error_type="execution_error",
                    )
                )

    return results


def run_benchmark_parallel(
    provider: Any,
    harness_url: str,
    tasks: List[Dict[str, str]],
    system_prompt: str,
    max_iterations: int = 30,
    workers: int = 5,
) -> List[TaskResult]:
    """Parallel version of run_benchmark."""
    return run_benchmark(
        provider,
        harness_url,
        tasks,
        system_prompt,
        max_iterations,
        parallel=True,
        workers=workers,
    )


def evolve_prompt(
    provider: Any,
    harness_url: str,
    benchmark_tasks: List[Dict[str, str]],
    max_generations: int = 20,
    target_score: float = 0.70,
    max_iterations: int = 30,
    parallel: bool = True,
    workers: int = 5,
    regression_threshold: float = 0.05,
    use_holdout_validation: bool = True,
    holdout_ratio: float = 0.2,
) -> Optional[Any]:
    """
    Main self-evolution loop with overfitting protection.

    1. Load or create baseline prompt
    2. Split into train/holdout sets
    3. Run benchmark and collect results
    4. Analyzer finds failure patterns
    5. Versioner creates new version with validation
    6. Validate on holdout set
    7. Repeat until target_score or overfitting detected

    Returns best PromptVersion found.
    """
    from self_evolution.validation import OverfittingGuard, format_validation_report
    from self_evolution.evolution_log import evolution_logger, GenerationLog

    import time as time_module

    gen_start_time = time_module.time()

    print(f"\n{'=' * 60}")
    print("SELF-EVOLVING PROMPT PIPELINE (with Overfitting Guard)")
    print(f"{'=' * 60}")
    print(f"Tasks: {len(benchmark_tasks)}")
    print(f"Holdout validation: {use_holdout_validation} (ratio={holdout_ratio})")
    print(f"Target score: {target_score}")
    print(f"Max generations: {max_generations}")
    print(f"Parallel: {parallel} (workers={workers})")
    print(f"{'=' * 60}\n")

    # Initialize evolution logger
    evolution_logger.start_session(
        model_name=getattr(provider, "model", "unknown"),
        task_count=len(benchmark_tasks),
    )

    # Initialize overfitting guard
    guard = OverfittingGuard(holdout_ratio=holdout_ratio)

    # Split tasks if holdout validation enabled
    if use_holdout_validation and len(benchmark_tasks) >= 5:
        train_tasks, holdout_tasks = guard.split_train_holdout(benchmark_tasks)
        print(f"Train tasks: {len(train_tasks)}, Holdout tasks: {len(holdout_tasks)}")
    else:
        train_tasks = benchmark_tasks
        holdout_tasks = []
        print(f"All tasks: {len(train_tasks)} (holdout disabled - too few tasks)")

    # Load or create baseline
    store = PromptStore()
    current = load_baseline_prompt()
    print(f"Starting with version {current.version_id}")

    prev_score: Optional[float] = None
    best_version = current
    no_improvement_count = 0

    for gen in range(1, max_generations + 1):
        gen_start = time.time()
        print(f"\n=== Generation {gen} ===")
        print(f"Prompt version: {current.version_id}")

        # Run benchmark on TRAINING set
        print(f"Running benchmark on train set ({len(train_tasks)} tasks)...")
        results = run_benchmark(
            provider,
            harness_url,
            train_tasks,
            current.system_prompt,
            max_iterations,
            parallel=parallel,
            workers=workers,
        )

        # Calculate train score
        passed = sum(1 for r in results if r.status == "passed")
        train_score = passed / len(results)
        gen_time = time.time() - gen_start

        print(
            f"Train Score: {train_score:.3f} ({passed}/{len(results)}) | Time: {gen_time:.1f}s"
        )

        # Run holdout validation if enabled
        holdout_score: Optional[float] = None
        if holdout_tasks:
            print(f"Validating on holdout set ({len(holdout_tasks)} tasks)...")
            holdout_results = run_benchmark(
                provider,
                harness_url,
                holdout_tasks,
                current.system_prompt,
                max_iterations,
                parallel=parallel,
                workers=workers,
            )
            holdout_passed = sum(1 for r in holdout_results if r.status == "passed")
            holdout_score = holdout_passed / len(holdout_results)
            print(
                f"{CLI_BLUE}Holdout Score: {holdout_score:.3f} ({holdout_passed}/{len(holdout_tasks)}){CLI_CLR}"
            )

        # Check for errors
        errors = sum(1 for r in results if r.status == "error")
        if errors > 0:
            print(f"{CLI_RED}WARNING: {errors} tasks had errors{CLI_CLR}")

        # Update current version with score
        score = train_score  # Use train_score as main score
        current.test_score = score
        store.save_with_score(current)

        # Track best
        if best_version.test_score is None or score > best_version.test_score:
            best_version = current
            no_improvement_count = 0
            print(f"{CLI_GREEN}NEW BEST: {score}{CLI_CLR}")
        else:
            no_improvement_count += 1

        # Check for overfitting using guard
        should_stop_reason = guard.should_stop(gen, train_score, holdout_score)
        if should_stop_reason[0]:
            print(f"\n{CLI_RED}*** STOPPED: {should_stop_reason[1]} ***{CLI_CLR}")
            print(
                f"Train: {train_score:.3f}, Holdout: {holdout_score:.3f if holdout_score else 'N/A'}"
            )
            return best_version

        # Check target
        if score >= target_score:
            print(
                f"\n{CLI_GREEN}*** TARGET REACHED: {score} >= {target_score} ***{CLI_CLR}"
            )
            return best_version

        # Early stop if near-perfect
        if score >= 0.95:
            print(f"\n{CLI_GREEN}*** NEAR PERFECT: {score} ***{CLI_CLR}")
            return best_version

        # Check for regression
        if prev_score is not None and score < prev_score - regression_threshold:
            print(f"{CLI_RED}REGRESSION: {prev_score:.3f} -> {score:.3f}{CLI_CLR}")
            print("Rolling back to previous version...")

        prev_score = score

        # Analyze failures
        print("Analyzing failures...")
        patterns = analyze_failures(results, provider)

        if not patterns:
            print(f"{CLI_YELLOW}No failure patterns found, stopping.{CLI_CLR}")
            return best_version

        print(f"Found {len(patterns)} failure patterns:")
        for p in patterns:
            print(f"  - {p.description[:80]}")

        # Create new version
        print("Creating new version...")
        suggestions = format_suggestions(patterns)

        # Import versioner here to avoid circular import
        from versioner import create_new_version

        new_version = create_new_version(
            current.system_prompt,
            suggestions,
            provider,
            current.version_id,
        )

        current = new_version
        store.save(current)

        print(f"Created version {current.version_id}")

        # Log this generation
        gen_duration = time_module.time() - gen_start_time
        gen_log = GenerationLog(
            generation=gen,
            version_id=current.version_id,
            parent_version_id=current.parent_version,
            train_score=train_score,
            holdout_score=holdout_score,
            failure_patterns_found=[p.description for p in patterns],
            analyzer_summary=patterns[0].hypothesis if patterns else "",
            changes_summary=current.changes_summary,
            rationale=current.rationale,
            duration_seconds=gen_duration,
        )
        evolution_logger.log_generation(gen_log)

        # Stop if no improvement for 3 generations
        if no_improvement_count >= 3:
            print(f"{CLI_YELLOW}No improvement for 3 generations, stopping.{CLI_CLR}")
            evolution_logger.finish_session(
                best_version_id=best_version.version_id,
                best_score=best_version.test_score or 0.0,
            )
            return best_version

    # Finalize
    evolution_logger.finish_session(
        best_version_id=best_version.version_id,
        best_score=best_version.test_score or 0.0,
    )

    print(f"\n{CLI_YELLOW}Max generations reached.{CLI_CLR}")
    return best_version


def print_evolution_summary(store: PromptStore):
    """Print summary of evolution progress."""
    print(f"\n{'=' * 60}")
    print("EVOLUTION SUMMARY")
    print(f"{'=' * 60}")

    versions = sorted(store.prompt_versions, key=lambda v: v.version_id)

    for v in versions:
        score_str = f"{v.test_score:.3f}" if v.test_score else "N/A"
        print(f"v{v.version_id}: score={score_str} | method={v.generation_method}")

        if v.changes_summary:
            print(f"  changes: {v.changes_summary[:100]}")

    best = store.get_best_version()
    if best:
        print(f"\nBest: v{best.version_id} with score {best.test_score:.3f}")
