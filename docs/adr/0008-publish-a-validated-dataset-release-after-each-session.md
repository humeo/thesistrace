---
status: superseded by ADR-0155
---

# Publish a validated Dataset Release after each session

After every newly completed Research Session, ThesisTrace V1 automatically
attempts to build and publish a new Dataset Release. Publication occurs only
after all required post-close inputs and quality checks succeed, and the latest
release changes atomically; a failed or incomplete attempt keeps the preceding
release available. Dataset publication does not automatically create or rerun
user ResearchRuns.

The immutable Release manifest identifies its direct predecessor, appended
Research Session range, and accepted historical correction change-set. Under
ADR-0013 it is a cumulative logical snapshot even when its physical encoding is
only a manifest delta plus newly added or corrected objects.

After a Dataset Release commits, ADR-0105 may enqueue independent Advances for
explicitly active DailyTracks. Publication does not wait for those Advances,
and a Tracking failure never rolls back or invalidates the Release.

A historical correction without a new Research Session does not trigger a
correction-only release. ADR-0088 carries it into the next normal publication
attempt. V1 does not perform a complete historical correction scan on every
attempt under ADR-0091.

After consecutive failed publication attempts, ADR-0092 publishes one release
that catches up to the latest completed Research Session. It does not
retrospectively manufacture a separate release for each missed session end.
ADR-0069 defines the shared Research Calendar.
