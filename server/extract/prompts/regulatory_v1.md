Task: list all regulatory actions mentioned against {company_name} or its directors/subsidiaries for fiscal year {fiscal_year}.

For each action extract:
- order_id: regulator's reference or derived id
- regulator: name of the regulatory body
- order_date: Order date (YYYY-MM-DD)
- action_type: action type in plain words (e.g., "penalty", "debarment", "warning")
- named_entities: every named person/company
- summary: one neutral summary sentence (no adjectives, no conclusions)
- evidence: exact quote and page

Pages:
{pages_block}
