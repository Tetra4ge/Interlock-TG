import hashlib
import json
from pathlib import Path

from server.llm.models import LLMRequest, LLMResponse

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data/cache/llm"


def generate_cache_key(req: LLMRequest) -> str:
    """
    Generate a stable SHA-256 hash based on request inputs.
    Any change in prompt, temperature, or model results in a new key.
    """
    data = req.model_dump()
    # Tool fields are omitted when unused so keys for plain requests are the same
    # as before they existed and previously cached responses stay valid.
    for message in data["messages"]:
        if not message["tool_calls"]:
            del message["tool_calls"]
        if message["tool_call_id"] is None:
            del message["tool_call_id"]
    # Serialize to JSON deterministically
    key_str = json.dumps(data, sort_keys=True)
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def get_cached(key: str) -> LLMResponse | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    return LLMResponse(**json.loads(path.read_text()))


def put_cached(key: str, response: LLMResponse) -> None:
    """Atomic write: a crash mid-write leaves no partial cache file behind."""
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(response.model_dump_json(indent=2))
    tmp.replace(path)
