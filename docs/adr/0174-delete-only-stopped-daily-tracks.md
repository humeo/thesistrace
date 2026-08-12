---
status: accepted
---

# Delete only stopped DailyTracks

Users may permanently delete a DailyTrack only when its status is `stopped`.
An `active` or `blocked` Track must first complete the existing explicit Stop
action; Delete does not implicitly stop work or race an active progression.
Deletion removes the Track resource and its owned tracking state, including
progressions, checkpoints, working caches, and receipts, and garbage-collects
physical objects only when no other durable reference needs them. Research
Deletion and DailyTrack Deletion remain independent explicit actions and never
cascade into one another.
