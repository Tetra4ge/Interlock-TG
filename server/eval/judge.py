"""LLM faithfulness judge (TRD §8, scores.faithfulness + judge_reason).

Given a pipeline's answer and the evidence it was shown, the judge decides
whether every claim in the answer is supported by that evidence. It is a
separate model from the answerer so it does not grade its own work, and it
is deliberately failure-tolerant: any offline miss, spend-cap, transport
or parse error returns None so a run that cannot reach the judge still
scores correctness, citations and recall.
"""

import json
import logging

from pydantic import BaseModel

from server.llm.gateway import OfflineCacheMiss, SpendCapExceeded, call_llm
from server.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)

# A capable free-tier model, distinct from the answerer (gpt-oss-20b in
# server/pipelines/common/answer.py) so the judge is not grading itself.
JUDGE_MODEL = "openai/gpt-oss-120b"
JUDGE_MAX_TOKENS = 512

SYSTEM_PROMPT = (
    "You are a strict faithfulness judge for a question-answering system. "
    "You are given a QUESTION, an ANSWER, and the EVIDENCE the system was "
    "shown. Decide whether every factual claim in the ANSWER is directly "
    "supported by the EVIDENCE. Do not use any outside knowledge: a claim "
    "that may be true in the real world but is not in the EVIDENCE is "
    "unfaithful. Reply with JSON only: "
    '{"faithful": true|false, "reason": "<one sentence>"}.'
)


class JudgeResult(BaseModel):
    faithfulness: float  # 1.0 if every claim is supported, else 0.0
    reason: str


def _build_prompt(question: str, answer_long: str, evidence_texts: list[str]) -> str:
    blocks = "\n\n".join(f"[E{i}] {t}" for i, t in enumerate(evidence_texts, start=1))
    return (
        f"QUESTION:\n{question}\n\n"
        f"ANSWER:\n{answer_long}\n\n"
        f"EVIDENCE:\n{blocks or '(no evidence provided)'}"
    )


def judge_faithfulness(
    question: str,
    answer_long: str,
    evidence_texts: list[str],
    *,
    model: str = JUDGE_MODEL,
) -> JudgeResult | None:
    """Return a faithfulness verdict, or None when the judge is unreachable
    (offline cache miss, spend cap, transport error) or returns unparseable
    output -- so the caller can simply leave faithfulness unscored."""
    req = LLMRequest(
        provider="groq",
        model=model,
        messages=[
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=_build_prompt(question, answer_long, evidence_texts)),
        ],
        json_mode=True,
        temperature=0.0,
        max_tokens=JUDGE_MAX_TOKENS,
    )

    try:
        resp = call_llm(req)
    except (OfflineCacheMiss, SpendCapExceeded) as e:
        logger.info(f"Faithfulness judge skipped: {e}")
        return None
    except Exception as e:
        logger.warning(f"Faithfulness judge call failed: {e}")
        return None

    if resp.error:
        logger.warning(f"Faithfulness judge error: {resp.error}")
        return None

    try:
        data = json.loads(resp.content)
        faithful = bool(data["faithful"])
        reason = str(data.get("reason", ""))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Faithfulness judge returned unparseable output: {e}")
        return None

    return JudgeResult(faithfulness=1.0 if faithful else 0.0, reason=reason)
