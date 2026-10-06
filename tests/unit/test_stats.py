from server.eval.stats import bootstrap_ci, paired_diff_ci


def test_bootstrap_is_deterministic_with_seed() -> None:
    values = [0.0, 1.0, 1.0, 0.0, 1.0]
    assert bootstrap_ci(values, seed=3) == bootstrap_ci(values, seed=3)


def test_bootstrap_ci_contains_mean() -> None:
    mean, lo, hi = bootstrap_ci([0.0, 1.0, 1.0, 0.0, 1.0, 1.0])
    assert lo <= mean <= hi


def test_bootstrap_ci_is_zero_width_for_constant_data() -> None:
    assert bootstrap_ci([1.0] * 10) == (1.0, 1.0, 1.0)


def test_paired_diff_of_identical_scores_is_zero() -> None:
    a = {"q1": 1.0, "q2": 0.0, "q3": 1.0}
    assert paired_diff_ci(a, dict(a)) == (0.0, 0.0, 0.0)


def test_paired_diff_only_uses_shared_questions() -> None:
    mean, _, _ = paired_diff_ci({"q1": 1.0, "q2": 1.0}, {"q1": 0.0, "q3": 0.0})
    assert mean == 1.0
