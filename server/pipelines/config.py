from pathlib import Path

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "config/pipeline.yaml"


class RetrievalConfig(BaseModel):
    evidence_token_budget: int = 6000
    rag_top_k: int = 20
    rerank_top_k: int = 8
    use_reranker: bool = False


def load_retrieval_config(path: Path = CONFIG_PATH) -> RetrievalConfig:
    if not path.exists():
        return RetrievalConfig()
    data = yaml.safe_load(path.read_text()) or {}
    return RetrievalConfig(**(data.get("retrieval") or {}))


RETRIEVAL = load_retrieval_config()
