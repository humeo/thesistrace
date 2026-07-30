---
status: accepted
---

# Bind Adjustment Anchors to the Dataset Release

An Adjustment Anchor is data lineage owned by Dataset Release. It is not a
Strategy setting, Research Definition option, or member of the rolling Research
Window.

For each instrument, the anchor is the first session on or after its listing
date that has both a valid raw daily bar and a valid Source Adjustment Factor.
The immutable anchor record contains:

```text
instrument_id
anchor_session
anchor_adjustment_factor
```

Dataset Publication derives the anchor from source data rather than from import
time or the first ResearchRun that encounters the instrument. It fails rather
than falling back to import time when source lifecycle or history cannot
determine one unique earliest qualifying session.

A Dataset Release manifest binds the exact immutable identities of, at minimum:

```text
Dataset Release
├── Research Calendar
├── Universe snapshots
├── Canonical Dataset Schemas and Physical Data Objects
├── Adjustment Anchors
├── Adjustment Factors
└── other required dated families, including industry and trading state
```

This is logical manifest ownership, not a physical copy of every object.
Unchanged releases may reuse the same content-addressed anchor, factor, calendar,
and market-data objects.

An Adjustment Anchor may predate the 756-session Research Input History. The
release retains that one anchor record independently, so advancing the Research
Window never changes `anchor_session` or `anchor_adjustment_factor`. No complete
pre-window price history is required solely to keep the anchor.

A Tushare correction to an anchor fact creates new immutable Physical Data
Objects for the next new-session Dataset Release, which recomputes affected
Adjusted Research Prices. It does not publish a correction-only release under
ADR-0088. Earlier releases and their pinned ResearchRuns remain unchanged.
Appending sessions without an anchor correction reuses the existing anchor.

Factor Evaluation, Strategy Backtest, Alpha generation and validation,
collaborative review, and later reproduction all resolve data through the same
concrete Dataset Release. None may substitute a current calendar, Universe,
field schema, anchor, or factor independently.
