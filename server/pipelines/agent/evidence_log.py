import re
from collections.abc import Callable

import numpy as np

from server.pipelines.common.budget import fit_to_budget, item_tokens
from server.pipelines.models import EvidenceItem

LABEL_RE = re.compile(r"\bE(\d+)\b")
RECENT_STEPS = 3
RECENT_BONUS = 0.05  # recency breaks ties between similarly relevant items

Relevance = Callable[[list[str]], list[float]]


def question_similarity(question: str, texts: list[str]) -> list[float]:
    """Cosine similarity of each text to the question (embeddings are normalised)."""
    from server.embed.provider import embed_texts
    from server.embed.query import embed_query

    if not texts:
        return []
    q = np.array(embed_query(question), dtype=np.float32)
    vectors = np.array(embed_texts(texts, is_query=False), dtype=np.float32)
    return [float(x) for x in vectors @ q]


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
        # A transaction is logged as "edgeA,edgeB"; either edge id finds it.
        for part in ref_id.split(","):
            self._label_of.setdefault(part, label)
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
        self,
        budget_tokens: int,
        last_text: str,
        recent_labels: list[str],
        relevance: Relevance | None = None,
    ) -> tuple[list[EvidenceItem], dict[str, dict]]:
        """Fit the log into the shared evidence budget. Anything the agent's last
        message cited comes first. The rest is ordered by relevance to the question
        (recent steps get a small bonus) when a scorer is given and the log does
        not already fit; without one, recent steps come first, then log order.

        Recency alone is a poor proxy: an agent that flails ends with a log whose
        newest items are its worst, and they would push out the ones that matter."""
        if sum(item_tokens(i) for i in self.items) <= budget_tokens:
            return self._fit(self.items, budget_tokens)

        cited = {f"E{n}" for n in LABEL_RE.findall(last_text)}
        recent = set(recent_labels)
        labelled = [(f"E{i + 1}", item) for i, item in enumerate(self.items)]

        scores: list[float] | None = None
        if relevance is not None:
            try:
                scores = relevance([item.text for _, item in labelled])
            except Exception:  # scoring is a heuristic; never lose the answer over it
                scores = None

        def key(i: int) -> tuple[int, float]:
            label = labelled[i][0]
            if label in cited:
                return (0, 0.0)
            if scores is None:
                return (1, 0.0) if label in recent else (2, 0.0)
            return (1, -(scores[i] + (RECENT_BONUS if label in recent else 0.0)))

        order = sorted(range(len(labelled)), key=key)  # stable: log order breaks ties
        return self._fit([labelled[i][1] for i in order], budget_tokens)

    def _fit(
        self, ordered: list[EvidenceItem], budget_tokens: int
    ) -> tuple[list[EvidenceItem], dict[str, dict]]:
        kept = fit_to_budget(ordered, budget_tokens)
        return kept, {i.ref_id: self.provenance[i.ref_id] for i in kept}


def recent_labels(steps: list, n: int = RECENT_STEPS) -> list[str]:
    return [label for step in steps[-n:] for label in step.result_labels]
