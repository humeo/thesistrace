.PHONY: dev check hosted-up hosted-deploy hosted-down hosted-restart hosted-smoke hosted-health-check hosted-smtp-configure hosted-config hosted-dispatch-probe hosted-recovery-probe-start hosted-operator hosted-maintenance-enter hosted-maintenance-exit hosted-rollback hosted-backup-target-init hosted-backup hosted-restore hosted-release-acceptance hosted-local-acceptance hosted-local-frontend

HOSTED_LOCAL_EVIDENCE ?= .hosted/evidence/hosted-v2-local.json

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

hosted-health-check:
	./scripts/hosted-stack health-check

hosted-smtp-configure:
	./scripts/hosted-stack smtp-configure $(CONFIG) $(PASSWORD_FILE) $(ACTOR)

hosted-config:
	./scripts/hosted-stack config

hosted-dispatch-probe:
	./scripts/hosted-stack dispatch-probe

hosted-recovery-probe-start:
	./scripts/hosted-stack recovery-probe-start $(PROBE_ID)

hosted-operator:
	./scripts/hosted-stack operator $(ARGS)

hosted-maintenance-enter:
	./scripts/hosted-stack maintenance-enter

hosted-maintenance-exit:
	./scripts/hosted-stack maintenance-exit

hosted-rollback:
	./scripts/hosted-stack rollback

hosted-backup-target-init:
	./scripts/hosted-stack backup-target-init $(TARGET)

hosted-backup:
	./scripts/hosted-stack backup

hosted-restore:
	./scripts/hosted-stack restore $(BACKUP_ID)

hosted-release-acceptance:
	.venv/bin/python scripts/hosted/release_acceptance.py \
		--release-bundle-id "$(RELEASE_BUNDLE_ID)" \
		--capacity-evidence "$(CAPACITY_EVIDENCE)" \
		--recovery-evidence "$(RECOVERY_EVIDENCE)" \
		--output "$(OUTPUT)"

hosted-local-acceptance:
	.venv/bin/python scripts/hosted/local_acceptance.py \
		--output "$(HOSTED_LOCAL_EVIDENCE)"

hosted-local-frontend:
	bun run --cwd web typecheck
	bun run --cwd web build
	bun run --cwd web test:e2e
