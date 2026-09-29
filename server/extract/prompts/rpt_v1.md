Task: list related party transactions for {company_name} in fiscal year {fiscal_year}.

For each transaction extract:
- reporting_company: {company_name}
- counterparty_name: the other party involved
- relationship: as disclosed, e.g. "Subsidiary", "KMP", "Entity controlled by promoter"
- nature: e.g. "Sale of goods", "Loan given"
- amount_inr: amount in rupees (number only)
- amount_raw: amount as printed (copy the unit line into amount_raw context, e.g. "12.5 (₹ crore)")
  Note: Tables often show two years side by side — take the column matching {fiscal_year} only.
- fiscal_year: {fiscal_year}
- evidence: exact quote and page

Pages:
{pages_block}
