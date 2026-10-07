import json
import logging
from functools import cache

import yaml
from pydantic import BaseModel

from server.resolve.normalize import norm_company, norm_person
from server.settings import ROOT
from server.store.db import connect

COMPANIES_YAML = ROOT / "config/companies.yaml"

logger = logging.getLogger(__name__)


class Mention(BaseModel):
    mention_id: str  # f"{record_id}:{role}"  e.g. "r123:person", "r123:company"
    kind: str  # person | company | audit_firm
    raw_name: str
    norm_name: str
    ids: dict  # {"din": "..."} | {"cin": "..."} | {"frn": "..."}
    context_company_id: str | None  # the reporting company, for blocking
    record_id: str


@cache
def config_company_names() -> dict[str, str]:
    """company_id → legal name for every company in config/companies.yaml."""
    if not COMPANIES_YAML.exists():
        return {}
    data = yaml.safe_load(COMPANIES_YAML.read_text()) or {}
    return {c["company_id"]: c["name"] for c in data.get("companies", [])}


def context_company_mention(record_id: str, company_id: str) -> Mention:
    """The reporting company of a record. It is named by its legal name, not
    its ticker-style id, so that the same company appearing as another
    filer's counterparty ("Tata Steel Limited") resolves to this entity and
    name search / MENTIONS linking can find it."""
    name = config_company_names().get(company_id, company_id)
    return Mention(
        mention_id=f"{record_id}:context_company",
        kind="company",
        raw_name=name,
        norm_name=norm_company(name),
        ids={"company_id": company_id},
        context_company_id=company_id,
        record_id=record_id,
    )


def build_mentions() -> list[Mention]:
    """Scans all accepted records and builds a list of resolved Mentions."""
    conn = connect()
    rows = conn.execute("""
        SELECT r.record_id, r.record_type, r.payload_json, d.company_id
        FROM records r
        JOIN documents d ON r.doc_id = d.doc_id
        WHERE r.status = 'accepted' OR r.status = 'fixed'
    """).fetchall()
    conn.close()

    mentions = []

    for row in rows:
        record_id, record_type, payload_json, company_id = row
        payload = json.loads(payload_json)

        # 1. Directors -> Person mention + Company mention (context)
        if record_type == "directors":
            if "person_name" in payload and payload["person_name"]:
                mentions.append(
                    Mention(
                        mention_id=f"{record_id}:person",
                        kind="person",
                        raw_name=payload["person_name"],
                        norm_name=norm_person(payload["person_name"]),
                        ids={"din": payload["din"]} if payload.get("din") else {},
                        context_company_id=company_id,
                        record_id=record_id,
                    )
                )

            mentions.append(context_company_mention(record_id, company_id))

        # 2. RPT -> Context Company + Counterparty
        elif record_type == "rpt":
            mentions.append(context_company_mention(record_id, company_id))

            if "counterparty_name" in payload and payload["counterparty_name"]:
                raw_cp = payload["counterparty_name"]
                # Heuristic to decide person vs company based on suffixes
                lower_cp = raw_cp.lower()
                suffixes = [
                    "limited",
                    "ltd",
                    "private",
                    "pvt",
                    "llp",
                    "trust",
                    "inc",
                    "co",
                    "corporation",
                ]
                is_company = any(f" {s}" in lower_cp or lower_cp.endswith(s) for s in suffixes)

                kind = "company" if is_company else "person"
                norm = norm_company(raw_cp) if is_company else norm_person(raw_cp)

                mentions.append(
                    Mention(
                        mention_id=f"{record_id}:counterparty",
                        kind=kind,
                        raw_name=raw_cp,
                        norm_name=norm,
                        ids={},
                        context_company_id=company_id,
                        record_id=record_id,
                    )
                )

        # 3. Auditor -> Context Company + Audit Firm
        elif record_type == "auditor":
            mentions.append(context_company_mention(record_id, company_id))
            if "firm_name" in payload and payload["firm_name"]:
                mentions.append(
                    Mention(
                        mention_id=f"{record_id}:audit_firm",
                        kind="audit_firm",
                        raw_name=payload["firm_name"],
                        norm_name=norm_company(
                            payload["firm_name"]
                        ),  # Audit firms normalized like companies
                        ids={"frn": payload["firm_registration_no"]}
                        if payload.get("firm_registration_no")
                        else {},
                        context_company_id=company_id,
                        record_id=record_id,
                    )
                )

        # 4. Subsidiary -> parent (context) company + subsidiary company
        elif record_type == "subsidiaries":
            mentions.append(context_company_mention(record_id, company_id))
            if payload.get("subsidiary_name"):
                sub_name = payload["subsidiary_name"]
                mentions.append(
                    Mention(
                        mention_id=f"{record_id}:subsidiary",
                        kind="company",
                        raw_name=sub_name,
                        norm_name=norm_company(sub_name),
                        ids={},
                        context_company_id=company_id,
                        record_id=record_id,
                    )
                )

        # (Shareholding and Regulatory mentions can be added here as needed)

    return mentions
