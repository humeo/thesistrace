# Keep Agent Chat separate from Research truth

A Researcher-owned Agent Chat Session can reference multiple Research resources but never owns their inputs, lifecycle, or Results. Deleting the conversation removes its interaction history without changing accepted research, and model conversation context remains confined to that Session, accepting explicit research lookup instead of cross-conversation recall.

Research presentation follows the same boundary. A2UI may compose proposals and
explanations, but accepted ResearchRun, comparison, and DailyTrack components
carry resource IDs only. The authenticated client reads their facts from Core,
preserves comparison order, and shows the read time with an explicit reload.
Reopening a conversation therefore displays current resource state, not an
immutable historical snapshot of model-authored status or metrics. Deleted or
inaccessible resources remain explicit per-resource errors. This costs a Core
read when a card mounts, in exchange for keeping research truth out of generated
UI payloads. Obsolete model-authored status, metrics, and provenance components
are rejected rather than translated.

Failed presentation snapshots retain an allowlisted diagnostic code and their
activity identity across persistence and replay. Provider error text and private
tool payloads do not cross the browser boundary.
