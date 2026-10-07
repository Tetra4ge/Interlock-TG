import json
import threading
import time

import pytest

from server.api import deps as deps_mod
from server.api.deps import ADHOC_RUN_ID, AppContext, load_json_lines
from server.pipelines.models import AnswerResult
from server.settings import Settings
from tests.conftest import MemoryDB
from tests.unit.api_fixtures import answer_result


def _cfg(**kw: object) -> Settings:
    return Settings(**{"groq_api_key": "", "demo_mode": False, **kw})  # type: ignore[arg-type]


def _ctx(memdb: MemoryDB, **kw) -> AppContext:  # type: ignore[no-untyped-def]
    return AppContext(
        cfg=kw.pop("cfg", _cfg()),
        db_factory=lambda: memdb,
        pipelines_loader=kw.pop("pipelines_loader", dict),
        tg_probe=kw.pop("tg_probe", lambda: True),
        **kw,
    )


def test_turso_ok_true_and_false(memdb: MemoryDB) -> None:
    assert _ctx(memdb).turso_ok() is True

    def broken() -> None:
        raise RuntimeError("db down")

    assert AppContext(db_factory=broken).turso_ok() is False  # type: ignore[arg-type]


def test_db_context_manager_closes_the_connection() -> None:
    closed: list[bool] = []

    class Conn:
        def close(self) -> None:
            closed.append(True)

    ctx = AppContext(db_factory=lambda: Conn())
    with ctx.db():
        pass
    assert closed == [True]
    with pytest.raises(ValueError), ctx.db():
        raise ValueError("inside")
    assert closed == [True, True]  # closed on error too


@pytest.mark.parametrize(
    ("key", "demo", "expected"),
    [("", False, True), ("", True, True), ("sk", False, False), ("sk", True, True)],
)
def test_demo_mode_is_on_when_asked_for_or_when_there_is_no_key(
    memdb: MemoryDB, key: str, demo: bool, expected: bool
) -> None:
    ctx = _ctx(memdb, cfg=_cfg(groq_api_key=key, demo_mode=demo))
    assert ctx.demo_mode is expected and ctx.llm_key is bool(key)


def test_pipelines_load_lazily_once(memdb: MemoryDB) -> None:
    calls: list[int] = []

    def loader() -> dict:
        calls.append(1)
        return {"rag": object()}

    ctx = _ctx(memdb, pipelines_loader=loader)
    assert calls == []  # building the context loads nothing heavy
    assert ctx.pipelines is ctx.pipelines and calls == [1]


def test_pipelines_are_loaded_once_under_concurrent_first_use(memdb: MemoryDB) -> None:
    calls: list[int] = []

    def slow_loader() -> dict:
        calls.append(1)
        time.sleep(0.05)
        return {}

    ctx = _ctx(memdb, pipelines_loader=slow_loader)
    threads = [threading.Thread(target=lambda: ctx.pipelines) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == [1]


def test_tigergraph_probe_is_cached_between_health_checks(memdb: MemoryDB) -> None:
    probes: list[int] = []

    def probe() -> bool:
        probes.append(1)
        return True

    ctx = _ctx(memdb, tg_probe=probe)
    assert ctx.tigergraph_ok() and ctx.tigergraph_ok() and ctx.tigergraph_ok()
    assert probes == [1]


def test_tigergraph_probe_failure_is_false_not_an_exception(memdb: MemoryDB) -> None:
    def probe() -> bool:
        raise ConnectionError("500 from token endpoint")

    assert _ctx(memdb, tg_probe=probe).tigergraph_ok() is False


def test_tigergraph_probe_that_hangs_times_out(
    memdb: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deps_mod, "TG_PROBE_TIMEOUT_S", 0.1)
    release = threading.Event()
    ctx = _ctx(memdb, tg_probe=lambda: release.wait(5) or True)
    started = time.monotonic()
    assert ctx.tigergraph_ok() is False
    assert time.monotonic() - started < 2
    release.set()


def test_tigergraph_probe_result_expires(memdb: MemoryDB, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps_mod, "TG_PROBE_TTL_S", 0.0)
    answers = iter([False, True])
    ctx = _ctx(memdb, tg_probe=lambda: next(answers))
    assert ctx.tigergraph_ok() is False and ctx.tigergraph_ok() is True


def test_adhoc_results_are_saved_under_the_adhoc_run(memdb: MemoryDB) -> None:
    ctx = _ctx(memdb)
    ctx.save_adhoc_result("req-1", answer_result())
    row = memdb.execute("SELECT run_id, qid, answer_json FROM results").fetchone()
    assert row[0] == ADHOC_RUN_ID and row[1] == "req-1:rag"
    assert AnswerResult.model_validate_json(row[2]).answer_short == "a"


def test_saving_an_adhoc_result_never_raises(memdb: MemoryDB) -> None:
    def broken() -> None:
        raise RuntimeError("disk full")

    AppContext(db_factory=broken).save_adhoc_result("req", answer_result())  # type: ignore[arg-type]


def test_load_json_lines_skips_blank_and_bad_lines(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "x.jsonl"
    p.write_text(json.dumps({"a": 1}) + "\n\nnot json\n" + json.dumps({"b": 2}) + "\n")
    assert load_json_lines(p) == [{"a": 1}, {"b": 2}]
    assert load_json_lines(tmp_path / "missing.jsonl") == []
