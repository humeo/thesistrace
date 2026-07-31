.PHONY: dev check hosted-up hosted-deploy hosted-down hosted-restart hosted-smoke hosted-config hosted-dispatch-probe hosted-operator hosted-maintenance-enter hosted-maintenance-exit hosted-rollback

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

hosted-deploy:
	./scripts/hosted-stack deploy

hosted-down:
	./scripts/hosted-stack down

hosted-restart:
	./scripts/hosted-stack restart

hosted-smoke:
	./scripts/hosted-stack smoke

hosted-config:
	./scripts/hosted-stack config

hosted-dispatch-probe:
	./scripts/hosted-stack dispatch-probe

hosted-operator:
	./scripts/hosted-stack operator $(ARGS)

hosted-maintenance-enter:
	./scripts/hosted-stack maintenance-enter

hosted-maintenance-exit:
	./scripts/hosted-stack maintenance-exit

hosted-rollback:
	./scripts/hosted-stack rollback
