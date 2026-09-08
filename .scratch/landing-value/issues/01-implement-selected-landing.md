# Implement the selected landing design

Status: complete

## Decision

User selected the final restrained landing prototype on 2026-09-08. Keep the centered AI Agent positioning, compact three-step research sequence, interactive research preview, four reasons to choose ThesisTrace, and closing login CTA. Put the official Discord symbol and link in the first navigation row. Preserve English and Chinese language selection.

Primary source: branch `codex/landing-value-prototype`, commit `3ebb125`. Earlier A/B/C explorations were rejected and are not implementation requirements. The original prototype remains on that branch; main contains the selected design without a variant switcher, development gate, prototype route or prototype component.

## Implementation

Use the existing LandingPage and copy module. Replace the old oversized branding and duplicated formula strip with the selected hierarchy. Keep shared product styles unchanged.

## Validation

Targeted checks: web typecheck, existing landing browser regression at desktop and mobile widths, production Web build and local browser inspection. No backend behavior changes.

Verified: web typecheck passed; landing browser regression passed at 1220px and 390px (2 tests); production Web image built and local Web service is healthy. Inspected the built page at `http://127.0.0.1:5173/?lang=en` and the captured mobile layout. The selected implementation is delivered on main; the throwaway prototype remains on its original branch.
