import json
import logging
from pathlib import Path

from server.embed.index import search_vector_index
from server.embed.keyword import keyword_search, load_chunks
from server.pipelines.common.fusion import reciprocal_rank_fusion
from server.pipelines.common.rerank import rerank
from server.store.db import connect

logger = logging.getLogger(__name__)

K = 8
CANDIDATES = 40
RESULTS_PATH = Path("data/eval/recall_at_8.json")


def _labeled_questions() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT r.doc_id, r.payload_json, d.company_id, d.fiscal_year
            FROM records r JOIN documents d ON r.doc_id = d.doc_id
            WHERE r.run_id IN ('manual-fy2324-boards', 'manual-bajfinance-fy2324')
              AND r.status = 'accepted'
            """
        ).fetchall()
    finally:
        conn.close()
    questions = []
    for doc_id, payload_json, company_id, fiscal_year in rows:
        name = json.loads(payload_json)["name"]
        questions.append(
            {
                "question": f"Who is {name} on the board of {company_id} in {fiscal_year}?",
                "doc_id": doc_id,
                "name": name,
            }
        )
    return questions


def _gold_chunk_ids(question: dict, chunks_by_doc: dict[str, list[dict]]) -> set[str]:
    needle = question["name"].lower()
    return {
        str(c["chunk_id"])
        for c in chunks_by_doc.get(question["doc_id"], [])
        if needle in c["text"].lower()
    }


def _recall(ranked_ids: list[str], gold: set[str]) -> float:
    return 1.0 if gold and any(cid in gold for cid in ranked_ids[:K]) else 0.0


def run_recall_test() -> dict:
    questions = _labeled_questions()
    all_chunks = load_chunks(None)
    chunks_by_doc: dict[str, list[dict]] = {}
    for c in all_chunks:
        chunks_by_doc.setdefault(c["doc_id"], []).append(c)
    text_by_id = {str(c["chunk_id"]): c["text"] for c in all_chunks}

    totals = {"vector": 0.0, "hybrid": 0.0, "hybrid_rerank": 0.0}
    per_question = []
    for q in questions:
        gold = _gold_chunk_ids(q, chunks_by_doc)
        if not gold:
            continue
        vector = [cid for cid, _ in search_vector_index(q["question"], k=CANDIDATES)]
        keyword = [cid for cid, _ in keyword_search(q["question"], all_chunks, k=CANDIDATES)]
        fused = [
            cid
            for cid, _ in reciprocal_rank_fusion(
                [[(c, 0.0) for c in vector], [(c, 0.0) for c in keyword]], k_out=CANDIDATES
            )
        ]
        hits = [{"chunk_id": cid, "text": text_by_id.get(cid, "")} for cid in fused]
        reranked = [h["chunk_id"] for h in rerank(q["question"], hits)]
        fused_rerank = [
            cid
            for cid, _ in reciprocal_rank_fusion(
                [[(c, 0.0) for c in fused], [(c, 0.0) for c in reranked]], k_out=CANDIDATES
            )
        ]
        scores = {
            "vector": _recall(vector, gold),
            "hybrid": _recall(fused, gold),
            "hybrid_rerank": _recall(fused_rerank, gold),
        }
        for method, value in scores.items():
            totals[method] += value
        per_question.append({"question": q["question"], "gold_count": len(gold), **scores})

    n = len(per_question)
    result = {
        "n_questions": n,
        "k": K,
        "recall_at_8": {m: round(v / n, 3) for m, v in totals.items()} if n else {},
        "per_question": per_question,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(result, indent=2))
    logger.info(f"Recall@{K} over {n} questions: {result['recall_at_8']}")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_recall_test()["recall_at_8"], indent=2))
