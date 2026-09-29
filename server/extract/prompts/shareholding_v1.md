Task: list shareholding patterns of promoters and promoter groups for {company_name} in fiscal year {fiscal_year}.

For each shareholding record extract:
- holder_name: name of the shareholder
- holder_kind: "person", "company", or "category"
- company_name: {company_name}
- pct_holding: % of total shares held (number between 0 and 100)
- pct_pledged_of_holding: % pledged/encumbered if shown and as a percentage of that holder's shares (state which base the table uses in a note field)
- is_promoter_group: true for promoters/promoter groups, false otherwise
- as_of: date from the table heading (YYYY-MM-DD)
- evidence: exact quote and page

Pages:
{pages_block}
