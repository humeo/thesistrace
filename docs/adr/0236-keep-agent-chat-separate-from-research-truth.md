# Keep Agent Chat separate from Research truth

A Researcher-owned Agent Chat Session can reference multiple Research resources but never owns their inputs, lifecycle, or Results. Deleting the conversation removes its interaction history without changing accepted research, and model conversation context remains confined to that Session, accepting explicit research lookup instead of cross-conversation recall.

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
The client is discarded on conversation unmount, and resources with no remaining
detail views are removed. Reopening the conversation reads current resource state;
the UI never persists research snapshots or puts research truth into generated
payloads. Deleted or inaccessible resources remain explicit per-resource errors.
Reads have a 15-second deadline covering headers and body, retain previous facts
only on transient failure, and cannot replace a newer attempt after cancellation.
Obsolete model-authored status, metrics, and provenance components are rejected
rather than translated.

Failed presentation snapshots retain an allowlisted diagnostic code and their
activity identity across persistence and replay. Provider error text and private
tool payloads do not cross the browser boundary.

The shared contract owns the Zod component definitions. Transport JSON Schema,
server field validation and the official frontend catalog use those definitions;
graph integrity, route restrictions and payload bounds remain validated at the
browser boundary. The persisted v0.9 operations contract remains unchanged.
Existing content is displayed with the application's fixed 16px block spacing
and full content width. Only an identical ordered resource-only view can replace
an earlier view in the same turn; any authored explanation or proposal remains
visible. Tool validation exposes field paths and reasons to the model, while the
browser continues to receive only safe diagnostic codes.
