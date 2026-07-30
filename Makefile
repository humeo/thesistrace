.PHONY: dev check hosted-up hosted-down hosted-restart hosted-smoke hosted-config hosted-operator

dev:
	bun run --cwd web dev

check:
	.venv/bin/ruff check src tests
	.venv/bin/pytest -q
	bun run --cwd web typecheck
	bun run --cwd web build
	bun run --cwd web test:e2e

hosted-up:
	./scripts/hosted-stack up

hosted-down:
	./scripts/hosted-stack down

hosted-restart:
	./scripts/hosted-stack restart

hosted-smoke:
	./scripts/hosted-stack smoke

hosted-config:
	./scripts/hosted-stack config

hosted-operator:
	./scripts/hosted-stack operator $(ARGS)
