"""Builders for GraphRAG tests: raw `expand_hop` output and Triples."""

from typing import Any

from server.pipelines.graphrag.models import Triple


def raw_edge(
    rel: str,
    src: tuple[str, str],
    dst: tuple[str, str],
    edge_id: str | None = None,
    **attrs: Any,
) -> dict:
    attributes = dict(attrs)
    if edge_id is not None:
        attributes["edge_id"] = edge_id
    return {
        "e_type": rel,
        "directed": True,
        "from_id": src[0],
        "from_type": src[1],
        "to_id": dst[0],
        "to_type": dst[1],
        "attributes": attributes,
    }


def raw_result(edges: list[dict], txns: dict[str, dict] | None = None) -> list[dict]:
    return [
        {"edges": edges},
        {
            "txns": [
                {"v_id": k, "v_type": "RelatedPartyTxn", "attributes": v}
                for k, v in (txns or {}).items()
            ]
        },
    ]


def director(person: str, company: str, fy: str, edge_id: str, **extra: Any) -> dict:
    return raw_edge(
        "DIRECTOR_OF",
        (person, "Person"),
        (company, "Company"),
        edge_id,
        role=extra.pop("role", "Independent Director"),
        independent=extra.pop("independent", True),
        fiscal_year=fy,
        doc_id=extra.pop("doc_id", "d" * 24),
        page=extra.pop("page", 46),
        quote=extra.pop("quote", "Mr. Anil Kumar Sharma | Independent Director"),
        **extra,
    )


def txn_edges(
    txn: str, reporting: str, counterparty: str, tag: str, fy: str = "FY2022-23"
) -> list[dict]:
    common = {
        "doc_id": "9" * 24,
        "page": 212,
        "quote": "Example Trading Private Limited | Sale of goods | 48.20",
    }
    return [
        raw_edge(
            "PARTY_TO",
            (reporting, "Company"),
            (txn, "RelatedPartyTxn"),
            f"{tag}-r",
            side="reporting",
            **common,
        ),
        raw_edge(
            "PARTY_TO",
            (counterparty, "Company"),
            (txn, "RelatedPartyTxn"),
            f"{tag}-c",
            side="counterparty",
            **common,
        ),
    ]


def triple(
    rel: str = "DIRECTOR_OF",
    src: str = "P:1",
    dst: str = "C:1",
    edge_id: str = "e1",
    hop: int = 1,
    fy: str = "FY2023-24",
    **attrs: Any,
) -> Triple:
    types = {"DIRECTOR_OF": ("Person", "Company"), "AUDITED_BY": ("Company", "AuditFirm")}
    s, d = types.get(rel, ("Company", "Company"))
    return Triple(
        edge_id=edge_id,
        rel=rel,
        src_id=src,
        src_type=s,
        dst_id=dst,
        dst_type=d,
        attrs={"fiscal_year": fy, **attrs},
        hop=hop,
    )
