.PHONY: dev check check-live-tushare hosted-up hosted-deploy hosted-down hosted-restart hosted-smoke hosted-smtp-configure hosted-config hosted-operator

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

hosted-up:
	./scripts/hosted-stack up

hosted-deploy:
	./scripts/hosted-stack deploy

hosted-down:
	./scripts/hosted-stack down

hosted-restart:
	./scripts/hosted-stack restart

hosted-smoke:
	./scripts/hosted-stack smoke

hosted-smtp-configure:
	./scripts/hosted-stack smtp-configure $(CONFIG) $(PASSWORD_FILE)

hosted-config:
	./scripts/hosted-stack config

hosted-operator:
	./scripts/hosted-stack operator $(ARGS)
