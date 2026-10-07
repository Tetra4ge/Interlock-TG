from typing import Protocol

from server.pipelines.models import AnswerResult


class Pipeline(Protocol):
    name: str

    def answer(self, question: str, request_id: str) -> AnswerResult: ...


REGISTRY: dict[str, Pipeline] = {}


def register(pipeline: Pipeline) -> None:
    REGISTRY[pipeline.name] = pipeline


def load_all() -> None:
    """Import every pipeline module so each registers itself. Lazy because the
    modules pull in heavy dependencies (embedding / reranker models)."""
    import server.pipelines.graphrag  # noqa: F401  (registers "graphrag")
    import server.pipelines.rag  # noqa: F401  (registers "rag")
