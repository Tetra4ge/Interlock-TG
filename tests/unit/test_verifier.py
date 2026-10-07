import json

import pytest

from server.llm.models import LLMResponse
from server.pipelines.agent import verifier as vf
from server.pipelines.agent.verifier import Claim, number_supported, verify_answer
from server.pipelines.common.render import assign_labels
from server.pipelines.models import AnswerType, EvidenceItem, ModelAnswer


def _labels(*texts: str):  # type: ignore[no-untyped-def]
    items = [EvidenceItem(kind="chunk", ref_id=f"r{i}", text=t) for i, t in enumerate(texts)]
    return assign_labels(
        items,
        {f"r{i}": {"doc_id": "d" * 24, "page_start": 3, "page_end": 3} for i in range(len(texts))},
    )


def _answer(
    short: str = "x", long: str = "x is y [E1].", typ: AnswerType = AnswerType.ENTITY
) -> ModelAnswer:
    return ModelAnswer(answer_type=typ, answer_short=short, answer_long=long, citations=[])


def _llm(payload: object, error: str | None = None):  # type: ignore[no-untyped-def]
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return lambda req: LLMResponse(
        content=content, tokens_in=300, tokens_out=40, cost_usd=0.001, error=error
    )


def _claims(*items: tuple[str, str, list[str]]) -> dict:
    return {"claims": [{"claim": c, "verdict": v, "evidence_labels": e} for c, v, e in items]}


def test_all_supported_claims_pass(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(vf, "call_llm", _llm(_claims(("x is y", "SUPPORTED", ["E1"]))))
    result = verify_answer(tracer, _answer(), _labels("x is y"))
    assert result.ok and result.supported[0].evidence_labels == ["E1"]


def test_unsupported_claims_are_reported(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    payload = _claims(("a", "SUPPORTED", ["E1"]), ("b", "UNSUPPORTED", []))
    monkeypatch.setattr(vf, "call_llm", _llm(payload))
    result = verify_answer(tracer, _answer(), _labels("a"))
    assert not result.ok and [c.claim for c in result.unsupported] == ["b"]
    assert [c.claim for c in result.supported] == ["a"]


def test_supported_without_a_real_label_is_downgraded(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    payload = _claims(("a", "SUPPORTED", []), ("b", "SUPPORTED", ["E9"]))
    monkeypatch.setattr(vf, "call_llm", _llm(payload))
    result = verify_answer(tracer, _answer(), _labels("a"))
    assert [c.verdict for c in result.claims] == ["UNSUPPORTED", "UNSUPPORTED"]


def test_the_verifier_call_is_traced_with_cost(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(vf, "call_llm", _llm(_claims(("a", "SUPPORTED", ["E1"]))))
    verify_answer(tracer, _answer(), _labels("a"))
    step = tracer.steps[-1]
    assert (step.kind, step.name, step.tokens_in, step.cost_usd) == (
        "verify",
        "verifier",
        300,
        0.001,
    )
    assert tracer.usage(0).llm_calls == 1


@pytest.mark.parametrize(
    "reply", ["not json", "[]", '{"claims": "x"}', '{"claims": [{"claim": "a"}]}', ""]
)
def test_unparseable_output_keeps_the_draft(monkeypatch, tracer, reply: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(vf, "call_llm", _llm(reply))
    result = verify_answer(tracer, _answer(), _labels("a"))
    assert result.failed and result.ok is False and result.claims == []
    assert tracer.steps[-1].error.startswith("verify_failed")


def test_an_llm_error_keeps_the_draft(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(vf, "call_llm", _llm("", error="rate limited"))
    assert verify_answer(tracer, _answer(), _labels("a")).failed


def test_a_raising_llm_keeps_the_draft(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    def boom(req):  # type: ignore[no-untyped-def]
        raise ConnectionError("down")

    monkeypatch.setattr(vf, "call_llm", boom)
    result = verify_answer(tracer, _answer(), _labels("a"))
    assert result.failed and "down" in tracer.steps[-1].error


def test_the_spend_cap_propagates(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    from server.llm.gateway import SpendCapExceeded

    def capped(req):  # type: ignore[no-untyped-def]
        raise SpendCapExceeded("cap")

    monkeypatch.setattr(vf, "call_llm", capped)
    with pytest.raises(SpendCapExceeded):
        verify_answer(tracer, _answer(), _labels("a"))


def test_the_prompt_contains_the_evidence_and_the_draft(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    seen = {}

    def spy(req):  # type: ignore[no-untyped-def]
        seen["prompt"] = req.messages[0].content
        seen["json_mode"] = req.json_mode
        return LLMResponse(content=json.dumps(_claims()), tokens_in=1, tokens_out=1)

    monkeypatch.setattr(vf, "call_llm", spy)
    verify_answer(tracer, _answer(long="The auditor is KKC."), _labels("KKC audits Bajaj."))
    assert "[E1]" in seen["prompt"] and "KKC audits Bajaj." in seen["prompt"]
    assert "The auditor is KKC." in seen["prompt"] and "{evidence_blocks}" not in seen["prompt"]
    assert seen["json_mode"] is True


# --- numbers ---------------------------------------------------------------


def test_a_number_that_appears_in_a_calculate_result_is_supported() -> None:
    labels = _labels("calculate(48.2 + 12.5) = 60.7", "Tata Steel paid some fees.")
    assert number_supported("60.7", labels)
    assert number_supported("₹ 60.7 crore", labels)


def test_a_number_that_appears_nowhere_is_unsupported() -> None:
    assert not number_supported("99", _labels("calculate(48.2 + 12.5) = 60.7"))


def test_a_number_in_a_fact_after_unit_formatting_is_supported() -> None:
    labels = _labels("Company A —[RELATED-PARTY TXN: Sale of goods; ₹ 48.20 crore]→ Company B")
    assert number_supported("48.2", labels)
    assert number_supported("48.20 crore", labels)


def test_numbers_match_within_one_percent_and_commas_are_ignored() -> None:
    assert number_supported("1,234.5", _labels("total 1234.9"))
    assert not number_supported("1,234.5", _labels("total 1300"))


def test_a_non_numeric_answer_has_nothing_to_check() -> None:
    assert number_supported("Deloitte", _labels("anything"))


def test_a_number_answer_with_no_support_adds_an_unsupported_claim(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(vf, "call_llm", _llm(_claims(("total is 99", "SUPPORTED", ["E1"]))))
    answer = _answer("99", "The total is 99 [E1].", AnswerType.NUMBER)
    result = verify_answer(tracer, answer, _labels("calculate(48.2 + 12.5) = 60.7"))
    assert not result.ok
    assert any("appears in no evidence" in c.claim for c in result.unsupported)


def test_a_supported_number_passes_both_checks(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(vf, "call_llm", _llm(_claims(("total is 60.7", "SUPPORTED", ["E1"]))))
    answer = _answer("60.7", "The total is 60.7 [E1].", AnswerType.NUMBER)
    assert verify_answer(tracer, answer, _labels("calculate(48.2 + 12.5) = 60.7")).ok


def test_claim_model_rejects_unknown_verdicts() -> None:
    with pytest.raises(ValueError):
        Claim(claim="a", verdict="MAYBE")  # type: ignore[arg-type]
