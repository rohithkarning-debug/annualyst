# Annualyst

An analyst copilot for annual reports of NSE/BSE-listed Indian companies.

## The problem
Indian annual reports are 300+ page PDFs that mix ₹ crore, lakh and million, and report standalone and consolidated numbers side by side. Pulling reliable numbers out of them by hand is slow, and generic LLM chatbots make up figures without citing sources. Annualyst extracts metrics that cite their source page and are checked against the exchanges' official XBRL filings. Its accuracy is measured, not assumed.

## Planned features
- **Fact table:** key financial metrics extracted into DuckDB. Every value records its source page, its unit, and whether it is standalone or consolidated.
- **XBRL verification:** extracted numbers are cross-checked against the official results filed with NSE/BSE.
- **Cited Q&A:** answers to analyst questions with page-level citations. The system says "Not found in the report" instead of guessing.
- **Analysis:** year-over-year trends, peer comparison, and red flags such as receivables outpacing revenue, weak cash conversion, or auditor changes.
- **IndiaFinBench:** a public benchmark of Q&A pairs on Indian annual reports.

See [METRICS.md](METRICS.md) for the metric schema.

## Quickstart
```bash
uv sync
make test
make lint
```

**Status: Week 1 — in progress**
