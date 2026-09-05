# 01 — Implement MCP connections and client authorization

**Status:** ready-for-agent

**What to build:** Deliver the accepted MCP page and its real OAuth, discovery,
and Researcher-owned revocation boundaries as one complete acceptance unit.

## Acceptance

- [x] Sidebar entry and product route, accepted copy and responsive layout.
- [x] English agent prompt plus Codex and Claude Code remote MCP commands.
- [x] Authenticated live service check and dynamically discovered tool set.
- [x] Real OAuth registration, PKCE, signed login/consent continuation and grants.
- [x] Owner-only grant listing and revocation of access/refresh tokens.
- [x] Fresh schema and least-privilege Auth role contract.
- [x] Final image/browser acceptance and review findings closed.
- [ ] Commit implementation and verification evidence.

## Comments

Implementation is isolated in `.worktrees/mcp-connections` on
`codex/mcp-connections`, based on `b54560e`. The saved main checkout and its
parallel changes are preserved. Test environments use the repository's isolated
Compose entrypoints and do not reset `thesistrace-dev`.

Final verification is recorded in [verification.md](../verification.md).
