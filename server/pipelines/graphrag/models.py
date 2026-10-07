import hashlib
from typing import Any

from pydantic import BaseModel, Field

# Reverse edge names declared in schema.gsql, mapped back to the forward edge so a
# triple always reads in the direction the fact was extracted.
REVERSE_TO_FORWARD = {
    "HAS_DIRECTOR": "DIRECTOR_OF",
    "HAS_PARTY": "PARTY_TO",
    "HAS_SUBSIDIARY": "SUBSIDIARY_OF",
    "AUDITS": "AUDITED_BY",
    "HELD_BY": "HOLDS_STAKE",
    "NAMES": "NAMED_IN",
    "SECTOR_OF": "IN_SECTOR",
}
FACT_EDGES = (
    "DIRECTOR_OF",
    "PARTY_TO",
    "AUDITED_BY",
    "SUBSIDIARY_OF",
    "HOLDS_STAKE",
    "NAMED_IN",
    "IN_SECTOR",
)


def synthetic_edge_id(rel: str, src: str, dst: str) -> str:
    return hashlib.sha256(f"{rel}:{src}:{dst}".encode()).hexdigest()[:16]


class Triple(BaseModel):
    edge_id: str
    rel: str
    src_id: str
    src_type: str
    dst_id: str
    dst_type: str
    attrs: dict[str, Any] = Field(default_factory=dict)
    txn: dict[str, Any] | None = None  # attributes of the RelatedPartyTxn vertex, if any
    hop: int = 1

    @property
    def fiscal_year(self) -> str:
        return str(self.attrs.get("fiscal_year") or (self.txn or {}).get("fiscal_year") or "")

    @property
    def doc_id(self) -> str:
        return str(self.attrs.get("doc_id") or "")

    @property
    def page(self) -> int:
        return int(self.attrs.get("page") or 0)

    @property
    def quote(self) -> str:
        return str(self.attrs.get("quote") or "")

    @property
    def txn_id(self) -> str | None:
        if self.rel != "PARTY_TO":
            return None
        return self.dst_id if self.dst_type == "RelatedPartyTxn" else self.src_id

    def endpoints(self) -> tuple[str, str]:
        return self.src_id, self.dst_id
