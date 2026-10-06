from collections.abc import Mapping, Sequence

import numpy as np


def bootstrap_ci(
    values: Sequence[float], n: int = 2000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float, float]:
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n)])
    return (
        float(arr.mean()),
        float(np.quantile(means, alpha / 2)),
        float(np.quantile(means, 1 - alpha / 2)),
    )


def paired_diff_ci(
    a: Mapping[str, float],
    b: Mapping[str, float],
    n: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    qids = sorted(set(a) & set(b))
    diffs = np.array([a[q] - b[q] for q in qids], dtype=float)
    rng = np.random.default_rng(seed)
    boots = np.array([rng.choice(diffs, size=len(diffs), replace=True).mean() for _ in range(n)])
    return (
        float(diffs.mean()),
        float(np.quantile(boots, alpha / 2)),
        float(np.quantile(boots, 1 - alpha / 2)),
    )
