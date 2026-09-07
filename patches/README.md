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

# Mastra child logging and controlled Session context

The pinned `@mastra/memory@1.28.1` Observer and Reflector agents inherit the
parent Mastra logger so a Host using `noopLogger` does not leak child-model errors.
The retained native hydration correction only adds missing message identities;
it never overwrites a live answered Tool with an older pending storage copy.
The production Session path disables native observational scheduling entirely:
`createResearchMemory` loads raw history with `lastMessages: false`, semantic
recall and working memory disabled. The Host controller owns fixed M/S snapshots.

PostgreSQL runtime tests cover same-Turn question recovery, mid-Tool-loop
compression, raw-history retention, restart, Session isolation/deletion, usage and
safe failures. Candidate tests exercise the patched entry points below. See
[Session context](../docs/runbook/session-context.md) for current scheduling and
[Issue 06 evidence](../.scratch/session-context-compaction/evidence-06.md) for final
acceptance status.

## Controlled compaction candidates

The same pinned Memory patch exposes `observer.callCandidate` and
`reflector.callCandidate`. Native `call` formats tool results with a 10k-token
cutoff and includes extractor/retry orchestration; Reflector can escalate through
several generation attempts. Those behaviors cannot publish part of a Session's
atomic M/S checkpoint.

`observer.getCandidateInput` prepares the exact instructions and full-source user
messages without invoking a model or mutating the source. Candidate execution uses
the same builder; token-based model resolution counts a clone because the native
counter annotates message parts. The Host uses this input to plan bounded batches.

Candidate calls reuse the installed Observer/Reflector prompts, parsers and Agent
execution, but receive full source JSON (including completed tool arguments and
results), run one request with no tools/extractors or automatic retries, and return
finish reason plus usage. They do not set lastExchange, write markers, invoke
extractor hooks or mutate memory. The Host's checkpoint controller owns candidate
validation, correction limits, budgets and the final atomic commit. Cancellation
is checked before and after generation. The ESM and CommonJS distributions and
public runner declarations are patched together.

`agent/src/compaction-candidates.test.ts` verifies these boundaries with an offline
model, including long results, empty observations, length stops and cancellation.
`session-context-generation.ts` calls these entries to generate unpublished M
candidates; `session-context-controller.ts` coordinates M/S validation and atomic
publication. Native automatic OM scheduling and buffering remain disabled.

## V3 prompt conversion declaration

The pinned Core 1.63.1 runtime already converts tool result media with
`aiV5PromptToAIV6Prompt`, used by `MessageList.get.all.aiV6.llmPrompt`. Both public
return declarations incorrectly name `LanguageModelV2Prompt`. The Core patch
corrects only these declarations to `LanguageModelV3Prompt`; it changes no runtime
behavior. The controller regression verifies actual image-data/file-data tool
results as well as a statically assignable V3 prompt. No local converter or unsafe
assertion replaces the framework conversion.
