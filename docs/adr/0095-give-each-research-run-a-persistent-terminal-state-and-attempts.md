---
status: accepted
---

# Give each ResearchRun a persistent terminal state and attempts

Every ResearchRun follows one durable lifecycle:

```text
queued -> running -> succeeded | failed
queued -> cancelled
running -> cancelling -> cancelled
```

Transient infrastructure retry creates another ResearchRun Attempt under the
same user-visible identity, frozen ResearchRun input, Data Generation, and
execution plan. A valid private checkpoint is resumed; a stale Attempt is fenced
from checkpoint or Result publication, and terminal cancellation discards all
private continuation state.

Admission accepts an idempotency key so repeated delivery resolves to the same
ResearchRun. A new user execution is always an ordinary Run from a Browser Draft
and therefore creates a new ResearchRun; infrastructure Attempts are never
exposed as research reuse.
