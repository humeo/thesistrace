---
status: accepted
---

# Apply conservative availability to date-only financial disclosures

Point-in-time financial facts may be used only after they were knowable. When
the source provides a precise publication timestamp, ThesisTrace derives the
first usable market session from that timestamp and the market calendar. When
the source provides only a publication date, the fact becomes usable on the
next completed Shanghai or Shenzhen market session.

The conservative next-session rule prevents a historical end-of-day research
from using a disclosure that may have been published after that date's close.
The Data module records both the source publication value and the derived
availability session so the decision remains reproducible.
