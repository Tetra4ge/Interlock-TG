from typing import Protocol

from server.ingest.models import CompanyConfig, DocumentTarget


class SourceAdapter(Protocol):
    name: str

    def targets(self, company: CompanyConfig, fiscal_years: list[str]) -> list[DocumentTarget]:
        """Expand config into concrete document targets for this company."""
        ...

    def resolve_urls(self, client: object, target: DocumentTarget) -> list[str]:
        """Find the PDF URL(s) for a target. Return [] if the source requires
        manual download -- the fetcher records that as `manual_needed` rather
        than treating it as a failure."""
        ...
