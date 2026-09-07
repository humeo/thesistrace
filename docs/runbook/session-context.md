# Session context and recovery

The main model receives stable instructions and Tools F, Session memory M,
Session handoff summary S, retained original history R, then appended messages N.
M and S belong to one Session; another Session owned by the same Researcher cannot
reuse them. PostgreSQL retains original history separately from the effective
model input. Deleting a Session deletes its checkpoint and recovery records.

## Capacity and trigger

The registry owns `context_window` C, `max_output_tokens` L and the registry-level
`min_compaction_context_window` K. The maintained values are C=258000, L=128000,
K=65536. They are runtime configuration, not a claim about provider billing.

| Rule | Formula | Maintained Luna |
| --- | --- | --- |
| Normal trigger T | floor(C × 0.9) | 232200 |
| Safety margin H | 4096 | 4096 |
| Recent original history target | min(20000, floor(T / 2)) | 20000 |
| Memory reflection trigger | floor(T / 8) | 29025 |
| Reflection and summary text targets | floor(T / 16) | 14512 |
| Actual output allowance D | min(P, L, C − I − H) | Depends on input I |

P defaults to L. Text targets do not replace API output limits: reasoning and text
share the provider's output allowance. The Host estimates the complete model-visible
instructions, Tool definitions, M/S and messages with tokenx, excluding internal
Mastra metadata copies. This is an estimate, not the provider's tokenizer. The
final provider boundary repeats the budget check and passes D through
`maxOutputTokens` (OpenAI Responses uses `max_output_tokens`). Actual usage and
estimate error are observed separately.

Every main inference checks its input, including a new prompt, Continue,
`ask_user` resumption and the complete batch of Tool results. The last Tool result
is included. A finished answer does not trigger idle compression. I >= T starts
normal compression. Without legal output space, an eligible model may attempt
compression early as request protection; it still fails if the result cannot fit.

C < K disables all auxiliary compression and automatic recovery. Existing M/S and
history remain usable when they fit, including above 90%; otherwise the request
fails without trimming them or reverting the chosen model. C = K is eligible.
Switching model, Tools or permissions causes budgets and permissions to be checked
again; it does not silently replace memory or select a different model.

## One atomic compression cycle

1. Freeze the source watermark and select a continuous recent tail around the
   target. Protect the current request and unfinished interactions by stable
   message/part references. A long task need not remain entirely uncompressed.
2. Feed only newly removed, previously unprocessed evidence to Observer together
   with M. Plan batches against the actual auxiliary instructions, prior context
   and output space. Complete tool arguments/results stay paired. A single large
   source can be split into identified fragments for auxiliary input; stored raw
   history remains intact.
3. Append new observations. Only if M exceeds its budget, call Reflector in this
   cycle to reduce it to its target. Empty M is valid. M holds still-valid facts,
   constraints and decisions; task progress belongs to S.
4. Generate or update S from old S and removed original evidence, with candidate
   M as a consistency reference. Long turns can produce a separate prefix summary
   before merging. The six sections cover goal, constraints/preferences, progress,
   decisions, next steps and critical context. Preserve exact resource/request IDs,
   cursors, conditions and relevant errors.
5. Validate completion reasons, structure, source coverage, required references,
   text budgets and the entire new request. An oversized candidate has at most
   one correction. Publish M/S, rendered text, retained references, watermark and
   statistics together after ownership/revision checks. Generation holds no long
   database transaction. Failure or cancellation publishes no partial snapshot.

The selected Run model and effort perform all auxiliary requests, with shared
usage, cancellation, provider deadlines and Run limits. Auxiliary generation
executes no business Tools. The controlled Mastra candidate patch supplies native
Observer/Reflector prompts and parsers; the Host owns batching and commit. The
handoff summary uses the existing Mastra/AI SDK, not a separate Pi runtime.

Absolute dates are rendered at commit time. Between commits the Host reuses the
stored text and retained references; it does not re-render relative dates or slide
R. Run identity and Continue controls have stable internal identities and remain
hidden from the browser's user messages. Tools are ordered deterministically.
This preserves the structural prefix; provider `cached_tokens` remains an observed
metric, not a guarantee of cache hits across requests or model changes.

## Length stops and context rejection

An explicit length stop is recoverable only for eligible models when D < min(P,L).
A provider context rejection shares the same one-attempt budget. The Host durably
claims recovery for the logical step before generating new M/S. Recovery must
reduce input and leave legal output space; length recovery must also improve D.
No improvement, a full requested output allowance exhausted, a second failure or
cancellation ends recovery. A changed error category grants no additional attempt.

The original partial answer remains in the timeline. A replacement has its own
message identity and is invalid for future model input until a complete model
step is confirmed. Completed Tool steps stay valid even when later inference
fails. The guard withholds all tool-input fragments and tool calls until a valid
finish, so length-stopped parameters cannot execute. Previously successful
operations are not replayed. A restarted Host terminates the interrupted Run;
it does not automatically continue it or reset its recovery count.

The UI retains partial text and shows recovery in progress, replacement success
or failure. Refresh reads the same persistent state. Public errors distinguish
`OUTPUT_LIMIT`, `CONTEXT_TOO_LARGE`, `CONTEXT_COMPACTION_FAILED` and
`RECOVERY_FAILED`; raw provider errors are never displayed. Small-window errors
do not appear as recovery in progress.

## Tool data and verification

Core returns bounded business pages, complete records and explicit continuation
cursors; operations return small receipts. See [Research Agent MCP](research-agent-mcp.md).
The 32-KiB page contract, Core 256-KiB wire guard and Host 512-KiB transport guard
serve different boundaries. The model sees one canonical business result, while
the browser receives a safe projection. There is no generic temporary result store.

Use Scripted/Fake/Replay for engineering behavior and isolated PostgreSQL for
atomicity/recovery. Run `pnpm check` and `pnpm test:image-smoke` for final integration
without attaching to Development data. Real-model summary retention and measured
cache usage require separately recorded evaluation; deterministic tests cannot
establish either. See [Research Agent evaluation](research-agent-eval.md).

## Content-free diagnostics

`agent_model_call_finished` records each answer/auxiliary request's configured
capacity, estimated input, requested and actual output allowance, safety margin,
duration, normalized finish reason and individual usage (including cache reads).
A failed or cancelled request without usage stays unknown. These records are
separate from aggregate Run usage; their numeric fields permit comparison of
estimates with actual reported input.

`agent_tool_finished.tool_result_bytes` measures the model-facing serialized
Tool result in UTF-8. `agent_recovery_claimed` records the current Run's durable
attempt count; re-entered Runs reload it from their existing recovery records.
Compaction statistics contain before/after tokens, output allowance, auxiliary
usage and elapsed time. Telemetry never carries prompts, Tool business data or
M/S text, and a failed sink cannot change model or business execution.
