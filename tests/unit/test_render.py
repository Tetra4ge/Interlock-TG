from server.pipelines.common.render import assign_labels, render_blocks
from server.pipelines.models import EvidenceItem


def _items() -> list[EvidenceItem]:
    return [EvidenceItem(kind="chunk", ref_id=f"c{i}", text=f"text {i}") for i in range(3)]


def _provenance() -> dict[str, dict]:
    return {
        f"c{i}": {"doc_id": f"doc{i}", "page_start": i + 1, "page_end": i + 2} for i in range(3)
    }


def test_labels_are_sequential_and_stable_for_same_order() -> None:
    first = assign_labels(_items(), _provenance())
    second = assign_labels(_items(), _provenance())
    assert list(first) == ["E1", "E2", "E3"]
    assert {k: v.item.ref_id for k, v in first.items()} == {
        k: v.item.ref_id for k, v in second.items()
    }


def test_label_resolves_to_its_own_provenance() -> None:
    labels = assign_labels(_items(), _provenance())
    assert labels["E2"].doc_id == "doc1"
    assert (labels["E2"].page_start, labels["E2"].page_end) == (2, 3)


def test_render_blocks_contains_every_label_once() -> None:
    blocks = render_blocks(assign_labels(_items(), _provenance()))
    for label in ("[E1]", "[E2]", "[E3]"):
        assert blocks.count(label) == 1
