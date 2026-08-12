---
status: accepted
---

# Reuse Research only through Use as Draft

ThesisTrace has no separate Rerun action or endpoint. `Use as Draft` is the
only user action that reuses a ResearchRun's authorable values: after protecting
unexecuted local changes, it copies those values into the selected Research
Folder's Browser Draft and neither creates a backend resource nor starts an
execution. The user may then Run the values unchanged or edit them first; both
paths use ordinary authoritative compilation and admission and create a new
ResearchRun. Infrastructure retries remain Attempts under the same ResearchRun
and are not exposed as research reuse. This decision supersedes the user-Rerun
lifecycle in ADR-0095, ADR-0151, and ADR-0154 without preserving a compatibility
action.
