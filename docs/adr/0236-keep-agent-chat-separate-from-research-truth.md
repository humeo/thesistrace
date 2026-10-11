# Keep Agent Chat separate from Research truth

A Researcher-owned Agent Chat Session can reference multiple Research resources but never owns their inputs, lifecycle, or Results. Deleting the conversation removes its interaction history without changing accepted research, and model conversation context remains confined to that Session, accepting explicit research lookup instead of cross-conversation recall.

Session model settings record selection intent separately from the actual model
identity on each accepted Run. `modelSelectionMode` in the existing thread metadata
is `default` or `manual`, persisted atomically at Prompt/Continue acceptance.
Sessions without recorded intent follow the registered default; opening them does
not rewrite stored model keys. The composer initializes default mode from the
current catalog and retains valid manual choices. Retired saved models or efforts
initialize the complete current default before sending. The picker can explicitly
return to default mode. Every new request carries its displayed model, effort and
intent; a default request that no longer matches the catalog is rejected before
execution. Accepted and resumed Runs retain their pinned model identity. Updating
the default catalog requires no per-model preference migration.

The browser keeps unsent message and question drafts, pending command receipts,
model-picker edits and reading positions by Session within the Researcher's
workspace. Switching conversations restores those edits and a short-lived
public timeline snapshot, then reconciles current Session and timeline facts in
the background. It never resubmits a retained input: pending commands reconcile
by their original command ID before clearing a draft. The existing workspace
Query client owns these caches and discards them when the Researcher changes.
Model discovery and context usage share that client; the CopilotKit connection
lives across Chat navigation while each scoped agent belongs to one Session.
Research resource queries below still reopen against current Core truth.

Automatic Session naming is independent of the Chat Turn and has a one-minute
deadline. The browser observes the saved title for up to one minute without
holding Chat execution open. Until a generated or manually renamed title exists,
Session reads expose a message title from the first 32 Unicode characters of the
first durable user message, with whitespace collapsed. The internal `Untitled`
sentinel continues to control generation and retry; message titles are display
data and never overwrite saved names. Existing Sessions use the same read-time
presentation without model backfill or rewriting history.

Research presentation follows the same boundary. The model-facing render_a2ui Tool accepts only three semantic views: an ordered
research_runs list, an unsubmitted alpha_proposal, or a daily_track. The
application constructs the A2UI operations; the model cannot choose component
graphs, surface identities, spacing, alignment, bindings or actions. Explanations,
headings and ordinary tables use the normal Markdown response. Accepted
ResearchRun, comparison and DailyTrack components carry resource IDs only. The authenticated client reads their facts from Core,
preserves comparison order, and shows the read time with an explicit reload.
Only references in the latest Turn load research details, for the last five
distinct resources across all its views, ranked by their latest occurrence in
display order. Original reference order is preserved. Earlier Turns and
references outside that selection render ordinary detail links without reading Core.
Failed reads still occupy the limit; a new Turn without research references does
not load an earlier Turn. Loading older history does not extend the window.
Within the window, references to the same
resource share an authenticated read through a conversation-scoped TanStack
Query client, and an explicit reload updates all its visible occurrences.
New references to ongoing research or tracking revalidate its shared state, so
completion can appear without retaining a previous running snapshot.
Resources with no remaining detail views are removed from the conversation client.
On conversation unmount, its completed reads move to a Session-keyed, short-lived
snapshot in the existing Researcher workspace cache, and the client is discarded.
Reopening hydrates that snapshot before presentation. Successful reads of terminal
resources remain fresh for 30 seconds from the original successful read;
navigation does not extend that window. Expired, ongoing and failed reads
revalidate against Core on reopening, while explicit reload always reads Core.
The old read time remains visible until a successful refresh; refreshing does
not replace known facts with loading rows.
Snapshots expire with the workspace cache and are discarded on Researcher change;
they never enter persistent browser storage or generated payloads. Deleted or
inaccessible resources clear their previous facts and remain explicit errors.
Reads have a 15-second deadline covering headers and body, retain previous facts
only on transient failure, and cannot replace a newer attempt after cancellation.
Obsolete model-authored status, metrics, and provenance components are rejected
rather than translated.

Successful render_a2ui output is display-only: persist its complete operations
for frontend replay, but assemble an empty tool result for the model. Keep the
call/result pair intact and retain correctable validation errors. This applies
before main-model token budgeting, to restored history, and to the Observer and
handoff summary evidence; UI operations must not consume model context or be
copied into Session memory.

Failed presentation snapshots retain an allowlisted diagnostic code and their
activity identity across persistence and replay. Provider error text and private
tool payloads do not cross the browser boundary.

Live Chat display uses the persisted public timeline, including its canonical
entry IDs, ordering and timestamps. The Host emits the current Turn and Session
as `chat_timeline_update` through native AG-UI CUSTOM events after projection
is saved, using the same browser-safe serializers as HTTP history. Text updates
follow the projector's existing bounded flush cadence. The browser applies these
updates directly; tokens do not trigger history requests. HTTP reads initialize
and paginate history and reconcile command completion, and a read started before
a live update cannot replace that newer Turn. A replaying Run caches native deltas
and only its latest public Turn snapshot, avoiding retention of every growing
copy of the answer. Model context and Research resource state remain separate.

The shared contract owns the Zod component definitions. Transport JSON Schema,
server field validation and the official frontend catalog use those definitions;
graph integrity, route restrictions and payload bounds remain validated at the
browser boundary. The persisted v0.9 operations contract remains unchanged.
Existing content is displayed with the application's fixed 16px block spacing
and full content width. Only an identical ordered resource-only view can replace
an earlier view in the same turn; any authored explanation or proposal remains
visible. Tool validation exposes field paths and reasons to the model, while the
browser continues to receive only safe diagnostic codes.
