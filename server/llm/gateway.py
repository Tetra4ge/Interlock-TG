import json
import random
import time
from datetime import UTC, datetime
from pathlib import Path

from server.common.logging import get_logger
from server.llm.cache import generate_cache_key
from server.llm.models import LLMRequest, LLMResponse
from server.llm.pricing import calculate_cost
from server.llm.providers.base import BaseLLMProvider, FatalError, RetryableError
from server.llm.providers.groq_provider import GroqProvider
from server.settings import settings
from server.store.db import connect

logger = get_logger(__name__)
ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data/cache/llm"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Register supported providers
PROVIDERS = {
    "groq": GroqProvider,
}

MAX_RETRIES = 5
BASE_DELAY_SECONDS = 1.0


class SpendCapExceeded(Exception):
    """Raised when a call would push cumulative spend past LLM_SPEND_CAP_USD."""


class OfflineCacheMiss(Exception):
    """Raised in offline (CI) mode when a request has no cached response."""


_spent_usd: float | None = None  # lazily loaded from llm_calls, then tracked in-process


def _get_spent_usd() -> float:
    """Cumulative spend so far, loaded from the DB once per process so the
    cap survives restarts, then tracked in memory to avoid a query per call."""
    global _spent_usd
    if _spent_usd is None:
        conn = connect()
        try:
            rs = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls")
            _spent_usd = float(rs.rows[0][0]) if rs.rows else 0.0
        except Exception as e:
            logger.warning(f"Could not load prior LLM spend, assuming $0: {e}")
            _spent_usd = 0.0
        finally:
            conn.close()
    return _spent_usd


def call_llm(request: LLMRequest) -> LLMResponse:
    """
    The main orchestrator for LLM requests.
    Checks the local JSON cache, hits the API on cache miss (retrying transient
    errors with backoff), calculates cost, enforces the spend cap, and logs
    the execution trace to Turso DB.
    """
    global _spent_usd

    # 1. Generate stable Cache Key
    cache_key = generate_cache_key(request)
    cache_file = CACHE_DIR / f"{cache_key}.json"

    # 2. Check File Cache
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            res = LLMResponse(**data)
            res.cache_hit = True
            res.cost_usd = 0.0  # Cache hits cost $0
            _log_to_db(cache_key, request, res)
            return res
        except Exception as e:
            logger.warning(f"Failed to read cache file {cache_file}: {e}")

    # 3. Offline mode: CI/tests must never make a real call
    if settings.llm_offline:
        raise OfflineCacheMiss(f"cache miss in offline mode: {cache_key}")

    # 4. Spend cap: check before spending another cent
    if _get_spent_usd() >= settings.llm_spend_cap_usd:
        raise SpendCapExceeded(f"spent ${_get_spent_usd():.2f}")

    # 5. Call Provider (Cache Miss), retrying transient failures
    provider_class = PROVIDERS.get(request.provider)
    if not provider_class:
        return LLMResponse(
            content="", tokens_in=0, tokens_out=0, error=f"Unknown provider: {request.provider}"
        )

    provider_impl = provider_class()
    response = _call_with_retry(provider_impl, request, cache_key)
    if response is None:
        # _call_with_retry already logged the failure to the DB
        raise RuntimeError(f"LLM call failed after {MAX_RETRIES} attempts: {cache_key}")

    # 6. Calculate Cost
    response.cost_usd = calculate_cost(request.model, response.tokens_in, response.tokens_out)
    _spent_usd = _get_spent_usd() + response.cost_usd

    # 7. Save to File Cache if no error
    if not response.error:
        cache_file.write_text(response.model_dump_json(indent=2))

    # 8. Save audit trail to Turso DB (llm_calls table)
    _log_to_db(cache_key, request, response)

    return response


def _call_with_retry(
    provider_impl: BaseLLMProvider, request: LLMRequest, cache_key: str
) -> LLMResponse | None:
    """Retries RetryableError with exponential backoff + jitter. FatalError
    and a final exhausted retry are logged and re-raised, not swallowed."""
    delay = BASE_DELAY_SECONDS
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return provider_impl.generate(request)
        except FatalError as e:
            _log_to_db(cache_key, request, None, error=str(e))
            raise
        except RetryableError as e:
            if attempt == MAX_RETRIES:
                _log_to_db(cache_key, request, None, error=str(e))
                raise
            time.sleep(delay + random.uniform(0, delay / 2))
            delay *= 2
    return None  # unreachable, satisfies type checker


def _log_to_db(
    cache_key: str,
    request: LLMRequest,
    response: LLMResponse | None,
    error: str | None = None,
) -> None:
    """
    Inserts a metadata record of the LLM call to the run store.
    """
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO llm_calls
            (cache_key, role, provider, model, tokens_in, tokens_out,
             cost_usd, latency_ms, cache_hit, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                cache_key,
                "system",  # Using a generic role name for the log
                request.provider,
                request.model,
                response.tokens_in if response else 0,
                response.tokens_out if response else 0,
                response.cost_usd if response else 0.0,
                response.latency_ms if response else 0,
                int(response.cache_hit) if response else 0,
                error or (response.error if response else None),
                datetime.now(UTC).isoformat(),
            ],
        )
    except Exception as e:
        logger.error(f"Failed to log LLM call to DB: {e}")
    finally:
        conn.close()
