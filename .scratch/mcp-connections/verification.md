# MCP implementation verification

Implementation branch: `codex/mcp-connections`, isolated from saved main at
`b54560e`. No Development data or containers were reset.

## Completed checks

- Python MCP OAuth / HTTP contracts: 53 passed; affected Ruff checks passed.
- Agent typecheck and complete unit suite: 531 passed.
- Auth typecheck and complete unit suite: 191 passed.
- Final complete Auth database integration suite: 136 passed across 17 files
  (isolated run `20260905t082256z-49495-228c7949`).
- Web production build and bundle budget passed; complete Shell suite: 305 passed.
- Database-backed OAuth checks: PKCE, signed consent, owner isolation, refresh
  rotation, revoke, pending authorization code rejection, account reactivation,
  secret rotation, tampered requests and inactive Researchers.

## Issues found during acceptance

- Local HTTP MCP URLs passed settings parsing but failed transport construction
  and Agent readiness. Both checks now permit loopback HTTP only in Development
  and Test; Production continues to require HTTPS. Regression checks cover both.
- OAuth provider initialization must finish before the Auth process serves or an
  Operator command closes its pool. Server and Operator await the Auth context.
- Account credential lifecycle now removes external OAuth credentials on
  deactivation, password reset and hard Auth secret rotation.
- The first complete Auth integration attempt during image building had a
  10-second database TRUNCATE setup timeout (134 passed, 1 failed). Evidence is
  preserved under the runner's `thesistrace-auth-test.yuCt5t` temporary directory.
  The affected file subsequently passed all 17 cases; the final complete suite
  passed all 136 cases, as recorded above. No timeout was raised or test removed.

## Final image and browser acceptance

Final Caddy/Auth/Agent/Core images were built and started by the repository E2E
runner in `thesistrace-test-20260905t081903z-47908-1c915ce1`.
The browser test passed (29.4 seconds) against those images with an independent
Playwright project identity after fixing the test's hard-coded protocol header
to use the initialization response's negotiated version. No product source
changed after those images were built.

The test covers live Connection availability and 16 tools, English setup prompt,
390-pixel mobile layout without horizontal overflow, signed login continuation,
explicit consent, read-only tool discovery, owned grant display, confirmation and
revocation, and rejection of the old external bearer token with HTTP 401.
Desktop, mobile and consent screenshots were visually inspected. Screenshots
finish CSS transitions before capture.

Evidence: `.local/test-runs/20260905t081903z-47908-1c915ce1/browser-acceptance/`.
The original failed test traces remain separately under the runner's evidence
folder, sanitized by the repository runner. An intermediate reuse attempt failed
because fixture provisioning requires a fresh test identity; the final test used
its own identity. The temporary Playwright project config was removed afterward.

The final Caddy Auth health and protected-resource metadata were also read live.
The metadata assertion in the runner now uses the allocated resource URL.

These checks use a protocol test client. Real Codex/Claude interactive CLI setup
and a production deployment were not performed. No real model or paid research
operation was used. Saved main and the prototype remain unchanged.
