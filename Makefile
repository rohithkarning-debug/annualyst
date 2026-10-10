.PHONY: help ingest validate extract eval test lint app

ARGS = $(if $(SYMBOL),--symbol $(SYMBOL)) $(if $(FY),--fy $(FY))

help:
	@echo Targets: ingest SYMBOL=TCS FY=2025, validate, extract, eval, test, lint, app
	@echo ingest and validate run for all companies and years when SYMBOL and FY are omitted.

ingest:
	uv run python -m annualyst.ingest.download $(ARGS)
	uv run python -m annualyst.ingest.validate $(ARGS)

validate:
	uv run python -m annualyst.ingest.validate $(ARGS)

extract:
	@echo extract: not implemented yet

eval:
	uv run python eval/run_eval.py

test:
	uv run pytest

lint:
	uv run ruff check --fix .
	uv run ruff format .

app:
	@echo app: not implemented yet
