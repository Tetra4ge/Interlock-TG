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


class GraphRAGConfig(BaseModel):
    max_hops: int = 2
    max_triples: int = 150
    linked_chunks: int = 6
    fanout_hop1: int = 50
    fanout_hop2: int = 15
    min_per_relation: int = 5
    triple_budget_share: float = 0.6
    hub_degree_percentile: float = 99.0
    hub_min_degree: int = 25
    link_min_score: int = 85
    link_score_gap: int = 5
    gsql_timeout_seconds: int = 10
    global_enabled: bool = True


class AgentConfig(BaseModel):
    max_steps: int = 8
    max_tokens: int = 40_000
    timeout_seconds: int = 120
    gsql_timeout_seconds: int = 10
    gsql_max_rows: int = 200
    tool_output_tokens: int = 1500
    shown_rows: int = 60
    graph_query_max_failures: int = 2
    neighbors_default_limit: int = 40
    neighbors_max_limit: int = 60
    search_max_k: int = 8
    verify_enabled: bool = True


def _section(name: str, path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data.get(name) or {}


def load_graphrag_config(path: Path = CONFIG_PATH) -> GraphRAGConfig:
    return GraphRAGConfig(**_section("graphrag", path))


def load_agent_config(path: Path = CONFIG_PATH) -> AgentConfig:
    return AgentConfig(**_section("agent", path))


def load_retrieval_config(path: Path = CONFIG_PATH) -> RetrievalConfig:
    if not path.exists():
        return RetrievalConfig()
    data = yaml.safe_load(path.read_text()) or {}
    return RetrievalConfig(**(data.get("retrieval") or {}))


RETRIEVAL = load_retrieval_config()
GRAPHRAG = load_graphrag_config()
AGENT = load_agent_config()
