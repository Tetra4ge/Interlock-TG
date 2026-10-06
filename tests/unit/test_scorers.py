from server.eval.normalize import entity_match
from server.eval.scorers import (
    citation_accuracy,
    score_abstention,
    score_list,
    score_number,
    score_yes_no,
    set_f1,
)


def test_set_f1_perfect() -> None:
    assert set_f1(["a", "b"], ["a", "b"], lambda x, y: x == y) == 1.0


def test_set_f1_partial() -> None:
    assert set_f1(["a", "x"], ["a", "b"], lambda x, y: x == y) == 0.5


def test_set_f1_both_empty_is_one() -> None:
    assert set_f1([], [], lambda x, y: x == y) == 1.0


def test_set_f1_empty_prediction_is_zero() -> None:
    assert set_f1([], ["a"], lambda x, y: x == y) == 0.0


def test_score_list_uses_fuzzy_entity_match() -> None:
    assert score_list(["Deloitte Haskins and Sells LLP"], ["Deloitte Haskins & Sells"]) == 1.0


def test_number_within_one_percent_passes() -> None:
    assert score_number(2310.0 * 1.009, 2310.0) == 1.0


def test_number_outside_tolerance_fails() -> None:
    assert score_number(2400.0, 2310.0) == 0.0


def test_number_missing_prediction_fails() -> None:
    assert score_number(None, 2310.0) == 0.0


def test_yes_no_reads_first_word() -> None:
    assert score_yes_no("Yes. It is listed as a subsidiary.", "yes") == 1.0
    assert score_yes_no("No", "yes") == 0.0


def test_abstention_scoring() -> None:
    assert score_abstention(answerable=False, abstained=True) == 1.0
    assert score_abstention(answerable=True, abstained=True) == 0.0
    assert score_abstention(answerable=True, abstained=False) == 1.0


def test_citation_accuracy_none_without_citations() -> None:
    assert citation_accuracy([], [("d", 1)]) is None


def test_citation_accuracy_counts_gold_pages() -> None:
    cited = [("d", 1), ("d", 2)]
    assert citation_accuracy(cited, [("d", 2)]) == 0.5


def test_entity_match_used_by_scorers_is_consistent() -> None:
    assert entity_match("T V Narendran", "T. V. Narendran")
