.PHONY: dev check check-live-tushare

dev:
	bun run --cwd web dev

check:
	.venv/bin/ruff check src tests
	.venv/bin/pytest -q
	bun run --cwd web typecheck
	bun run --cwd web build
	bun run --cwd web test:e2e

check-live-tushare:
	uv run python scripts/check_live_tushare.py
