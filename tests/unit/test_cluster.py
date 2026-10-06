import pytest

from server.resolve import cluster
from server.resolve.mentions import Mention


def _m(mention_id: str, name: str, kind: str = "person", din: str | None = None) -> Mention:
    from server.resolve.normalize import norm_company, norm_person

    norm = norm_person(name) if kind == "person" else norm_company(name)
    return Mention(
        mention_id=mention_id,
        kind=kind,
        raw_name=name,
        norm_name=norm,
        ids={"din": din} if din else {},
        context_company_id="C1",
        record_id=mention_id.split(":")[0],
    )


def _run(memdb, monkeypatch: pytest.MonkeyPatch, mentions: list[Mention]) -> None:
    monkeypatch.setattr(cluster, "connect", lambda: memdb)
    monkeypatch.setattr(cluster, "build_mentions", lambda: mentions)
    cluster.run_clustering()


def test_conflicting_dins_are_split_and_queued_not_dropped(
    memdb, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two real people share a name; a third mention without a DIN chains
    # them into one cluster, so the cluster ends up holding two DINs.
    _run(
        memdb,
        monkeypatch,
        [
            _m("r1:person", "A Sharma", din="11111111"),
            _m("r2:person", "A Sharma"),
            _m("r3:person", "A Sharma", din="22222222"),
        ],
    )

    entities = {r[0] for r in memdb.execute("SELECT entity_id FROM entities").fetchall()}
    assert {"P:11111111", "P:22222222"} <= entities
    # Every mention still has an entity, so the loader keeps their edges.
    assert len(memdb.execute("SELECT 1 FROM merge_log").fetchall()) == 3
    queued = memdb.execute("SELECT record_id, reason FROM review_queue").fetchall()
    assert {r[0] for r in queued} == {"r1", "r2", "r3"}
    assert all(r[1].startswith("cluster_conflict:") for r in queued)


def test_conflict_from_one_record_does_not_abort_the_run(
    memdb, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both conflicting mentions come from the same record; record_id is the
    # review_queue primary key, so a plain INSERT would raise here.
    _run(
        memdb,
        monkeypatch,
        [
            _m("r1:person", "A Sharma", din="11111111"),
            _m("r1:other", "A Sharma"),
            _m("r1:third", "A Sharma", din="22222222"),
        ],
    )
    assert len(memdb.execute("SELECT 1 FROM review_queue").fetchall()) == 1


def test_a_din_found_in_only_one_report_covers_both_mentions(
    memdb, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(
        memdb,
        monkeypatch,
        [_m("r1:person", "N Chandrasekaran", din="00121863"), _m("r2:person", "N Chandrasekaran")],
    )

    rows = memdb.execute("SELECT entity_id FROM merge_log ORDER BY mention_id").fetchall()
    assert [r[0] for r in rows] == ["P:00121863", "P:00121863"]


def test_aliases_from_separate_clusters_are_pooled(memdb, monkeypatch: pytest.MonkeyPatch) -> None:
    # Different surnames never share a block, so these stay separate clusters
    # that resolve to the same DIN.
    _run(
        memdb,
        monkeypatch,
        [
            _m("r1:person", "Natarajan Chandrasekaran", din="00121863"),
            _m("r2:person", "N Chandra", din="00121863"),
        ],
    )

    canonical, aliases = memdb.execute(
        "SELECT canonical_name, aliases_text FROM entities"
    ).fetchone()
    assert canonical == "Natarajan Chandrasekaran"
    assert sorted(aliases.split("|")) == ["N Chandra", "Natarajan Chandrasekaran"]
