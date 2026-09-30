import hashlib
import json
from pathlib import Path

from server.embed.provider import embed_texts

CACHE_DIR = Path("data/cache/embeddings")


def embed_query(text: str) -> list[float]:
    """Embed a question with the same model and query-mode flag used for
    chunks (Phase 3 Step 11), cached by text hash so repeated questions
    across pipelines/runs skip re-embedding."""
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cache_path = CACHE_DIR / f"{key}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    vec = embed_texts([text], is_query=True)[0]

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(vec))
    tmp.replace(cache_path)
    return vec
