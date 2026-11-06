# Orchestrate authenticated reads with Mastra Code Mode

The built-in Research Agent uses Mastra's native `createCodeMode` and the
official `@mastra/isolated-vm` transport to combine authenticated Core reads in
one `execute_typescript` invocation. Thirteen explicit read and diagnostic
capabilities are available as generated `external_*` functions. The five
Research/Batch/DailyTrack commands remain direct model Tools, alongside
`ask_user` and `render_a2ui`. Unknown discovered capabilities and destructive
commands are not automatically exposed. Core MCP remains the authority for
identity, scope, schemas and Research truth; Code Mode grants no new authority.

Each program receives a fresh V8 isolate without Node, filesystem, network or
module capabilities. The Host admits eight programs, with one per Agent Run.
A program is bounded by 30 seconds and the remaining Run deadline, a 64-MiB
isolate heap limit, 64-KiB source and arguments, 32 calls, four concurrent reads,
8-MiB cumulative read output, and a 256-KiB final envelope. The existing
512-KiB individual MCP output limit remains authoritative. Stop interrupts
synchronous execution and cancels queued/active reads. Fatal MCP failures and
execution limits terminate the Run even when the program catches its errors;
recoverable business rejections may be handled while preserving other reads.
The heap setting is an isolate limit rather than an OS process reservation;
the Agent container's existing resource limit remains the process boundary.

Every internal call has an independent identity and retains the outer Run's
authenticated request context and cancellation. Only actual outer model calls
enter native model history. Internal calls produce content-free lifecycle
activities through the existing durable timeline. They do not create synthetic
provider calls or expose source, arguments, results, credentials or private
errors to browser events or operational telemetry. Existing validated public
ResearchRun references may survive the safe result projection.

The pinned transport patch disables Host console capture and enforces UTF-8
argument/result budgets before copying data across the isolate boundary. It
also classifies isolate heap exhaustion as a fatal execution limit. Both ESM
and CommonJS builds are patched. Agent Node entrypoints use
`--no-node-snapshot`; startup does not substitute another execution backend.

Deterministic Providers execute the same Code Mode contract. The private
Memory evaluation oracle recognizes only provable, unchanged literal reads
and exact parallel read-through programs. Arbitrary computed results do not
prove which business data was inspected and therefore do not earn those
oracle facts. This conservative evaluation view never rewrites model history.
Engineering checks use the verification guidance in [AGENTS.md](../../AGENTS.md);
they do not establish real-model quality or production deployment qualification.
