import re
from functools import cache

import yaml

from server.pipelines.config import ROOT

COMPANIES_PATH = ROOT / "config/companies.yaml"
LEGAL_SUFFIXES = re.compile(r"\b(limited|ltd\.?)\b", re.IGNORECASE)
FISCAL_YEAR = re.compile(r"\bFY\s?(\d{4})\s?-\s?(\d{2})\b", re.IGNORECASE)


@cache
def _company_names() -> dict[str, str]:
    data = yaml.safe_load(COMPANIES_PATH.read_text()) or {}
    names: dict[str, str] = {}
    for c in data.get("companies", []):
        names[c["company_id"].lower()] = c["company_id"]
        core = LEGAL_SUFFIXES.sub("", c["name"]).strip().lower()
        names[core] = c["company_id"]
    return names


def detect_company(question: str) -> str | None:
    """Return the company_id named in the question, or None if zero or several
    companies match (an ambiguous question is searched across all companies)."""
    q = question.lower()
    matched = {
        cid for name, cid in _company_names().items() if re.search(rf"\b{re.escape(name)}\b", q)
    }
    return matched.pop() if len(matched) == 1 else None


def detect_fiscal_year(question: str) -> str | None:
    m = FISCAL_YEAR.search(question)
    return f"FY{m.group(1)}-{m.group(2)}" if m else None


def detect_filters(question: str) -> dict[str, str]:
    filters: dict[str, str] = {}
    company = detect_company(question)
    if company:
        filters["company_id"] = company
    year = detect_fiscal_year(question)
    if year:
        filters["fiscal_year"] = year
    return filters
