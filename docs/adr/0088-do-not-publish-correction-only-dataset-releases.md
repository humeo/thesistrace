---
status: accepted
---

# Do not publish correction-only Dataset Releases

V1 attempts Dataset Publication only after a newly completed Research Session
extends the latest Dataset Release's Research Calendar. Discovery of a Tushare
historical correction by itself does not publish another release with the same
calendar end.

ADR-0091 does not make historical correction discovery part of the normal
daily path: V1 does not re-fetch the complete three-year history after every
close. This ADR governs a correction only after an overlapping fetch, recovery,
or future repair workflow has actually discovered and accepted it.

The accepted correction remains pending until the next normal post-close
publication attempt. That candidate release binds both the new Research
Session and every accepted correction to its cumulative logical snapshot,
including the standard current ResearchRun dependency closure, every active
DailyTrack's complete Origin-to-target dependency closure, and an Adjustment
Anchor that predates Research Input History. Its correction change-set
identifies the affected logical keys or session ranges and replacement objects.
If the corrected dependency set fails validation, publication fails and the
previous latest release remains available.

Older Dataset Releases and their pinned ResearchRuns never change. The next
successful release may reference new corrected Physical Data Objects while
reusing every unchanged object; it does not copy the full historical dataset.
If no new Research Session completes, no release is published regardless of
how many corrections are pending.

If such a correction changes an active DailyTrack dependency, ADR-0144 applies
it prospectively in the next normal Tracking Advance. The Advance continues
from the current Checkpoint in the same Tracking Generation and never rewrites
already published observations.

This cadence deliberately permits a correction to wait through a weekend or
market holiday. V1 does not expose an operator action for publishing a
correction-only release.
