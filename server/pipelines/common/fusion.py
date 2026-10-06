def reciprocal_rank_fusion(
    rankings: list[list[tuple[str, float]]], k_out: int, rrf_k: int = 60
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, (item_id, _) in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (rrf_k + rank)
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return fused[:k_out]
