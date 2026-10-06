import pytest

from server.pipelines.common.scope import detect_company, detect_filters, detect_fiscal_year


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Who is the statutory auditor of Tata Steel in FY2023-24?", "TATASTEEL"),
        ("List the independent directors of Bajaj Finance in FY2023-24.", "BAJFINANCE"),
        ("What is the net profit of Bajaj Finserv?", "BAJAJFINSV"),
        ("Is Tata Motors Finance a related party of Tata Motors?", "TATAMOTORS"),
        ("What is the TRF revenue?", "TRF"),
        ("Who chairs Tata Power in FY2022-23?", "TATAPOWER"),
        ("Who audits The Tata Power Company Limited?", "TATAPOWER"),
        ("List the directors of Bajaj Holdings & Investment.", "BAJAJHLDNG"),
        ("List the directors of Bajaj Holdings and Investment Ltd.", "BAJAJHLDNG"),
        ("Who is the CFO of Tata Consumer Products?", "TATACONSUM"),
        ("Who is the MD of Bajaj Auto?", "BAJAJ-AUTO"),
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


def test_detects_fiscal_year_in_question() -> None:
    assert detect_fiscal_year("List the directors in FY2023-24.") == "FY2023-24"
    assert detect_fiscal_year("What happened in fy 2022 - 23?") == "FY2022-23"
    assert detect_fiscal_year("What is the CEO?") is None


def test_filters_combine_company_and_year() -> None:
    assert detect_filters("Who is the CEO of Tata Steel in FY2023-24?") == {
        "company_id": "TATASTEEL",
        "fiscal_year": "FY2023-24",
    }
