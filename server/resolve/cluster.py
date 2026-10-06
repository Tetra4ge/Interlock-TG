import collections
import hashlib
import logging

from server.common.config import pipeline_section
from server.resolve.match import block_keys, compare_mentions, generate_exact_id
from server.resolve.mentions import Mention, build_mentions
from server.store.db import connect

logger = logging.getLogger(__name__)


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _hashed_id(mention: Mention, cluster: list[Mention]) -> str:
    """Fallback id for an entity with no official identifier: a stable hash
    of the cluster's distinct normalised names."""
    names = sorted({m.norm_name for m in cluster})
    h = hashlib.sha256("|".join(names).encode()).hexdigest()[:8]
    prefix = {"person": "P", "company": "C", "audit_firm": "A"}.get(mention.kind, "X")
    return f"{prefix}:x{h}"


def run_clustering() -> None:
    logger.info("Building mentions...")
    mentions = build_mentions()

    logger.info(f"Loaded {len(mentions)} mentions. Blocking...")
    blocks: dict[str, list[Mention]] = collections.defaultdict(list)
    for m in mentions:
        for key in block_keys(m):
            blocks[key].append(m)

    cfg = pipeline_section("resolve")
    auto_merge_threshold = float(cfg.get("auto_merge_threshold", 95.0))
    review_band_low = float(cfg.get("review_band_low", 80.0))

    uf = UnionFind()
    merge_reasons = {}

    logger.info("Matching within blocks...")
    for _, block_mentions in blocks.items():
        n = len(block_mentions)
        # O(N^2) but only within small block limits
        for i in range(n):
            for j in range(i + 1, n):
                m1 = block_mentions[i]
                m2 = block_mentions[j]

                res = compare_mentions(m1, m2, auto_merge_threshold, review_band_low)
                if res and res["method"] in ("exact_name", "fuzzy"):
                    uf.union(m1.mention_id, m2.mention_id)
                    merge_reasons[m1.mention_id] = res
                    merge_reasons[m2.mention_id] = res

                elif res and res["method"] == "review_queue":
                    # In a real app we might write this pair to the review_queue table directly
                    pass

    logger.info("Extracting clusters...")
    clusters: dict[str, list[Mention]] = collections.defaultdict(list)
    for m in mentions:
        root = uf.find(m.mention_id)
        clusters[root].append(m)

    # Every mention gets an entity id. A cluster that turns out to hold two
    # different official ids is split along those ids instead of being
    # dropped -- dropping it silently removed every fact from those records.
    assignments: list[tuple[Mention, str]] = []
    conflicted: list[tuple[Mention, str]] = []

    for root, cluster_mentions in clusters.items():
        exact_ids = {eid for m in cluster_mentions if (eid := generate_exact_id(m))}
        if len(exact_ids) > 1:
            logger.warning(f"Conflict! Cluster {root} contains multiple IDs: {exact_ids}")
            reason = f"cluster_conflict: {sorted(exact_ids)}"
            for m in cluster_mentions:
                conflicted.append((m, reason))

        shared_id = exact_ids.pop() if len(exact_ids) == 1 else None
        for m in cluster_mentions:
            assignments.append(
                (m, generate_exact_id(m) or shared_id or _hashed_id(m, cluster_mentions))
            )

    # Two clusters can land on the same entity (same official id, or the
    # same set of names), so aliases are pooled per entity rather than the
    # last cluster written winning.
    by_entity: dict[str, list[Mention]] = collections.defaultdict(list)
    for m, entity_id in assignments:
        by_entity[entity_id].append(m)

    conn = connect()
    logger.info(f"Writing {len(by_entity)} entities to database...")
    for entity_id, entity_mentions in by_entity.items():
        # Canonical name: most frequent, ties broken by the longest spelling.
        name_counts = collections.Counter(m.raw_name for m in entity_mentions)
        max_count = max(name_counts.values())
        candidates = [name for name, count in name_counts.items() if count == max_count]
        canonical_name = sorted(candidates, key=len, reverse=True)[0]
        aliases = sorted({m.raw_name for m in entity_mentions})

        conn.execute(
            "INSERT OR REPLACE INTO entities (entity_id, kind, canonical_name, aliases_text) "
            "VALUES (?, ?, ?, ?)",
            [entity_id, entity_mentions[0].kind, canonical_name, "|".join(aliases)],
        )

        for m in entity_mentions:
            reason = merge_reasons.get(m.mention_id, {"method": "singleton", "score": 100.0})
            conn.execute(
                "INSERT OR REPLACE INTO merge_log "
                "(mention_id, entity_id, method, score, reason) VALUES (?, ?, ?, ?, ?)",
                [m.mention_id, entity_id, reason["method"], reason["score"], ""],
            )

    for m, reason in conflicted:
        # record_id is the primary key, so a second conflicting mention from
        # the same record must not abort the whole run.
        conn.execute(
            "INSERT OR REPLACE INTO review_queue (record_id, reason, created_at) "
            "VALUES (?, ?, datetime('now'))",
            [m.record_id, reason],
        )

    conn.commit()
    conn.close()
    logger.info("Clustering complete.")


if __name__ == "__main__":
    run_clustering()
