---
status: accepted
---

# Compile Alpha Formulas when a Run is admitted

The browser holds the research author's Alpha Formula exactly as editable
source and may preserve it locally while it is incomplete or invalid. Run
admission compiles the submitted Formula under the current Alpha Language
contract into one canonical Alpha Expression. Failed compilation returns
structured Alpha Diagnostics and creates no durable backend resource. Accepted
admission creates a ResearchRun that freezes the Formula for display and audit
and the Expression as its sole Alpha execution truth; the Worker executes the
frozen Expression and never reparses source. Browser source changes, formatting,
or later compiler changes therefore cannot alter an accepted ResearchRun or
its DailyTrack.
