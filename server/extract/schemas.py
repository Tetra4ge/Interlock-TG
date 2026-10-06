from datetime import date

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    doc_id: str
    page: int
    quote: str = Field(min_length=8, max_length=600)


class DirectorRecord(BaseModel):
    person_name: str
    din: str | None = None
    company_name: str
    role: str
    is_independent: bool | None = None
    appointed_on: date | None = None
    ceased_on: date | None = None
    fiscal_year: str
    evidence: Evidence


class DirectorsOut(BaseModel):
    records: list[DirectorRecord]


class ShareholdingRecord(BaseModel):
    holder_name: str
    holder_kind: str
    company_name: str
    pct_holding: float = Field(ge=0, le=100)
    pct_pledged_of_holding: float | None = Field(default=None, ge=0, le=100)
    is_promoter_group: bool | None = None
    as_of: date
    evidence: Evidence


class ShareholdingOut(BaseModel):
    records: list[ShareholdingRecord]


class RelatedPartyTxnRecord(BaseModel):
    reporting_company: str
    counterparty_name: str
    relationship: str
    nature: str
    amount_inr: float = Field(ge=0)
    amount_raw: str
    fiscal_year: str
    evidence: Evidence


class RelatedPartyTxnsOut(BaseModel):
    records: list[RelatedPartyTxnRecord]


class AuditorRecord(BaseModel):
    company_name: str
    firm_name: str
    firm_registration_no: str | None = None
    fiscal_year: str
    evidence: Evidence


class AuditorsOut(BaseModel):
    records: list[AuditorRecord]


class SubsidiaryRecord(BaseModel):
    parent_company: str
    subsidiary_name: str
    pct_held: float | None = Field(default=None, ge=0, le=100)
    as_of: date | None = None
    evidence: Evidence


class SubsidiariesOut(BaseModel):
    records: list[SubsidiaryRecord]


class RegulatoryActionRecord(BaseModel):
    order_id: str
    regulator: str
    order_date: date
    action_type: str
    named_entities: list[str]
    summary: str
    evidence: Evidence


class RegulatoryActionsOut(BaseModel):
    records: list[RegulatoryActionRecord]
