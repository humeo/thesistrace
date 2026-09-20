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

This preference does not establish a revision timestamp. A later-observed
correction retains its first-observed effective session and cannot replace the
value used before that session. Initial historical collection retains the
existing source-dated bootstrap convention, not a claim of complete historical
revision evidence.
