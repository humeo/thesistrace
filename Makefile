.PHONY: dev check

dev:
	bun run --cwd web dev

check:
	.venv/bin/ruff check src tests
	.venv/bin/pytest -q
	bun run --cwd web typecheck
	bun run --cwd web build
	bun run --cwd web test:e2e
