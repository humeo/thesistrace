# AG-UI/Mastra content-free logging

The pinned `@ag-ui/mastra@1.1.1` bridge calls `console.warn` directly in eight
places, including Memory, Tool setup and trace errors. Its public configuration
does not provide a logger switch; Mastra's `noopLogger` does not control these
calls. Raw exceptions may include private prompts, SQL, paths and credentials.

The pnpm patch replaces only these warning calls with `void` expressions in the
published ESM and CommonJS distributions. It changes no execution, persistence,
protocol, exception handling or dependency version. It does not intercept global
console output. The lockfile pins the patch hash, and all image builds copy it
before frozen installation.

`agent/src/bridge-log-privacy.test.ts` drives the installed public bridge through
five previously leaking paths. Agent operational diagnostics instead use the
closed `agent/src/run-telemetry.ts` metadata writer. Keep these regressions when
deliberately changing the dependency; never remove the privacy boundary merely
because a new package version installs successfully.

# Mastra optional enum/literal tool parameters

The pinned `@mastra/schema-compat@1.3.7` OpenAI tool-schema conversion makes
optional fields required and adds a null branch. For scalar enums/literals it
also leaves the original `enum`/`const` outside that branch, which excludes null
again. In `ask_user`, a free-text question therefore cannot send null for the
optional `selectionMode`, although the native tool expects it to be absent.

The pnpm patch removes only the duplicate outer value constraints in the ESM
and CommonJS distributions; the original enum/literal stays in the non-null
branch. Required fields, allowed non-null values, and the native tool's rule
that a selection mode requires options remain strict. There is no argument
guessing, alternate tool, framework upgrade, or change to suspension/resumption.

`agent/src/ask-user-schema.test.ts` captures actual Responses request schemas,
validates fixture arguments with an independent JSON Schema validator, and runs
them through native Mastra tools. It covers nulls, invalid values, both module
formats, and recovery after a selection without options. The native OpenAI
cases in `agent/src/research-runtime.integration.test.ts` additionally verify
free-text/single/multi-select questions, persistent suspension across a Host
restart, same-Turn answers, original model settings, accumulated usage, and
answer idempotency with isolated PostgreSQL and a fake Responses provider.

Retain these contract tests when deliberately upgrading Mastra; remove this
patch only once the installed replacement passes the same tests unpatched.
