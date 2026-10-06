import json
import logging
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from server.extract.grounding import check_grounding
from server.extract.rules.shareholding_table import parse_shareholding_table
from server.extract.schemas import (
    AuditorsOut,
    DirectorsOut,
    RegulatoryActionsOut,
    RelatedPartyTxnsOut,
    ShareholdingOut,
    SubsidiariesOut,
)
from server.extract.units import rupees_from_raw
from server.extract.validate import validate_record
from server.llm.gateway import call_llm
from server.llm.models import LLMMessage, LLMRequest
from server.parse.tokens import estimate_tokens
from server.store.db import connect

logger = logging.getLogger(__name__)


class SchemaInvalidError(Exception):
    pass


SECTION_TO_TASK = {
    "governance": ["directors"],
    "board_report": ["directors"],
    "auditor": ["auditor"],
    "related_party_standalone": ["rpt"],
    "subsidiaries": ["subsidiaries"],
    "shareholding": ["shareholding"],
    "regulatory": ["regulatory"],
}

TASK_SCHEMAS: dict[str, type[BaseModel]] = {
    "directors": DirectorsOut,
    "shareholding": ShareholdingOut,
    "rpt": RelatedPartyTxnsOut,
    "auditor": AuditorsOut,
    "subsidiaries": SubsidiariesOut,
    "regulatory": RegulatoryActionsOut,
}


REGULATORY_DOC_TYPE = "regulatory_order"


def fiscal_year_end(fiscal_year: str | None) -> date | None:
    """ "FY2023-24" → 2024-03-31, the balance-sheet date of an Indian fiscal year."""
    m = re.fullmatch(r"FY(\d{4})-\d{2}", fiscal_year or "")
    return date(int(m.group(1)) + 1, 3, 31) if m else None


def load_parsed(doc_id: str) -> dict:
    parsed_file = Path(f"data/parsed/{doc_id}.json")
    if not parsed_file.exists():
        return {}
    return json.loads(parsed_file.read_text())


def page_windows(pages: list[dict], max_tokens: int = 4000) -> list[list[dict]]:
    """Group pages into windows with 1 page overlap."""
    windows = []
    current_window: list[dict] = []
    current_tokens = 0

    for page in pages:
        text = page.get("cleaned_text", page.get("text", ""))
        tokens = estimate_tokens(text)

        if current_tokens + tokens > max_tokens and current_window:
            windows.append(current_window)
            # Start new window with 1 page overlap
            current_window = [current_window[-1], page]
            current_tokens = estimate_tokens(current_window[0].get("cleaned_text", "")) + tokens
        else:
            current_window.append(page)
            current_tokens += tokens

    if current_window:
        windows.append(current_window)

    return windows


def format_pages_block(pages: list[dict]) -> str:
    blocks = []
    for page in pages:
        blocks.append(f"[PAGE {page['page_no']}]\n{page.get('cleaned_text', page.get('text', ''))}")
    return "\n\n".join(blocks)


def _normalize_records_json(content: str, doc_id: str) -> dict:
    """Patch the two systematic shape mismatches between what the prompts
    ask for and what Evidence (schemas.py) requires, before validation:

    - evidence.doc_id is never mentioned in any task prompt (the model has
      no way to know it), but the caller already knows it -- inject it
      rather than expect the model to invent/echo an ID.
    - evidence.page: the system prompt tells the model to cite pages using
      the input's own "[PAGE 45]" label (rule 2), but Evidence.page wants a
      bare int -- pull the digits out rather than rely on prompt wording
      alone to stop the model from ever echoing the brackets back.
    """
    data = json.loads(content)
    for rec in data.get("records", []) if isinstance(data, dict) else []:
        if not isinstance(rec, dict):
            continue
        evidence = rec.get("evidence")
        if not isinstance(evidence, dict):
            continue
        evidence.setdefault("doc_id", doc_id)
        page = evidence.get("page")
        if isinstance(page, str):
            digits = "".join(ch for ch in page if ch.isdigit())
            if digits:
                evidence["page"] = int(digits)
    return data


def llm_extract(task: str, doc_row: dict, window_pages: list[dict]) -> list[Any]:
    sys_prompt = Path("server/extract/prompts/system_v1.md").read_text()
    task_prompt_template = Path(f"server/extract/prompts/{task}_v1.md").read_text()

    pages_block = format_pages_block(window_pages)

    # Regulatory orders are not filed by a company for a fiscal year, so
    # both columns are NULL for them.
    task_prompt = task_prompt_template.format(
        company_name=doc_row.get("company_id") or "any company or person named in this order",
        fiscal_year=doc_row.get("fiscal_year") or "any period",
        pages_block=pages_block,
    )

    schema_model = TASK_SCHEMAS[task]

    # $0 Groq free-tier model (config/models.yaml) -- llama3-70b-8192 has
    # since been decommissioned by Groq. Deliberately NOT the same model as
    # the shared answer step (server/pipelines/common/answer.py): Groq's
    # per-model daily token cap is shared across every caller of that model,
    # and bulk extraction's volume can exhaust openai/gpt-oss-20b's cap
    # before the answer step ever gets to run.
    model = "openai/gpt-oss-120b"

    req = LLMRequest(
        provider="groq",
        model=model,
        messages=[
            LLMMessage(role="system", content=sys_prompt),
            LLMMessage(role="user", content=task_prompt),
        ],
        json_mode=True,
        temperature=0.0,
    )

    try:
        resp = call_llm(req)
    except Exception as e:
        # The gateway/provider can raise (FatalError, RetryableError after
        # retries are exhausted, a mid-call network drop, ...) rather than
        # returning an errored LLMResponse -- e.g. Groq's own json_mode
        # validation occasionally fails server-side with an empty
        # `failed_generation`. Treat it the same as a schema failure so it
        # costs this one task/window, not the rest of the document.
        raise SchemaInvalidError(str(e)) from e
    if resp.error:
        logger.error(f"LLM call error: {resp.error}")
        return []

    doc_id = doc_row.get("doc_id", "")
    try:
        parsed_out = schema_model.model_validate(_normalize_records_json(resp.content, doc_id))
        return getattr(parsed_out, "records", [])
    except (ValidationError, ValueError) as e:
        # ValueError also catches json.JSONDecodeError from
        # _normalize_records_json when the model didn't return valid JSON
        # at all. Retry once on either kind of failure.
        logger.warning("LLM Extraction validation failed. Retrying once...")
        retry_prompt = (
            f"{task_prompt}\n\nYour previous output failed validation: {e}\nReturn corrected JSON."
        )
        req.messages[1].content = retry_prompt
        try:
            resp2 = call_llm(req)
        except Exception as e2:
            raise SchemaInvalidError(str(e2)) from e2

        if resp2.error:
            return []

        try:
            normalized2 = _normalize_records_json(resp2.content, doc_id)
            parsed_out2 = schema_model.model_validate(normalized2)
            return getattr(parsed_out2, "records", [])
        except (ValidationError, ValueError) as e2:
            logger.error(f"Failed LLM extraction validation twice: {e2}")
            raise SchemaInvalidError(str(e2)) from e2


DOCUMENT_COLUMNS = [
    "doc_id",
    "company_id",
    "doc_type",
    "fiscal_year",
    "source_url",
    "file_path",
    "fetched_at",
    "status",
    "error",
]


def _write(sql: str, params: list) -> None:
    """Open a fresh connection for a single write and close it immediately.

    extract_document() spans many slow, sequential LLM calls (one per
    section/window) between writes. A single connection held open across
    that whole span has repeatedly gone stale mid-document -- Turso's
    remote Hrana stream either idle-times-out an open transaction or the
    stream itself expires ("stream not found"). Reconnecting per write
    keeps each connection's lifetime to a single fast round-trip, which
    eliminates both failure modes.
    """
    c = connect()
    try:
        c.execute(sql, params)
        c.commit()
    finally:
        c.close()


def extract_document(doc_id: str, run_id: str) -> None:
    conn = connect()
    doc_row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", [doc_id]).fetchone()
    if not doc_row:
        conn.close()
        return

    doc = dict(zip(DOCUMENT_COLUMNS, doc_row, strict=True))

    parsed = load_parsed(doc_id)
    if not parsed:
        conn.close()
        return

    pages = parsed.get("pages", [])
    tables = parsed.get("tables", [])

    sections = conn.execute(
        "SELECT kind, page_start, page_end FROM sections WHERE doc_id = ?", [doc_id]
    ).fetchall()
    conn.close()

    if doc.get("doc_type") == REGULATORY_DOC_TYPE and pages:
        # An order is short and is about regulatory action from start to end:
        # the whole document is one "regulatory" section.
        sections = [("regulatory", pages[0]["page_no"], pages[-1]["page_no"])]

    if not sections:
        logger.warning(f"No sections detected for {doc_id}. Flagging document.")
        _write("UPDATE documents SET status = 'flagged' WHERE doc_id = ?", [doc_id])
        return

    _write(
        "INSERT OR IGNORE INTO extraction_runs "
        "(run_id, started_at, model, prompt_version, git_commit) "
        "VALUES (?, datetime('now'), ?, ?, ?)",
        [run_id, "groq:openai/gpt-oss-120b", "v1", "HEAD"],
    )

    # A shareholding table in an annual report is stated as of the year end.
    as_of = fiscal_year_end(doc.get("fiscal_year"))

    for section_row in sections:
        kind, page_start, page_end = section_row
        for task in SECTION_TO_TASK.get(kind, []):
            sec_pages = [p for p in pages if page_start <= p["page_no"] <= page_end]

            for window in page_windows(sec_pages, max_tokens=4000):
                recs = []
                try:
                    if task == "shareholding":
                        window_page_nos = [p["page_no"] for p in window]
                        window_tables = [t for t in tables if t["page_no"] in window_page_nos]

                        # Without a known year end the rule parser cannot date
                        # a holding; leave those documents to the LLM prompt.
                        if as_of is not None:
                            for t in window_tables:
                                r = parse_shareholding_table(
                                    doc_id,
                                    doc.get("company_id") or "",
                                    t["page_no"],
                                    t["cells"],
                                    as_of,
                                )
                                if r:
                                    recs.extend(r)

                        if not recs:
                            recs = llm_extract(task, doc, window)
                    else:
                        recs = llm_extract(task, doc, window)
                except SchemaInvalidError:
                    record_id = str(uuid.uuid4())
                    _write(
                        "INSERT INTO records "
                        "(record_id, run_id, doc_id, record_type, payload_json, status, reason) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [record_id, run_id, doc_id, task, "{}", "rejected", "schema_invalid"],
                    )
                    continue

                for rec in recs:
                    status, reason = "accepted", ""

                    # RPT amounts: the rupee value is computed from the figure
                    # as printed (amount_raw) and its unit. The model's own
                    # amount_inr is ignored -- it is sometimes the printed
                    # figure and sometimes already multiplied out.
                    if hasattr(rec, "amount_inr") and hasattr(rec, "amount_raw"):
                        real_val = rupees_from_raw(getattr(rec, "amount_raw", "") or "")
                        if real_val is None:
                            status, reason = "review", "unit_unknown"
                        else:
                            rec.amount_inr = real_val

                    if status == "accepted":
                        status, reason = check_grounding(rec, parsed)

                    if status == "accepted":
                        v_status, v_reason = validate_record(rec)
                        if v_status != "accepted":
                            status = v_status
                            reason = v_reason

                    # Also mark ungrounded as 'review' instead of just 'rejected' to surface them
                    if status == "rejected":
                        status = "review"

                    payload_json = (
                        rec.model_dump_json() if hasattr(rec, "model_dump_json") else "{}"
                    )
                    record_id = str(uuid.uuid4())

                    _write(
                        "INSERT INTO records "
                        "(record_id, run_id, doc_id, record_type, payload_json, status, reason) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [record_id, run_id, doc_id, task, payload_json, status, reason or ""],
                    )

                    if status == "review":
                        _write(
                            "INSERT INTO review_queue (record_id, reason, created_at) "
                            "VALUES (?, ?, datetime('now'))",
                            [record_id, reason or ""],
                        )

    _write("UPDATE documents SET status = 'extracted' WHERE doc_id = ?", [doc_id])
    _write("UPDATE extraction_runs SET finished_at = datetime('now') WHERE run_id = ?", [run_id])


def extract_all(run_id: str) -> None:
    conn = connect()
    # Regulatory orders used to be flagged as "no sections" and never
    # extracted; pick those up again as well.
    rows = conn.execute(
        "SELECT doc_id FROM documents WHERE status = 'parsed' "
        "OR (status = 'flagged' AND doc_type = ?)",
        [REGULATORY_DOC_TYPE],
    ).fetchall()
    conn.close()

    for (doc_id,) in rows:
        print(f"Extracting records for document {doc_id}...")
        try:
            extract_document(doc_id, run_id)
        except Exception as e:
            logger.exception(f"Failed to extract {doc_id}")
            print(f"Failed to extract {doc_id}: {e}")
            try:
                _write(
                    "UPDATE documents SET status = 'failed', error = ? WHERE doc_id = ?",
                    [repr(e), doc_id],
                )
            except Exception:
                # Whatever broke the extraction (e.g. a transient network
                # outage) can just as easily break this status write too --
                # don't let a doomed cleanup attempt crash the whole batch.
                logger.exception(f"Also failed to record failure status for {doc_id}")

    print(f"Extraction complete for run {run_id}.")
