# Metric schema (v1)

Source of truth for what Annualyst extracts. All monetary values are normalised to ₹ crore.
Record standalone and consolidated separately; consolidated is the default view.

"XBRL check" = can be auto-verified against the exchange XBRL financial results filing.
Before relying on a check, confirm the field actually exists in the downloaded XBRL for that company and year — coverage varies by format (Ind AS, banking, NBFC).

## Income statement
| # | Metric | Key | XBRL check | Notes |
|---|---|---|---|---|
| 1 | Revenue from operations | `revenue_ops` | Yes | Not "total income" |
| 2 | Other income | `other_income` | Yes | Watch if large vs revenue |
| 3 | Total expenses | `total_expenses` | Yes | |
| 4 | Depreciation & amortisation | `depreciation` | Yes | |
| 5 | Finance costs | `finance_costs` | Yes | |
| 6 | Profit before tax | `pbt` | Yes | Before exceptional items noted separately |
| 7 | Tax expense | `tax_expense` | Yes | Current + deferred |
| 8 | Net profit (PAT) | `pat` | Yes | Attributable to owners when consolidated |
| 9 | Basic EPS (₹) | `eps_basic` | Yes | Per share, not in crore |
| 10 | EBITDA | `ebitda` | Derived | PBT + finance costs + depreciation − other income |

## Balance sheet
| # | Metric | Key | XBRL check | Notes |
|---|---|---|---|---|
| 11 | Total assets | `total_assets` | Check | Often in half-year results |
| 12 | Total equity | `total_equity` | Check | |
| 13 | Total borrowings | `borrowings` | Check | Non-current + current |
| 14 | Trade receivables | `receivables` | Check | Non-current + current |
| 15 | Inventories | `inventories` | Check | N/A for banks/IT services |
| 16 | Cash & cash equivalents | `cash` | Check | Exclude other bank balances; store separately if needed |

## Cash flow
| # | Metric | Key | XBRL check | Notes |
|---|---|---|---|---|
| 17 | Cash from operations | `cfo` | Check | |
| 18 | Capex | `capex` | Check | Purchase of PPE + intangibles |
| 19 | Free cash flow | `fcf` | Derived | CFO − capex |

## Governance & risk (text extraction, verified manually)
| # | Metric | Key | Notes |
|---|---|---|---|
| 20 | Auditor name | `auditor_name` | Flag changes year-over-year |
| 21 | Audit opinion type | `audit_opinion` | unmodified / qualified / adverse / disclaimer; note any emphasis of matter |
| 22 | Contingent liabilities | `contingent_liabilities` | From notes to accounts |
| 23 | Related-party transactions (total) | `rpt_total` | From RPT note |
| 24 | Promoter shares pledged (%) | `promoter_pledge_pct` | From shareholding pattern |

## Red-flag rules (v1)
- Receivables growth > revenue growth by more than 15 percentage points, two years in a row
- CFO / PAT < 0.7 for two consecutive years (profits not turning into cash)
- Auditor changed, or audit opinion not unmodified
- Promoter pledge increased by more than 5 percentage points
- Other income > 20% of PBT
- Contingent liabilities > 25% of total equity
- Related-party transactions > 10% of revenue

Thresholds are starting points. Tune them, and document every change in this file.

## Note on banks
Banks and NBFCs use different formats (interest earned, NII, NPAs). Exclude them from v1 extraction, or add a separate bank schema later.
