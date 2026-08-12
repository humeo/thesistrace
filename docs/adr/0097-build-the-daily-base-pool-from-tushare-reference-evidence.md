---
status: accepted
---

# Build the daily Base Pool from Tushare reference evidence

The Data module automatically builds each point-in-time Universe Base Pool
from Tushare source evidence. V1 uses `stock_basic` for instrument reference
and listing dates, `bak_basic(trade_date)` for the historical daily stock list,
`daily` for observed market bars, and `suspend_d` for dated suspension
evidence. Users and Research Definitions do not select or maintain these source
interfaces.

The source rows are filtered to the ordinary-A-share scope fixed by ADR-0075.
The absence of a `daily` row never determines membership by itself because an
otherwise listed stock may be suspended. A normal full-session trading
suspension therefore leaves Base Pool membership unchanged and is handled by
the Canonical Trading State instead.

If the accepted Tushare responses cannot uniquely establish whether an
instrument belongs to the Base Pool for a required Research Session, Dataset
candidate Data Generation validation fails. V1 does not guess, silently exclude the instrument, or
backfill today's listing status into a historical snapshot. Source permissions
and representative historical and suspended-stock fixtures are bootstrap
acceptance checks.

The accepted evidence is stored and indexed inside the Data Generation.
ResearchRun does not call Tushare while resolving a holding's missing Open;
ADR-0100 performs only conditional local lookups after the ordinary daily-price
path has already failed.
