---
status: accepted
---

# Separate field discovery, logical releases, and physical storage

ThesisTrace separates three concerns:

- Field Catalog is the user-facing inventory for discovering Canonical Market
  Data fields and their meaning, unit, time semantics, coverage, and
  availability by Dataset Release.
- Dataset Release is an immutable manifest that identifies one validated
  logical snapshot and binds the exact Research Calendar, Universe snapshots,
  Dataset Schema versions, Adjustment Anchors, Adjustment Factors, and physical
  objects used by a ResearchRun or DailyTrack.
- Physical Data Objects are immutable data partitions or content-addressed
  objects that may be referenced by many Dataset Releases.

Every Dataset Release is a cumulative logical snapshot from Dataset Bootstrap
through its final Research Session. Its immutable manifest records its direct
predecessor, newly appended Research Session range, and accepted historical
correction change-set, including affected logical keys or session ranges and
the replacement Physical Data Objects. A consumer can therefore resolve both a
standard ResearchRun's current 756-session closure and every active
DailyTrack's fixed Origin-to-target closure from that one release.

The first Dataset Release published by Bootstrap is the Release-chain root:
`predecessor = none`, its appended range is the complete bootstrapped Research
Calendar range, and its accepted correction change-set is empty. Every later
Release names exactly one direct predecessor.

This cumulative contract does not require a cumulative physical copy. A daily
release normally stores only the new session's objects and a small manifest
delta referencing its predecessor. A historical correction adds corrected
objects to the next new-session release while older releases continue to
reference the previous objects; V1 does not publish a correction-only release.
Objects referenced by an immutable Release or Tracking Generation remain
retained. ADR-0073 defines Adjustment Anchors as release-owned manifest inputs
rather than Research Window data.

Research authors discover and reference stable fields through the Field
Catalog; they do not select a Dataset Release. Run admission resolves the
latest successful Release and pins it in the ResearchRun's immutable input.
Dataset Schema versions remain internal compatibility metadata already
resolved by that Release; they are not a Research Definition parameter.
