import re

from server.pipelines.common.budget import fit_to_budget
from server.pipelines.models import EvidenceItem

LABEL_RE = re.compile(r"\bE(\d+)\b")
RECENT_STEPS = 3


class EvidenceLog:
    """Everything the tools returned that states a fact, labelled E1, E2, ...
    like RAG and GraphRAG evidence. A ref_id is logged once: asking for the
    same fact again returns the label it already has."""

    def __init__(self) -> None:
        self.items: list[EvidenceItem] = []
        self.provenance: dict[str, dict] = {}
        self._label_of: dict[str, str] = {}

    def add(
        self,
        kind: str,
        ref_id: str,
        text: str,
        doc_id: str = "",
        page_start: int = 0,
        page_end: int | None = None,
        section: str = "",
        fiscal_year: str = "",
    ) -> str:
        if ref_id in self._label_of:
            return self._label_of[ref_id]
        label = f"E{len(self.items) + 1}"
        self.items.append(EvidenceItem(kind=kind, ref_id=ref_id, text=text))
        self.provenance[ref_id] = {
            "doc_id": doc_id,
            "page_start": page_start,
            "page_end": page_start if page_end is None else page_end,
            "section": section,
            "fiscal_year": fiscal_year,
        }
        self._label_of[ref_id] = label
        return label

    def label_of(self, ref_id: str) -> str | None:
        return self._label_of.get(ref_id)

    def item_for_label(self, label: str) -> EvidenceItem | None:
        match = LABEL_RE.fullmatch(label)
        if not match:
            return None
        i = int(match.group(1)) - 1
        return self.items[i] if 0 <= i < len(self.items) else None

    def __len__(self) -> int:
        return len(self.items)

    def prioritized(
        self, budget_tokens: int, last_text: str, recent_labels: list[str]
    ) -> tuple[list[EvidenceItem], dict[str, dict]]:
        """Fit the log into the shared evidence budget: items the agent's last
        message cited first, then items from its latest steps, then the rest."""
        cited = {f"E{n}" for n in LABEL_RE.findall(last_text)}
        recent = set(recent_labels)

        def rank(label: str) -> int:
            return 0 if label in cited else 1 if label in recent else 2

        ordered = sorted(
            ((f"E{i + 1}", item) for i, item in enumerate(self.items)),
            key=lambda pair: rank(pair[0]),  # stable: log order within a group
        )
        kept = fit_to_budget([item for _, item in ordered], budget_tokens)
        return kept, {i.ref_id: self.provenance[i.ref_id] for i in kept}


def recent_labels(steps: list, n: int = RECENT_STEPS) -> list[str]:
    return [label for step in steps[-n:] for label in step.result_labels]
