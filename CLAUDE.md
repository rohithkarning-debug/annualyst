# Annualyst — Analyst copilot for Indian annual reports

## What this project is
Annualyst reads annual reports of companies listed on NSE/BSE and:
1. Extracts key financial metrics into a structured fact table (every value keeps its source page).
2. Verifies extracted numbers against the official XBRL financial results filed with the exchanges.
3. Answers analyst questions with page-level citations, and says "not found in the report" when the answer isn't there.
4. Tracks metrics year-over-year, compares peers, and flags accounting red flags.
5. Ships a public benchmark (IndiaFinBench) of Q&A pairs on Indian annual reports.

The goal is a portfolio project that proves accuracy with numbers, not just a demo.
Everything must be measurable through the eval harness.

## Tech stack
- Python 3.11, dependency management with `uv`
- PDF parsing: Docling (primary), PyMuPDF (fallback / page text)
- Storage: DuckDB for the fact table, local files for raw data
- Retrieval: BM25 (`rank_bm25`) + embeddings (sentence-transformers) + cross-encoder reranker
- LLM: Claude via the Anthropic Python SDK (API key from env var `ANTHROPIC_API_KEY`, never hard-coded)
- Backend: FastAPI. Frontend: Streamlit for v1
- Quality: pytest, ruff, type hints everywhere

## Folder structure
```
annualyst/
├── CLAUDE.md
├── METRICS.md              # the metric schema — source of truth for extraction
├── README.md
├── pyproject.toml
├── Makefile                # make ingest / make extract / make eval / make app
├── data/
│   ├── raw/{SYMBOL}/{FY}/  # annual_report.pdf, results.xml (XBRL)  — gitignored
│   ├── parsed/             # parsed text + tables as JSON, with page numbers — gitignored
│   └── facts.duckdb        # extracted fact table — gitignored
├── benchmark/
│   ├── questions.jsonl     # IndiaFinBench Q&A pairs (committed)
│   └── README.md           # how questions were written, categories, license
├── src/annualyst/
│   ├── ingest/             # downloaders + PDF/XBRL parsing
│   ├── extract/            # metric extraction from parsed reports
│   ├── verify/             # compare extracted facts vs XBRL
│   ├── retrieve/           # chunking, BM25, embeddings, reranker
│   ├── qa/                 # question answering with citations
│   ├── analyze/            # YoY, peer comparison, red flags
│   ├── api/                # FastAPI app
│   └── ui/                 # Streamlit app
├── eval/
│   ├── run_eval.py         # single entry point, prints a scorecard
│   └── results/            # dated JSON results of each eval run (committed)
└── tests/
```

## Commands
- `make ingest SYMBOL=TCS FY=2025` — download and parse one report
- `make extract` — run metric extraction on all parsed reports
- `make eval` — run the full eval harness and print the scorecard
- `make test` — pytest
- `make lint` — ruff check + format
- `make app` — run the Streamlit UI locally

## Rules (always follow)
1. **Every number keeps its provenance.** Any extracted value must store: company symbol, fiscal year, metric name, value, unit, standalone/consolidated, source page number. No provenance = don't store it.
2. **Units and scale matter.** Indian reports mix ₹ crore, ₹ lakh and ₹ million. Normalise everything to ₹ crore and store the original unit too.
3. **Standalone vs consolidated** must always be recorded explicitly. Default to consolidated when both exist.
4. **Answers must cite pages.** If the QA system can't find supporting evidence, it must answer "Not found in the report" rather than guess.
5. **Never edit `benchmark/questions.jsonl` or files in `eval/` without asking me first.** The benchmark is the ground truth; changing it to make scores go up is cheating.
6. **Run `make eval` after any change** to extraction, retrieval or QA, and report the before/after scores.
7. **Tests with every module.** New functions get pytest tests, using small fixture files in `tests/fixtures/`.
8. **No secrets in code or git.** API keys come from `.env` (gitignored).
9. **Respect source websites.** Rate-limit downloads (≥2 seconds between requests), set a proper User-Agent, and cache everything locally so we never re-download. If NSE/BSE blocks scripted downloads, stop and tell me — I'll download files manually.
10. **Keep LLM costs visible.** Log tokens used per eval run in the results file.

## How to work with me
- I'm a 3rd-year AIML student. When you make a design choice (chunk size, model, prompt format), explain it in 2–3 sentences so I can defend it in interviews.
- For anything bigger than a small fix, propose a plan first and wait for my OK.
- Keep commits small, one feature per commit, with clear messages.
- If something is ambiguous in the data (e.g. a metric reported differently by a company), flag it rather than silently picking an interpretation.

## Current milestone
Week 1: set up the repo, download 5 companies × 3 fiscal years (TCS, Infosys, Hindustan Unilever, Asian Paints, Reliance — FY2023–FY2025; no banks in v1) and their XBRL results, and get clean page-level text out of each PDF.
