import pytest

from server.pipelines.common.scope import detect_company


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Who is the statutory auditor of Tata Steel in FY2023-24?", "TATASTEEL"),
        ("List the independent directors of Bajaj Finance in FY2023-24.", "BAJFINANCE"),
        ("What is the net profit of Bajaj Finserv?", "BAJAJFINSV"),
        ("Is Tata Motors Finance a related party of Tata Motors?", "TATAMOTORS"),
        ("What is the TRF revenue?", "TRF"),
    ],
)
def test_detects_named_company(question: str, expected: str) -> None:
    assert detect_company(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Who audits Bajaj?",
        "Compare Tata Steel and Tata Motors auditors.",
        "What is the weather today?",
    ],
)
def test_no_or_ambiguous_company_returns_none(question: str) -> None:
    assert detect_company(question) is None
