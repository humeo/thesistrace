# 09 — Prove and document the local lifecycle

**What to build:** Make the accepted Development/Test lifecycle understandable
and prove it from a clean local state, so that repository instructions and
runtime evidence describe the same two environments without implying
Production readiness.

**Blocked by:** 04 — Reset Development safely to an empty Core; 05 — Provide
the Compose Watch development loop; 08 — Compose the complete local merge gate.

**Status:** ready-for-agent

- [ ] A lifecycle guide documents prerequisites, bootstrap, foreground and
      background Development, safe stop, safe reset, logs, fast tests,
      Integration Tests, browser tests, the complete gate, failure artifacts,
      and the keep-environment escape hatch.
- [ ] Active onboarding, architecture, and credential-verification instructions
      use mise, Node.js 24, pnpm, uv, and the accepted pnpm command contract.
- [ ] A concise ADR records why Development and Test use one full Compose
      topology instead of the former hybrid host-application runtime.
- [ ] The product domain glossary remains free of generic engineering lifecycle
      and deployment implementation terms.
- [ ] Active documentation states explicitly that only local Development and
      local Test exist and that local evidence is not Production readiness.
- [ ] Active lifecycle documentation and commands contain no Makefile,
      Staging, Production overlay, registry, deployment, backup, rollback, or
      release-image workflow.
- [ ] From a clean local state, bootstrap and background startup reach health,
      a real product resource survives stop/start, and reset returns to the
      migrated empty Core without Seed.
- [ ] Clean-state verification proves Test/Development isolation, failure
      evidence before cleanup, the optional keep behavior, and no leftover Test
      environment after the complete gate.
- [ ] The existing real PostgreSQL/RustFS integration evidence and complete
      four-resource browser journey pass through `pnpm check`.
- [ ] Final review confirms that unrelated working-tree and research material
      was preserved and that only lifecycle-scope changes are included.
