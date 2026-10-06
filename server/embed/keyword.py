import json
import math
import re
from collections import Counter
from pathlib import Path

CHUNKS_DIR = Path("data/chunks")
TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
    ]
)
K1 = 1.5
B = 0.75


def _tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]


def load_chunks(doc_ids: list[str] | None) -> list[dict]:
    paths = (
        [CHUNKS_DIR / f"{d}_chunks.json" for d in doc_ids]
        if doc_ids is not None
        else sorted(CHUNKS_DIR.glob("*_chunks.json"))
    )
    chunks: list[dict] = []
    for path in paths:
        if path.exists():
            chunks.extend(json.loads(path.read_text()))
    return chunks


def keyword_search(query: str, chunks: list[dict], k: int) -> list[tuple[str, float]]:
    """BM25 over chunk text, so exact phrases such as 'statutory auditor' rank even when
    embedding similarity does not."""
    query_terms = set(_tokens(query))
    if not query_terms or not chunks:
        return []
    term_counts = [Counter(_tokens(c["text"])) for c in chunks]
    lengths = [sum(tc.values()) for tc in term_counts]
    avg_len = (sum(lengths) / len(lengths)) or 1.0
    n = len(chunks)
    doc_freq = {t: sum(1 for tc in term_counts if t in tc) for t in query_terms}

    scored: list[tuple[str, float]] = []
    for chunk, tc, length in zip(chunks, term_counts, lengths, strict=True):
        score = 0.0
        for term in query_terms:
            freq = tc.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (n - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            score += idf * freq * (K1 + 1) / (freq + K1 * (1 - B + B * length / avg_len))
        if score > 0:
            scored.append((str(chunk["chunk_id"]), score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]
