from collections.abc import Callable, Iterable, Sequence

from server.eval.normalize import entity_match, norm_text


def score_entity(pred: str, gold: str) -> float:
    return 1.0 if entity_match(pred, gold) else 0.0


def set_f1(pred: Sequence[str], gold: Sequence[str], match: Callable[[str, str], bool]) -> float:
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    tp_pred = sum(1 for p in pred if any(match(p, g) for g in gold))
    tp_gold = sum(1 for g in gold if any(match(p, g) for p in pred))
    precision = tp_pred / len(pred)
    recall = tp_gold / len(gold)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def score_list(pred: Sequence[str], gold: Sequence[str]) -> float:
    return set_f1(pred, gold, entity_match)


def score_number(pred: float | None, gold: float, rel_tol: float = 0.01) -> float:
    if pred is None:
        return 0.0
    return 1.0 if abs(pred - gold) <= rel_tol * abs(gold) else 0.0


def score_yes_no(pred: str, gold: str) -> float:
    p = norm_text(pred).split()
    if not p:
        return 0.0
    return 1.0 if p[0] == norm_text(gold) else 0.0


def score_abstention(answerable: bool, abstained: bool) -> float:
    return 1.0 if abstained != answerable else 0.0


def citation_accuracy(
    cited: Iterable[tuple[str, int]], gold: Iterable[tuple[str, int]]
) -> float | None:
    cited_list = list(cited)
    if not cited_list:
        return None
    gold_set = set(gold)
    return sum(1 for c in cited_list if c in gold_set) / len(cited_list)
