.PHONY: dev dev-reset dev-down check check-live-tushare

dev:
	./scripts/core-test-runtime up
	./scripts/core-test-runtime run bun run --cwd web dev

dev-reset:
	./scripts/core-test-runtime reset

dev-down:
	./scripts/core-test-runtime down

check:
	uv run ruff check src tests
	uv run pytest -q tests/kernel tests/architecture tests/adapters
	bun run --cwd web typecheck
	bun run --cwd web build
	./scripts/core-test-runtime reset
	./scripts/core-test-runtime run uv run pytest -q tests/integration tests/acceptance
	./scripts/core-test-runtime reset
	./scripts/core-test-runtime run bun run --cwd web test:e2e
	./scripts/core-test-runtime down

check-live-tushare:
	uv run python scripts/check_live_tushare.py
