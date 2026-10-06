from typing import Literal

from pydantic import BaseModel

from server.pipelines.models import AnswerType


class GoldEvidence(BaseModel):
    doc_id: str
    page: int


class Question(BaseModel):
    qid: str
    version: str
    question: str
    category: Literal["single_fact", "numerical", "unanswerable"]
    answer_type: AnswerType
    gold_answer: str | list[str] | float | None = None
    gold_unit: str | None = None
    gold_evidence: list[GoldEvidence] = []
    split: Literal["dev", "test"]
    verified: bool = False
    verification_note: str | None = None

    @property
    def answerable(self) -> bool:
        return self.category != "unanswerable"
