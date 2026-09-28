import hashlib
import json
from server.llm.models import LLMRequest

def generate_cache_key(req: LLMRequest) -> str:
    """
    Generate a stable SHA-256 hash based on request inputs.
    Any change in prompt, temperature, or model results in a new key.
    """
    data = req.model_dump()
    # Serialize to JSON deterministically
    key_str = json.dumps(data, sort_keys=True)
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()
