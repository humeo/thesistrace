# 05 — Web authentication and account flow

**Status:** ready-for-agent

**Blocked by:** 04

## Goal

Expose the complete invite-only Researcher flow in the existing Vite product,
centralize Session and Core request behavior, and isolate browser-local Drafts
without adding a new routing or design system.

## Scope

- Add the Better Auth React client with same-origin credentials and explicit
  Session refetch behavior.
- Extend the existing lightweight router to pathname, search, and hash.
- Add `/login`, `/accept-invitation`, `/forgot-password`, and
  `/reset-password`; do not add `/signup`.
- Extract Invitation/reset fragment tokens once and remove them from browser
  history before rendering, logging, or network navigation.
- Invitation UI shows the bound email read-only and asks only for password and
  confirmation.
- Add one `AuthProvider` and `SessionGate` for initial load, anonymous,
  authenticated, setup-required, setup-failure, and Auth-unavailable states.
- Trigger `POST /api/researcher/bootstrap` after invitation auto-login and when
  an authenticated Session lacks a Core Researcher. Block product entry until
  success.
- Refetch the public Better Auth Session on initial load, focus, online recovery,
  and every 12 hours while visible and online.
- Replace direct Core page fetches with shared `coreFetch`. Stop polling and
  redirect on `401`; preserve Session and show retry on `503` or network error;
  retain product `403` and `404` behavior.
- Preserve a protected direct route only through validated same-origin relative
  `returnTo`.
- Add the context-bar account menu with email, display label, change password,
  and current-Session logout. Add no Settings/profile page.
- Hard-cut Draft storage to
  `thesistrace.research-draft.<researcherId>.<folderId>` and never read legacy
  keys. Logout preserves Drafts; switching Researcher hides them.
- Follow `DESIGN.md` and existing workbench components for accessible forms,
  labels, focus, autocomplete, errors, and loading states.

## Acceptance criteria

- [ ] Anonymous navigation reaches only the four Auth pages and protected paths
      redirect through safe `returnTo`.
- [ ] Invitation acceptance auto-logs in, bootstraps Core, and enters `/data`.
- [ ] Bootstrap failure cannot enter product routes and retries successfully on
      the next attempt or login.
- [ ] `401` ends polling and clears in-memory Session; `503` never presents as a
      logout.
- [ ] Seven-day rolling Cookie is refreshed only by direct Hono responses on the
      agreed browser events and 12-hour interval.
- [ ] Logout and account switching preserve each Researcher's Draft while
      preventing cross-account reads.
- [ ] No Session token, Invitation token, reset token, password, or full link is
      stored in localStorage, application logs, or rendered after extraction.

## Verification

- React unit tests for router state, safe returnTo, Session state machine,
  `coreFetch`, polling termination, account menu, and Draft keys.
- Playwright flows against Caddy and local Resend fake for invitation, login,
  logout, reset, bootstrap retry, focus/online refresh, and two-account Draft
  isolation.
- Keyboard, focus, label, autocomplete, and reduced-viewport checks.
- `mise exec -- pnpm test` and `mise exec -- pnpm test:e2e`.

## Delivery

Keep the current custom router and visual system. Do not introduce React Router,
a Settings area, public signup, profile management, marketing layout, or token
storage.

## Comments
