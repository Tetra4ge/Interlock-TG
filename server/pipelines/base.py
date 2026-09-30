from typing import Protocol

from server.pipelines.models import AnswerResult


class Pipeline(Protocol):
    name: str

    def answer(self, question: str, request_id: str) -> AnswerResult: ...


REGISTRY: dict[str, Pipeline] = {}


def register(pipeline: Pipeline) -> None:
    REGISTRY[pipeline.name] = pipeline
