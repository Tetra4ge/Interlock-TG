Task: list every director of {company_name} mentioned in this board composition section
for fiscal year {fiscal_year}.

For each director extract:
- person_name: as written
- din: the 8-digit Director Identification Number if printed, else null
- role: category as written (e.g. "Independent Director", "Managing Director", "Non-Executive Director")
- is_independent: true if the category says independent, false if it clearly says otherwise, null if unclear
- appointed_on / ceased_on: only if a date is stated on these pages (YYYY-MM-DD)
- evidence: exact quote and page

Pages:
{pages_block}
