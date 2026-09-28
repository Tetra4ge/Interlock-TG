from server.ingest.models import CompanyConfig, DocumentTarget

DOC_TYPES = ["annual_report", "shareholding", "rpt_disclosure"]


class ExchangeAdapter:
    """Adapter for annual reports, shareholding patterns and RPT disclosures.

    `resolve_urls` is intentionally a stub returning [] for every target: Phase 1's
    source-check (docs/sources.md) found automated access to these sources either
    unconfirmed (company IR pages, not checked live) or actively blocked (NSE, at the
    TLS/HTTP layer). Per the phase doc, a complicated source goes manual rather than
    blocking the project on scraper development. `targets()` still runs so the fetcher
    can log a `manual_needed` fetch_attempts row for every expected document, which is
    what `docs/coverage.md` uses to tell you what to download by hand.
    """

    name = "exchange"

    def targets(self, company: CompanyConfig, fiscal_years: list[str]) -> list[DocumentTarget]:
        return [
            DocumentTarget(company_id=company.company_id, doc_type=doc_type, fiscal_year=fy)
            for doc_type in DOC_TYPES
            for fy in fiscal_years
        ]

    def resolve_urls(self, client: object, target: DocumentTarget) -> list[str]:
        return []
