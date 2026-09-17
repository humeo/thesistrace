# Discover financial reports from structured disclosure periods

Financial Refresh uses TuShare `disclosure_date` as its only discovery source.
This supersedes [ADR-0219](0219-drive-daily-financial-refresh-from-cninfo-disclosures.md)
and [ADR-0232](0232-resolve-financial-announcement-triggers-from-stock-level-canonical-deltas.md).
The runtime and Replay no longer scrape CNINFO, classify announcement titles, or
create announcement-triggered work.

Each refresh checks the last three closed quarter ends and all additional periods
crossed since the previous complete check. This bounded overlap catches changes
to the recent disclosure calendar without fetching every company's history daily.
Only a nonempty `actual_date` on or before the target Research Session creates a
requirement. `pre_date` and `ann_date` on the timetable are not proof of a report's
publication. A failed, malformed or capped list response records a gap for that
report period; it cannot advance the complete-check date.

A Financial Report Requirement is identified by instrument, source endpoint and
report period. The required endpoints are `income`, `balancesheet`, `cashflow`
and `fina_indicator`. Accepted source evidence for the same period resolves the
requirement independently of the timetable's publication date. A successful
request returning only an older period remains pending. Nullable metric cells do
not create a missing-report requirement. Existing validation, quarantine and
point-in-time availability still govern whether individual facts can be used.

The refresh first persists the disclosure check, reconciles requirements against
its accepted source Generation, and freezes the collection plan. Pending reports
and failed checks retry on the next refresh. Separately, each source family checks
up to 64 other companies in order of oldest actual check time. This rotation
examines full histories to discover revisions to already received reports and
continues even when the target session has not changed. The three statements
retain their atomic per-company acceptance boundary. Accepted facts survive
failed requests. Resume reuses saved plans and validated checkpoints.
Persisted disclosures survive interruption before collection. Indicator report
readiness is reconciled with the merged candidate in the same transaction that
records it: an omitted old row preserves accepted history, while a conflicting
latest observation reopens the requirement until a valid later response arrives.

The [TuShare disclosure-date contract](https://tushare.pro/document/2?doc_id=162)
provides structured report periods and actual dates, not an exhaustive correction
feed or a 48-hour delivery guarantee. Rotation gives eventual re-observation; a
complete disclosure check does not promise that all supplier data is final or
that every field is populated. Operator status reports statement pending,
indicator pending and disclosure-list gaps separately.

Previously published Generations and source receipts keep their immutable
provenance and remain verifiable. Their archived announcement evidence cannot
create new work. Explicit [migration 0005](../database-migrations.md#0005-structured-financial-disclosures)
preserves historical rows and accepted dataset objects while introducing the
new report ledger. Its first refresh rebuilds requirements from structured
disclosures and accepted report evidence; old tasks are neither blindly copied
nor falsely marked completed.
