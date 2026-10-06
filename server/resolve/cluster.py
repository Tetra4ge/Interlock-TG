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


def run_clustering() -> None:
    logger.info("Building mentions...")
    mentions = build_mentions()

    logger.info(f"Loaded {len(mentions)} mentions. Blocking...")
    blocks: dict[str, list[Mention]] = collections.defaultdict(list)
    mention_dict: dict[str, Mention] = {}

    for m in mentions:
        for key in block_keys(m):
            blocks[key].append(m)
        mention_dict[m.mention_id] = m

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

    conn = connect()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            entity_id TEXT PRIMARY KEY,
            kind TEXT,
            canonical_name TEXT,
            aliases_text TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS merge_log (
            mention_id TEXT PRIMARY KEY,
            entity_id TEXT,
            method TEXT,
            score REAL,
            reason TEXT
        )
    """)
    conn.commit()

    logger.info(f"Writing {len(clusters)} entities to database...")
    for root, cluster_mentions in clusters.items():
        kind = cluster_mentions[0].kind

        # Collect exact official IDs
        exact_ids = set()
        for m in cluster_mentions:
            eid = generate_exact_id(m)
            if eid:
                exact_ids.add(eid)

        # Conflict check
        if len(exact_ids) > 1:
            logger.warning(f"Conflict! Cluster {root} contains multiple IDs: {exact_ids}")
            for m in cluster_mentions:
                conn.execute(
                    "INSERT INTO review_queue (record_id, reason, created_at) "
                    "VALUES (?, ?, datetime('now'))",
                    [m.record_id, f"cluster_conflict: {list(exact_ids)}"],
                )
            continue

        if exact_ids:
            entity_id = list(exact_ids)[0]
        else:
            # Stable hash of sorted normalized names
            sorted_names = sorted(list(set(m.norm_name for m in cluster_mentions)))
            h = hashlib.sha256(("|".join(sorted_names)).encode()).hexdigest()[:8]
            prefix = {"person": "P", "company": "C", "audit_firm": "A"}.get(kind, "X")
            entity_id = f"{prefix}:x{h}"

        # Canonical name (most frequent, tie -> longest)
        name_counts = collections.Counter(m.raw_name for m in cluster_mentions)
        max_count = max(name_counts.values())
        candidates = [name for name, count in name_counts.items() if count == max_count]
        canonical_name = sorted(candidates, key=len, reverse=True)[0]

        aliases = list(set(m.raw_name for m in cluster_mentions))

        conn.execute(
            "INSERT OR REPLACE INTO entities (entity_id, kind, canonical_name, aliases_text) "
            "VALUES (?, ?, ?, ?)",
            [entity_id, kind, canonical_name, "|".join(aliases)],
        )

        for m in cluster_mentions:
            reason = merge_reasons.get(m.mention_id, {"method": "singleton", "score": 100.0})
            conn.execute(
                "INSERT OR REPLACE INTO merge_log "
                "(mention_id, entity_id, method, score, reason) VALUES (?, ?, ?, ?, ?)",
                [m.mention_id, entity_id, reason["method"], reason["score"], ""],
            )

    conn.commit()
    conn.close()
    logger.info("Clustering complete.")


if __name__ == "__main__":
    run_clustering()
