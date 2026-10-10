.PHONY: help ingest extract eval test lint app

help:
	@echo Targets: ingest SYMBOL=TCS FY=2025, extract, eval, test, lint, app

ingest:
	@echo ingest SYMBOL=$(SYMBOL) FY=$(FY): not implemented yet

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
