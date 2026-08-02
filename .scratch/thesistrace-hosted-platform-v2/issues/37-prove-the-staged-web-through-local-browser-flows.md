# 37 — Prove the Staged Web through Local Browser Flows

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Verify the exact Web artifact staged in the reusable Core
Session through a real local browser. Keep build identity and visible product
behavior tied to the same Release Bundle instead of silently rebuilding or
swapping the active frontend near the end of acceptance.

**Blocked by:** 29 — Prove Local Identity, Isolation, and Retained Product Health.

**Status:** ready-for-agent

- [ ] Frontend install, typecheck, tests, and an isolated reproducibility build use the exact locked source and dependency inputs recorded by the Core Session; a mismatch invalidates the session rather than mutating its active release.
- [ ] The served Web asset manifest and build identity match the Web artifact already staged by ticket 28. Verification never rebuilds in place, hot-reloads, or swaps the active edge/Web artifact.
- [ ] With heavy workflow and observability work stopped, the Codex in-app browser reaches the real local Public Origin and authenticates as the retained acceptance Users with freshly acquired sessions.
- [ ] Visible flows cover invitation/verification/login and recovery, Personal Workspace provisioning, shared Dataset read, private ResearchRun creation and result inspection, quota and rerun behavior, DailyTrack activation/advance/stop, and a separate Tombstone deletion witness.
- [ ] Cross-Workspace routes, direct or nested Storage paths, stale object URLs, and unauthorized navigation disclose no private identifiers, payloads, signed links, or cached data in the UI, response body, browser storage, or history-visible route state.
- [ ] Browser evidence captures the exact build identity, route, assertions, screenshots, console errors, failed requests, response statuses, and timing needed to diagnose each flow; unexpected console or network failures fail the gate.
- [ ] The browser gate is independently rerunnable against the same compatible session, injects no service fault, and makes no claim about real SMTP delivery, Cloudflare, external DNS/TLS, production invitation opening, or production launch.
