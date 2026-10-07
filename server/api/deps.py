import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from server.pipelines.models import AnswerResult
from server.settings import ROOT, Settings, settings
from server.store.db import connect

logger = logging.getLogger(__name__)

CACHED_ANSWERS_PATH = ROOT / "data/samples/cached_answers.jsonl"
TG_PROBE_TIMEOUT_S = 6.0
TG_PROBE_TTL_S = 30.0
ADHOC_RUN_ID = "adhoc"


def _default_tg_probe() -> bool:
    from server.graph.client import get_tg_connection

    return bool(get_tg_connection().getVertexTypes())


def _default_pipelines() -> dict[str, Any]:
    from server.pipelines.base import REGISTRY, load_all

    load_all()
    return dict(REGISTRY)


class AppContext:
    """Everything the routes share, built once at startup. Heavy parts (the
    pipelines import the embedding and reranker models) load on first live use,
    so read-only routes and demo mode start fast and need no ML stack."""

    def __init__(
        self,
        cfg: Settings = settings,
        db_factory: Callable[[], Any] = connect,
        pipelines_loader: Callable[[], dict[str, Any]] = _default_pipelines,
        tg_probe: Callable[[], bool] = _default_tg_probe,
        cached_answers_path: Path = CACHED_ANSWERS_PATH,
    ) -> None:
        self.settings = cfg
        self._db_factory = db_factory
        self._pipelines_loader = pipelines_loader
        self._tg_probe = tg_probe
        self.cached_answers_path = cached_answers_path
        self._pipelines: dict[str, Any] | None = None
        self._pipelines_lock = threading.Lock()
        self._tg_cache: tuple[float, bool] | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tg-probe")

    @contextmanager
    def db(self) -> Iterator[Any]:
        conn = self._db_factory()
        try:
            yield conn
        finally:
            conn.close()

    @property
    def llm_key(self) -> bool:
        return bool(self.settings.groq_api_key)

    @property
    def demo_mode(self) -> bool:
        """Answer from the cached file first: asked for, or there is no key to spend."""
        return self.settings.demo_mode or not self.llm_key

    @property
    def pipelines(self) -> dict[str, Any]:
        with self._pipelines_lock:
            if self._pipelines is None:
                self._pipelines = self._pipelines_loader()
            return self._pipelines

    def turso_ok(self) -> bool:
        try:
            with self.db() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception as e:
            logger.warning(f"Turso health check failed: {e}")
            return False

    def tigergraph_ok(self) -> bool:
        """Cached briefly: a probe mints a token over HTTP, and a dashboard polls /health."""
        now = time.monotonic()
        if self._tg_cache and now - self._tg_cache[0] < TG_PROBE_TTL_S:
            return self._tg_cache[1]
        future = self._executor.submit(self._tg_probe)
        try:
            ok = bool(future.result(timeout=TG_PROBE_TIMEOUT_S))
        except FutureTimeout:
            logger.warning("TigerGraph health check timed out")
            ok = False
        except Exception as e:
            logger.warning(f"TigerGraph health check failed: {str(e)[:200]}")
            ok = False
        self._tg_cache = (now, ok)
        return ok

    def save_adhoc_result(self, request_id: str, result: AnswerResult) -> None:
        """Keep live answers so they can be inspected later. Best effort: failing to
        record an answer must never fail the answer."""
        try:
            with self.db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO results (run_id, qid, answer_json) VALUES (?, ?, ?)",
                    [ADHOC_RUN_ID, f"{request_id}:{result.pipeline}", result.model_dump_json()],
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"Could not save ad-hoc result: {e}")

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def load_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for n, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            logger.warning(f"{path.name}:{n} is not valid JSON: {e}")
    return rows
