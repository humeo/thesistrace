# Composer-based question answering

Status: complete

## Decision

The user selected **A — composer question** on 2026-09-04. Put the pending
question, choices, and optional free text together at the bottom of Chat.
The timeline shows a compact question activity and the accepted answer as a
normal user message. Keep the current one-question-per-interrupt contract;
the prototype's three-question demonstration is not a new backend capability.

Primary source: `codex/ask-user-prototype`, commit
`68d65fe5f18a467bb7f89af45b07b598d902053c`,
`web/src/chat/AskUserPrototype.tsx` (variant A).

## Contract

- Answer payload is strictly `{ selections: string[], text: string }`.
- Validate selections against the saved question; allow custom text alone or
  alongside choices. Reject empty, duplicate, unknown, excessive, and oversized
  input. Old scalar/array payloads are rejected, not migrated.
- Normalize to the same readable text for Mastra's native resume answer and
  the browser-safe user timeline entry. Resume the same Turn and settings.
- Preserve answer text/selections until the command receipt confirms acceptance.
  Keep any unfinished next-prompt draft separate from the answer.
- Stop remains available even with a filled answer. No new backend capabilities,
  schema changes, prototype routes, simulated data, or dependencies.

## Delivery

Use the existing DESIGN.md surfaces and prototype A density. Compact pointer
actions are 36px; touch actions are 44px. Long questions/options scroll inside
the question surface while the answer row remains reachable. Verify the
contract, recovery, rendering, and real-browser same-Turn flow with fake models.

Implemented as `9897ebf`, rebased unchanged to `27a36b8` and fast-forwarded into
local main with delivery commit `8febbef`. Verification, preservation of existing
uncommitted changes, and post-merge main checks are recorded in
`issues/01-production-answer-surface.md`. Web and Agent require an atomic
release; no remote push or explicit development-service restart was performed.
