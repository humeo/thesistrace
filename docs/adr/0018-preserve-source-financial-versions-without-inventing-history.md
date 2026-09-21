# Preserve source financial versions without inventing history

ThesisTrace retains the financial versions and revision evidence actually returned by Tushare and applies point-in-time availability to those facts. It never fabricates a missing revision chain or claims complete historical revisions when the source cannot provide them.

Within one logical report identity, source publication date (`f_ann_date`), and
first-observation time, records marked `update_flag=1` take precedence. If more
than one marked record remains, the greatest `ann_date` wins. All source
versions and raw receipts remain stored; query, history compaction, TTM seed,
and formula selection use the same ordering and preserve the winning row's null
values. Multiple distinct payloads tied at the greatest `ann_date` remain
quarantined. Without a marked payload, the same `ann_date` rule applies to the
remaining records. Different `f_ann_date` values remain separate PIT versions,
and different report types are never merged.

Financial indicator observations do not expose `f_ann_date` or report type. For
rows observed together with the same instrument, report period, and `ann_date`,
the same `update_flag=1` preference applies. Multiple distinct marked payloads
remain quarantined. The immutable observation receipt retains every returned
row even though indicator projection and formulas consume only the winner.

This preference does not establish a revision timestamp. A later-observed
correction retains its first-observed effective session and cannot replace the
value used before that session. Initial historical collection retains the
existing source-dated bootstrap convention, not a claim of complete historical
revision evidence.

Incremental projection compares the newly projected receipts with the logical
rows actually stored in the published financial Family. It does not regenerate
the old side with current projection rules. A rule correction can therefore
replace an older quarantined projection even when the raw receipt is unchanged.
New conflicts still fail the company acceptance boundary; resolving a previously
stored quarantine updates both the row overlay and the Family quarantine summary.
Projection and comparison run one instrument at a time and spool cross-market
rows to a task-local disk index before writing immutable delta objects.
