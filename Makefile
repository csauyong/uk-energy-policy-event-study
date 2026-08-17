.DEFAULT_GOAL := help
SHELL := /bin/bash
PY := 3.11

.PHONY: help setup lint fmt test check clean data-check events-check universe-check event-report sweep chronology shortlist audit finalise promote

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the venv and install the package + dev tools (editable)
	uv venv --python $(PY)
	uv pip install -e ".[dev]"
	@echo
	@echo "Activate with: source .venv/bin/activate"
	@echo "Then run 'make lint' and 'make test'."

lint:  ## ruff check + ruff format --check + mypy
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy

fmt:  ## Auto-fix lint and format
	uv run ruff check --fix src tests
	uv run ruff format src tests

test:  ## Run the test suite with coverage
	uv run pytest --cov --cov-report=term-missing

check: lint test data-check events-check  ## Everything CI would run

data-check:  ## Fail if any data file has been committed (CLAUDE.md hard rule)
	@# data/events/ is the one sanctioned exception -- the hand-curated event
	@# dictionary is source, not data. See the note at the top of .gitignore.
	@tracked=$$(git ls-files data/ \
		| grep -v '\.gitkeep$$' \
		| grep -v '^data/events/' \
		| grep -v '^data/exposure/' \
		| grep -v '^data/universe/uk_listed_universe\.csv$$' || true); \
	if [ -n "$$tracked" ]; then \
		echo "ERROR: data files are tracked in git:"; echo "$$tracked"; exit 1; \
	else \
		echo "OK: no data files tracked beyond the event dictionary."; \
	fi

events-check:  ## Validate the hand-curated event dictionary
	@uv run python scripts/check_events.py

universe-check:  ## Parse config/universe.yaml and print the clock-alignment table
	@uv run python scripts/check_universe.py

event-report:  ## Per-event curation view: timing, status resolution, power curve
	@uv run python scripts/event_report.py

sweep:  ## Sweep gov.uk for candidate announcements (timestamping aid)
	@uv run python scripts/sweep_govuk.py

chronology:  ## Deductive discovery: walk the policy taxonomy against published chronologies
	@uv run python scripts/build_chronology.py

shortlist:  ## Filter chronology candidates by rule, before leak checking (Step 2)
	@uv run python scripts/build_shortlist.py

audit:  ## Completeness audit and deferral hunt over the cached briefing corpus
	@uv run python scripts/audit_completeness.py

finalise:  ## Apply hand curation, re-check balance, verify dates
	@uv run python scripts/finalise_shortlist.py

promote:  ## Promote the a-priori inventory into the event dictionary (freeze step)
	@uv run python scripts/promote_events.py

prices:  ## Pull and cache daily history for every named unit (acquisition only; Rule 0 firewall)
	@uv run python scripts/pull_prices.py

clean:  ## Remove caches and build artefacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
