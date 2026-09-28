import json
from datetime import UTC, datetime
from pathlib import Path

from server.common.logging import get_logger
from server.llm.cache import generate_cache_key
from server.llm.models import LLMRequest, LLMResponse
from server.llm.pricing import calculate_cost
from server.llm.providers.groq_provider import GroqProvider
from server.store.db import connect

logger = get_logger(__name__)
CACHE_DIR = Path("data/cache/llm")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Register supported providers
PROVIDERS = {
    "groq": GroqProvider,
}

def call_llm(request: LLMRequest) -> LLMResponse:
    """
    The main orchestrator for LLM requests.
    Checks the local JSON cache, hits the API on cache miss, calculates cost, 
    and logs the execution trace directly to Turso DB.
    """
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

    # 3. Call Provider (Cache Miss)
    provider_class = PROVIDERS.get(request.provider)
    if not provider_class:
        return LLMResponse(
            content="", tokens_in=0, tokens_out=0, 
            error=f"Unknown provider: {request.provider}"
        )
    
    provider_impl = provider_class()
    response = provider_impl.generate(request)
    
    # 4. Calculate Cost
    response.cost_usd = calculate_cost(request.model, response.tokens_in, response.tokens_out)
    
    # 5. Save to File Cache if no error
    if not response.error:
        cache_file.write_text(response.model_dump_json(indent=2))
        
    # 6. Save audit trail to Turso DB (llm_calls table)
    _log_to_db(cache_key, request, response)
    
    return response

def _log_to_db(cache_key: str, request: LLMRequest, response: LLMResponse) -> None:
    """
    Inserts a metadata record of the LLM call to the run store.
    """
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO llm_calls 
            (cache_key, role, provider, model, tokens_in, tokens_out, cost_usd, latency_ms, cache_hit, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                cache_key, 
                "system", # Using a generic role name for the log 
                request.provider, 
                request.model, 
                response.tokens_in, 
                response.tokens_out, 
                response.cost_usd, 
                response.latency_ms, 
                int(response.cache_hit), 
                response.error,
                datetime.now(UTC).isoformat()
            ]
        )
    except Exception as e:
        logger.error(f"Failed to log LLM call to DB: {e}")
    finally:
        conn.close()
