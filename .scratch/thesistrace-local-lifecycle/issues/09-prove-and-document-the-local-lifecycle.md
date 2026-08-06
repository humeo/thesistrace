# 09 — Prove and document the local lifecycle

**What to build:** Make the accepted Development/Test lifecycle understandable
and prove it from a clean local state, so that repository instructions and
runtime evidence describe the same two environments without implying
Production readiness.

**Blocked by:** 04 — Reset Development safely to an empty Core; 05 — Provide
the Compose Watch development loop; 08 — Compose the complete local merge gate.

**Status:** complete

- [x] A lifecycle guide documents prerequisites, bootstrap, foreground and
      background Development, safe stop, safe reset, logs, fast tests,
      Integration Tests, browser tests, the complete gate, failure artifacts,
      and the keep-environment escape hatch.
- [x] Active onboarding, architecture, and credential-verification instructions
      use mise, Node.js 24, pnpm, uv, and the accepted pnpm command contract.
- [x] A concise ADR records why Development and Test use one full Compose
      topology instead of the former hybrid host-application runtime.
- [x] The product domain glossary remains free of generic engineering lifecycle
      and deployment implementation terms.
- [x] Active documentation states explicitly that only local Development and
      local Test exist and that local evidence is not Production readiness.
- [x] Active lifecycle documentation and commands contain no Makefile,
      Staging, Production overlay, registry, deployment, backup, rollback, or
      release-image workflow.
- [x] From a clean local state, bootstrap and background startup reach health,
      a real product resource survives stop/start, and reset returns to the
      migrated empty Core without Seed.
- [x] Clean-state verification proves Test/Development isolation, failure
      evidence before cleanup, the optional keep behavior, and no leftover Test
      environment after the complete gate.
- [x] The existing real PostgreSQL/RustFS integration evidence and complete
      four-resource browser journey pass through `pnpm check`.
- [x] Final review confirms that unrelated working-tree and research material
      was preserved and that only lifecycle-scope changes are included.

## Comments

- `d6a6d99` added the lifecycle guide, updated onboarding, architecture, and
  Tushare credential instructions, recorded ADR-0152, and added documentation
  contracts without changing `CONTEXT.md`. `0b0c855` resolved review findings
  by correcting pnpm option forwarding, removing stale CI wording, documenting
  the local change workflow, and exposing metadata-bound cleanup as
  `pnpm test:cleanup`.
- The documented `mise exec -- pnpm bootstrap` completed frozen uv/pnpm sync,
  Compose validation, pinned infrastructure pulls, and all Development image
  builds successfully.
- A canonical `dev:reset` produced an idle Data state and empty Dataset Release,
  Definition, ResearchRun, and DailyTrack lists. Definition
  `def_ab08fbe6dbd94fac8c5f` was then created through the public HTTP product
  seam, survived `dev:stop` and `dev:up` with the same ID and revision, and was
  removed by the final reset. Its detail returned 404 and all four lists were
  empty again, proving no Seed.
- A real `pnpm test:integration --keep-environment` run was interrupted after
  test execution began. Run `20260806t200850z-65539-30d50099` recorded status
  130, `cleanup_status=kept`, Compose ps/logs/inspect evidence, and retained its
  exact containers, network, and two volumes. The documented metadata-bound
  `pnpm test:cleanup` then removed all of them successfully.
- Final label queries found no `thesistrace-test-*` container, network, or
  volume. Development remained an empty migrated Core with Web, API, Worker,
  PostgreSQL, and RustFS healthy and Migration exited successfully.
- The complete `CI=true mise exec -- pnpm check` at `566b099` passed `176` fast
  Python tests, Integration `102/102`, and browser acceptance `18/18`, with both
  disposable run metadata files recording `cleanup_status=0` and `status=0`.
  Later Ticket 09 changes touched only documentation, documentation assertions,
  and the separately proven cleanup proxy, so they did not invalidate the real
  Integration or E2E evidence. The current fast gate passed `178` Python tests,
  TypeScript, and the Web shell.
- Standards and Spec reviews used fixed point `c8cc49d`. Both initial findings
  were fixed in `0b0c855`; final re-review reported no findings. The unrelated
  Hosted V2 research directory and InsForge research note remain untracked and
  untouched.
