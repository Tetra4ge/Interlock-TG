Identify what this question needs from a knowledge graph of Indian listed companies.

Graph relation types:
- DIRECTOR_OF (person -> company; role, independent, from, to, fiscal_year)
- HOLDS_STAKE (person/company -> company; pct, pledged_pct, promoter_group, as_of)
- SUBSIDIARY_OF (company -> company; pct)
- AUDITED_BY (company -> audit firm; fiscal_year)
- PARTY_TO (company/person -> related-party transaction; side) -- transactions have nature, amount_inr, fiscal_year
- NAMED_IN (company/person -> regulatory action; order_date, action_type)
- IN_SECTOR (company -> sector)

Return JSON only:
{
  "mentions": [{"text": "...", "kind": "company|person|audit_firm|sector|unknown"}],
  "relation_types": ["DIRECTOR_OF"],
  "fiscal_years": ["FY2023-24"],
  "is_global": false
}

Rules:
- "mentions" are the specific entities named in the question, exactly as written. Do not invent any.
- "relation_types" use only the names above.
- "fiscal_years" only if stated or clearly implied, formatted FY2023-24.
- "is_global" is true only when the question is about the whole dataset (for example "which sector ...", "how many companies ..."), not about specific named entities.
- Do not answer the question.

Question: {question}
