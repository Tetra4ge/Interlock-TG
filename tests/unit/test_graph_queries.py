import pytest

from server.graph import queries


@pytest.mark.parametrize(
    ("entity_id", "vertex_type"),
    [("C:TATASTEEL", "Company"), ("P:x67ebc80ea39b", "Person"), ("A:x1234", "AuditFirm")],
)
def test_vertex_param_infers_the_type_from_the_id_prefix(entity_id: str, vertex_type: str) -> None:
    assert queries.vertex_param(entity_id) == (entity_id, vertex_type)


def test_vertex_param_rejects_ids_it_cannot_type() -> None:
    with pytest.raises(ValueError, match="vertex type"):
        queries.vertex_param("Automobiles")


def test_untyped_vertex_parameters_are_sent_with_their_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, dict] = {}
    monkeypatch.setattr(
        queries, "run_installed", lambda name, params: sent.setdefault(name, params)
    )

    queries.chunks_for_entities(["C:1", "P:2"], limit=7)
    queries.neighbors("C:1", hops=2)
    queries.path_between("C:1", "P:2")

    assert sent["chunks_for_entities"] == {
        "entities": [("C:1", "Company"), ("P:2", "Person")],
        "max_limit": 7,
    }
    assert sent["entity_neighbors"]["seeds"] == [("C:1", "Company")]
    assert sent["path_between"]["source"] == ("C:1", "Company")
    assert sent["path_between"]["target"] == ("P:2", "Person")


def test_strict_runner_raises_instead_of_returning_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    class Conn:
        def runInstalledQuery(self, name, params=None, timeout=None):  # type: ignore[no-untyped-def]
            raise TimeoutError("slow")

    monkeypatch.setattr(queries, "get_tg_connection", lambda: Conn())
    with pytest.raises(queries.GraphQueryError, match="expand_hop: slow"):
        queries.run_installed_strict("expand_hop", {}, 5)
    assert queries.run_installed("expand_hop", {}) == []  # the lenient runner still hides it


def test_strict_runner_passes_the_timeout_in_milliseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    class Conn:
        def runInstalledQuery(self, name, params=None, timeout=None):  # type: ignore[no-untyped-def]
            seen["timeout"] = timeout
            return [{"ok": 1}]

    monkeypatch.setattr(queries, "get_tg_connection", lambda: Conn())
    assert queries.run_installed_strict("q", {}, 10) == [{"ok": 1}]
    assert seen["timeout"] == 10_000
