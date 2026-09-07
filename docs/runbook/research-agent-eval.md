# Research Agent real-model evaluation

This is an explicit, paid Operator workflow, separate from deterministic
engineering tests. No candidate is release-qualified yet: the checked-in
thresholds and execution envelope are calibrated by the reviewed baseline, but
independent qualification remains required before any model/effort is described
as qualification-passed. The user explicitly waived running qualification as
an Issue 12 completion condition; that waiver permits Issue 12 and Issue 13 to
proceed, but it is not release-quality evidence and does not qualify a model.

## Authorization and isolation

Obtain approval for the destination Provider, the fixed prompts, discovered
MCP schemas and isolated research results sent there, and the spending ceiling
before running. The current candidate is the user-selected `gpt-5.6-luna` with
`high` reasoning through the local OpenAI-compatible service on port 8317.
Set `THESISTRACE_AGENT_OPENAI_API_KEY` in the private `.env`. Run the explicit
paid evaluation through `pnpm config:run` so it uses the same configuration.
Never put the key in shell arguments or a checked-in file.

Set `THESISTRACE_AGENT_OPENAI_BASE_URL` explicitly. Containers reach the local
service through `http://host.docker.internal:8317/v1`, not their own localhost.
The CLI refuses a missing, credential-bearing or noncanonical endpoint and
plain HTTP outside loopback/host access. It does not fall back to a generic
`OPENAI_BASE_URL` or the SDK's public endpoint. Before the first model request,
the evaluator verifies the deployed Agent's endpoint hash against its explicit
configuration. Only the hash, not the endpoint, enters evaluation reports.

OpenAI requests use the SDK's native `store: false` mode. Mastra is the owner
of conversation history, so later steps replay native encrypted reasoning and
Tool history instead of depending on provider-side item retention. A proxy
that does not retain responses cannot resolve stored `item_reference` values.
This is one explicit stateless contract, not a proxy-specific retry or fallback.
See the [official conversation-state guidance](https://developers.openai.com/api/docs/guides/conversation-state).

The command creates a new canonical `thesistrace-test-*` Compose project with
its own database, accounts, network, data and volumes. It builds the final
images and reuses the same Caddy, Auth, token exchange, MCP, Workers and RustFS
pipeline as browser acceptance. It never attaches to Development or Production.
`--keep-environment` is rejected for this credential-bearing workflow.
Default Unit, Integration, E2E and image tests explicitly clear paid Provider
credentials and use the Scripted Provider. Offline preflight tests run during
`pnpm test`; they never invoke a model.

After approval, an example baseline command is:

```sh
THESISTRACE_AGENT_OPENAI_BASE_URL=http://host.docker.internal:8317/v1 \
THESISTRACE_AGENT_EVAL_MODEL_KEY=gpt-5.6-luna \
THESISTRACE_AGENT_EVAL_REASONING_EFFORT=high \
THESISTRACE_AGENT_EVAL_PHASE=baseline \
THESISTRACE_AGENT_EVAL_SPEND_LIMIT_USD="${THESISTRACE_AGENT_EVAL_SPEND_LIMIT_USD:?set the approved ceiling first}" \
  mise exec -- ./scripts/test-runtime agent-eval
```

The credential must already be in the Operator environment. This example is
not evidence that a paid evaluation has run or authorization to run one.

## Fixed inputs and automatic outcomes

`agent/evals/research-candidates.json` declares the candidate snapshot,
supported efforts, input ceiling, published-price upper bounds and thresholds.
`agent/evals/research-corpus.json` contains eleven cases. Baseline runs each
case once: 11 case attempts and 12 primary Agent Turns. Qualification repeats
each case three times: 33 attempts and 36 primary Turns. Clarification has
exactly two turns. The small fixed replay dataset and July 20–August 4, 2026 research
window with an August 5 head test workflow correctness, not investment efficacy.
The `explicit-return` corpus snapshot makes both momentum requests unambiguously
ask for the two-session cumulative percentage change in closing price. Absolute
price differences and average daily changes are different signals; the behavioral
oracle rejects them. Its four fixed panels include a volatile round trip that
distinguishes compounding from the arithmetic mean of daily returns. Earlier
ambiguous snapshots and interrupted baselines remain separate evidence, never
interchangeable qualification inputs.

The `render_a2ui` Tool advertises the exact flat component schemas from the shared
registered catalog. Mastra's native JSON Schema adapter validates those same
fields before execution; the existing projector still checks graph ownership,
links and resource bounds. No separate model-only catalog or renderer is used.

An A2UI-only answer can finish with an empty final model step. The Provider guard
requires output in the current Run, not redundant prose in every step. Evaluation
applies the same explanation semantics to ordinary text and the final validated
A2UI display values, including locally expandable tables and provenance. It does
not count component IDs, URLs, layout metadata, invalid/loading surfaces or prior
Chat history as an answer. Display text remains in memory and is never included
in reports; the existence of a card alone cannot qualify a result explanation.

Outcomes inspect independently owned Core artifacts, ownership, required and
forbidden capabilities, final status and bounded explanation semantics. The
Formula oracle uses the actual Alpha compiler/execution kernel over fixed
non-monotone panels and compares cross-sectional ordering; it does not require
an exact generated Formula or exact reply. Long polling holds the real Worker;
DailyTrack Retry starts from a real blocked Worker outcome. DailyTrack Refresh
starts from a real active, lagging, idle Track and must use the discovered
explicit Refresh command exactly once before inspecting the advanced state.

Formula correction requires the original invalid diagnostic, a valid diagnostic
of the submitted Formula, and the matching accepted Run. Admission correction
is a distinct case: `ts_mean(close, 2)` begins at the fixed replay's first session
(2010-01-04), receives a real `INSUFFICIENT_CALCULATION_WARMUP` rejection, then
keeps the research unchanged and moves the start to its next published session
(2026-07-09) with a revised request ID. Its final independent artifact must be
the only Run and must have succeeded. Two diagnostics do not prove admission
correction. The replay's deliberately sparse calendar is not production history.
Each repair decision must start in a later native model step than the result
that justifies it; a valid Formula diagnosis must also precede submission.
Native Memory may omit the initial `step-start` marker. Tool parts before the
first marker belong to an implicit first step; the next marker still begins a
distinct step. Omission must not collapse the original diagnosis and its repair.
Calls already started in the same step, or still pending from an earlier step,
are not reactions to an error. An accepted replay cannot retroactively qualify
an already-created Run as a repair.

Batch success requires successful `factor` Result reads for both distinct child
Run IDs from the authoritative Batch, with matching request and response IDs.
Completed Core artifacts, reading one child twice, a provenance-only read, or a
generic completed-Tool marker cannot substitute for inspecting both Results.

Long polling releases the real Worker only after an actual queued/running
`get_research_run` result. It requires a later succeeded result for that same
Run plus the independently checked artifact and successful Result inspection;
repeated terminal reads are not evidence of polling.
Tool results may arrive out of their invocation order. Polling and failure
recovery use the actual result-event sequence. Retry counts use start/result
events together, so an already-running parallel call is not counted as a
new attempt after an error it could not yet have observed.

## Reports, cost and failure handling

Evidence lives under the new run's `.local/test-runs/<run-id>/evidence/`.
`research-agent-eval.json` and `research-agent-eval.md` retain closed metadata,
hashes, artifact IDs and assertion outcomes, not prompts, Messages, Formulae,
MCP bodies, provider bodies or credentials. Reports include image digests,
source/config/corpus/fixture fingerprints, reasoning mapping, execution bounds,
fixed-denominator success, Tool validity/error/retry rates, correction success,
usage, cost, P50/P95, step counts and repetition variance.

A read-only oracle inside the isolated Agent container uses the native Mastra
message converter and owner-scoped Memory to inspect structured Core outcomes.
Only Formula-correction, admission-correction, unresolved-admission and
Batch-Result-inspection boolean facts leave that container. Private history,
parameters and results are neither
exported nor logged. Deterministic native-Memory and final-image tests validate
this measurement mechanism, not real-model quality.

Primary Run cost estimates come from terminal usage with explicit cached-input
pricing. The Luna profile is marked `published-standard-upper-bound`: it uses
the highest published Standard rates across short/long context, counting
cache writes at the conservative input ceiling. Per million tokens the ceilings
are USD 0.50 input, USD 0.04 cache reads and USD 1.80 output, checked against the
[official API pricing](https://developers.openai.com/api/docs/pricing) on
2026-08-31. The [model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
specifies the 922,000-token maximum input and long-context/cache-write rules.
Using these ceilings for aggregated Run usage deliberately overestimates short
requests rather than inferring their per-request price tiers from totals.

This is a reference-price upper bound, not a statement about the local proxy's
actual billing or subscription limits. If the Operator needs an actual monetary
ceiling, confirm the service's applicable billing basis separately; a model
catalog or successful connectivity probe proves no price contract. An approval
without a monetary ceiling still retains the evaluator's finite protective
per-run budget and execution limits. The spending limit applies to this declared
accounting basis, not an inferred local-service invoice.

Missing usage stays unknown and halts further paid work. Independent generated
titles have a separate conservative upper-bound reserve, not fabricated primary
usage. Before each case, the budget reserves all possible steps and turns using
the Provider input ceiling and configured output maximum, plus title reserves.
An insufficient remaining budget stops before the next case; no automatic
probabilistic retry, provider switch, hidden trimming or spending-limit increase
exists. Unexpected setup/transport failures remain failed/incomplete evidence.
The per-case quality deadline scores latency; it does not abort result collection.
Each submitted Turn has a separate 630-second observation deadline: the isolated
Host's unchanged 600-second Run limit plus 30 seconds for terminal delivery.
A completed case exceeding its quality deadline still fails `within_time`, but
its terminal usage and artifacts remain measurable and the fixed corpus continues.
A stalled observation still fails closed and halts with unknown accounting;
there is no reconnect, paid retry or extension of the Agent's execution limit.
Missing accounting does not overwrite a known terminal Provider/MCP failure.
Recovered Tool errors remain in the error/retry counts but are not reused as
the source of a later unrelated task failure. Tool retry rate counts another
attempt at a capability after its previous failed call; it is not an assertion
that identical request arguments were replayed. Required capabilities must have
completed successfully, not merely have been attempted.
Provider, MCP, Core admission, observed Dataset/Worker and model-quality
failures stay distinct; none are removed from the fixed denominator.
The Provider boundary also classifies native Node Socket interruptions and
SDK-validated [Responses error events](https://developers.openai.com/api/reference/resources/responses/streaming-events#error)
received after output has started. Only structured codes select the public
category; private error wording is neither inspected for meaning nor retained.
Unknown internal exceptions remain internal failures. Classification tests do
not establish the original cause of an older interrupted evaluation, remove
that failure from its report, recover missing usage or prove service stability.

## Qualification and release decision

Review the baseline, then explicitly review/pin candidate thresholds and bounds.
Run all fixed repetitions again with `THESISTRACE_AGENT_EVAL_PHASE=qualification`
and a separately approved spending ceiling. Do not use a partial baseline or
hand-picked successful retries as qualification. A qualification report must
have `qualified: true`, complete accounting, observed supported reasoning, no
ownership or forbidden/invalid Tool failures, and all declared quality/cost/time
and variance thresholds satisfied. Retain the reviewed baseline alongside it.

The current candidate envelope is four active Agent Runs in one 1-CPU, 1-GiB Agent Host;
16-KiB input, a required per-model `context_window` (258,000 for the maintained Luna
configuration), required per-model `max_output_tokens` (128,000 for Luna)
with a dynamic request allowance and a 4,096-token safety margin, a 512-KiB Tool
transport limit, no cumulative generated-byte or model-call count limit, 180-second Provider
calls and a 600-second Run. Authorized Luna/high baselines reached the former
provisional 60- and 120-second Provider-call boundaries. Nine ordinary cases
retain a 180-second quality ceiling. Measured Strategy and Batch workflows use
a 250-second case ceiling, and the candidate P95 ceiling is 250 seconds; these
are scoring thresholds, not longer Provider or Run execution limits. MCP tokens
live 660 seconds with 30 seconds of clock skew allowance. Saturation rejects a new Turn before Session/Run/Memory writes;
existing replay still works. A rejected Turn preserves its original text for
explicit retry. These are reviewed engineering and baseline scoring bounds,
not a completed real-model or production-load qualification. Session-scoped
Observer/Reflector and Session-summary calls share these Run bounds and token
accounting; the [Session context runbook](session-context.md) describes the 90%
trigger, fixed M/S snapshots and small-window gate. Compression is covered by
deterministic model replay; semantic retention quality requires separate real-model
evaluation. The older baseline envelope is not evidence for this changed runtime.

Enable only the exact qualified model/effort in the reviewed startup registry;
there is no runtime auto-enable, hot reload or fallback. Match evidence to the
release's code, corpus, configuration, pricing and production resource envelope.
Changes require explicit review and renewed qualification. If no combination
passes, do not describe any combination as qualification-passed and do not use
the baseline as a release decision. Under the user's explicit ticket waiver,
missing qualification does not block completion of Issue 12 or work on Issue
13; qualification remains a separate Operator workflow.

Paid evaluation preflight currently rejects finite spending budgets: without a
model-call count limit, the existing whole-Turn reservation cannot establish a
finite maximum cost. Per-call spend admission is required before paid evaluation
can run again; historical 16-call cost reserves must not be reused.
