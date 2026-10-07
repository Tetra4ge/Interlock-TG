import pytest

from server.eval import judge as judge_mod
from server.llm.gateway import OfflineCacheMiss, SpendCapExceeded
from server.llm.models import LLMResponse


def _stub(
    monkeypatch: pytest.MonkeyPatch, content: str | None = None, exc: Exception | None = None
):
    def fake(req):
        if exc is not None:
            raise exc
        return LLMResponse(content=content or "", tokens_in=1, tokens_out=1)

    monkeypatch.setattr(judge_mod, "call_llm", fake)


def test_faithful_verdict_scores_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, '{"faithful": true, "reason": "stated in E1"}')
    v = judge_mod.judge_faithfulness("q", "a", ["e"])
    assert v is not None and v.faithfulness == 1.0 and v.reason == "stated in E1"


def test_unfaithful_verdict_scores_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, '{"faithful": false, "reason": "not in evidence"}')
    assert judge_mod.judge_faithfulness("q", "a", ["e"]).faithfulness == 0.0


@pytest.mark.parametrize(
    "exc", [OfflineCacheMiss("miss"), SpendCapExceeded("cap"), RuntimeError("net")]
)
def test_unreachable_judge_returns_none_not_a_score(monkeypatch, exc) -> None:
    _stub(monkeypatch, exc=exc)
    assert judge_mod.judge_faithfulness("q", "a", ["e"]) is None


def test_unparseable_judge_output_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, "not json at all")
    assert judge_mod.judge_faithfulness("q", "a", ["e"]) is None


def test_missing_faithful_key_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, '{"reason": "no verdict"}')
    assert judge_mod.judge_faithfulness("q", "a", ["e"]) is None
