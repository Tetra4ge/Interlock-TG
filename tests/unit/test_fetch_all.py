import pytest

from server.ingest import fetcher
from server.ingest.models import CompaniesFile, CompanyConfig
from server.ingest.sources.exchange import ExchangeAdapter


def test_manual_needed_is_logged_once_per_target(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[tuple] = []

    def record(**kw: object) -> None:
        attempts.append((kw["company_id"], kw["doc_type"], kw["fiscal_year"], kw["outcome"]))

    def latest(company_id: str, doc_type: str, fiscal_year: str) -> str | None:
        matches = [a[3] for a in attempts if a[:3] == (company_id, doc_type, fiscal_year)]
        return matches[-1] if matches else None

    monkeypatch.setattr(fetcher, "already_have", lambda *_a: False)
    monkeypatch.setattr(fetcher, "record_attempt", record)
    monkeypatch.setattr(fetcher, "latest_attempt_outcome", latest)

    cf = CompaniesFile(
        fiscal_years=["FY2022-23", "FY2023-24"],
        doc_types=["annual_report"],
        companies=[CompanyConfig(company_id="C1", name="C1 Ltd", sector="s", selection_reason="r")],
    )
    fetcher.fetch_all(cf, [ExchangeAdapter()], client=None)  # type: ignore[arg-type]
    first_run = len(attempts)
    fetcher.fetch_all(cf, [ExchangeAdapter()], client=None)  # type: ignore[arg-type]

    assert first_run == 6  # 3 doc types x 2 fiscal years
    assert len(attempts) == first_run
    assert {a[3] for a in attempts} == {"manual_needed"}
