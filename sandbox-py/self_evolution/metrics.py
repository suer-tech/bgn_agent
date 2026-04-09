from typing import List, Optional

from self_evolution.prompt_store import PromptStore, PromptVersion


def print_evolution_summary(store: PromptStore) -> None:
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

        if v.failure_patterns:
            print(f"  patterns: {v.failure_patterns}")

    best = store.get_best_version()
    if best:
        print(f"\nBest: v{best.version_id} with score {best.test_score:.3f}")


def get_improvement_rate(store: PromptStore) -> float:
    """Calculate improvement rate between versions."""
    versions = sorted(
        [v for v in store.prompt_versions if v.test_score is not None],
        key=lambda v: v.version_id,
    )

    if len(versions) < 2:
        return 0.0

    first_score = versions[0].test_score
    last_score = versions[-1].test_score

    if first_score is None or last_score is None:
        return 0.0

    return last_score - first_score


def find_convergence_point(store: PromptStore, window_size: int = 3) -> Optional[int]:
    """Find version where scores stopped improving significantly."""
    versions = sorted(
        [v for v in store.prompt_versions if v.test_score is not None],
        key=lambda v: v.version_id,
    )

    if len(versions) < window_size:
        return None

    scores = [v.test_score for v in versions if v.test_score is not None]

    for i in range(len(scores) - window_size + 1):
        window = scores[i : i + window_size]
        max_diff = max(window) - min(window)

        if max_diff < 0.01:  # Less than 1% variation
            return versions[i + window_size - 1].version_id

    return None


def suggest_rollback(
    store: PromptStore, current_version_id: int, regression_threshold: float = 0.05
) -> Optional[int]:
    """Suggest which version to rollback to if current is worse."""
    current_version = None
    for v in store.prompt_versions:
        if v.version_id == current_version_id:
            current_version = v
            break

    if current_version is None or current_version.test_score is None:
        return None

    # Find best previous version
    better_versions = [
        v
        for v in store.prompt_versions
        if v.version_id < current_version_id
        and v.test_score is not None
        and v.test_score > current_version.test_score + regression_threshold
    ]

    if not better_versions:
        return None

    best = max(better_versions, key=lambda v: v.test_score)
    return best.version_id
