from pydantic import BaseModel


class CompanyConfig(BaseModel):
    company_id: str
    name: str
    exchange_codes: dict[str, str] = {}
    cin: str | None = None
    sector: str
    selection_reason: str


class CompaniesFile(BaseModel):
    fiscal_years: list[str]
    doc_types: list[str]
    companies: list[CompanyConfig]


class DocumentTarget(BaseModel):
    company_id: str | None
    doc_type: str
    fiscal_year: str | None
    period_label: str | None = None


class FetchResult(BaseModel):
    target: DocumentTarget
    url: str | None
    content: bytes | None
    http_status: int | None
    error: str | None
