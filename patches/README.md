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
