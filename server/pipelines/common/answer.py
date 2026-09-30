import logging
from pathlib import Path

from pydantic import ValidationError

from server.common.timing import timer
from server.llm.gateway import call_llm
from server.llm.models import LLMMessage, LLMRequest
from server.pipelines.common.render import LabeledEvidence, render_blocks
from server.pipelines.common.tracer import Tracer
from server.pipelines.models import ModelAnswer

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT = (PROMPTS_DIR / "answer_system_v1.md").read_text()
USER_PROMPT_TEMPLATE = (PROMPTS_DIR / "answer_user_v1.md").read_text()

# $0 on Groq's free tier per config/models.yaml; also the model `hl llm-ping` uses.
DEFAULT_MODEL = "openai/gpt-oss-20b"


def final_answer(
    tracer: Tracer,
    question: str,
    labels: dict[str, LabeledEvidence],
    model: str = DEFAULT_MODEL,
) -> tuple[ModelAnswer | None, str | None]:
    """Shared final-answer step for all pipelines (RAG now; GraphRAG/agent
    reuse this for their own final answer): same prompts, same schema, same
    one-repair-attempt parsing. Never raises -- returns (None, error) on
    unrecoverable failure so the caller can produce an error AnswerResult."""
    blocks = render_blocks(labels)
    user_prompt = USER_PROMPT_TEMPLATE.format(question=question, evidence_blocks=blocks)
    messages = [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_prompt),
    ]
    req = LLMRequest(
        provider="groq", model=model, messages=messages, json_mode=True, temperature=0.0
    )

    with timer() as t:
        resp = call_llm(req)
    tracer.add(
        "llm",
        "final_answer",
        question,
        resp.content[:1000],
        resp.tokens_in,
        resp.tokens_out,
        resp.cost_usd,
        t["ms"],
        error=resp.error,
    )
    if resp.error:
        return None, f"llm_error: {resp.error}"

    try:
        return ModelAnswer.model_validate_json(resp.content), None
    except ValidationError as e:
        logger.warning("Answer JSON validation failed, retrying once with the error appended.")
        repair_prompt = (
            f"{user_prompt}\n\nYour previous output failed validation: {e}\nReturn corrected JSON."
        )
        req.messages[1].content = repair_prompt
        with timer() as t2:
            resp2 = call_llm(req)
        tracer.add(
            "llm",
            "final_answer_repair",
            repair_prompt[:500],
            resp2.content[:1000],
            resp2.tokens_in,
            resp2.tokens_out,
            resp2.cost_usd,
            t2["ms"],
            error=resp2.error,
        )
        if resp2.error:
            return None, f"llm_error: {resp2.error}"
        try:
            return ModelAnswer.model_validate_json(resp2.content), None
        except ValidationError as e2:
            return None, f"schema_invalid: {e2}"
