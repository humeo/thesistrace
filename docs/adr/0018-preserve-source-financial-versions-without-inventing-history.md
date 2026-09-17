# Preserve source financial versions without inventing history

ThesisTrace retains the financial versions and revision evidence actually returned by Tushare and applies point-in-time availability to those facts. It never fabricates a missing revision chain or claims complete historical revisions when the source cannot provide them.

Within one logical report identity, source publication date, and first-observation
time, a unique payload marked `update_flag=1` resolves simultaneous old/new
records. All source versions and raw receipts remain stored; query and seed
selection prefer the marked version at the same effective session, including
its null values. Multiple distinct marked payloads remain quarantined. Without
a marked payload, distinct simultaneous payloads also remain quarantined; a
single unmarked record remains usable. Different report types are never merged.

This preference does not establish a revision timestamp. A later-observed
correction retains its first-observed effective session and cannot replace the
value used before that session. Initial historical collection retains the
existing source-dated bootstrap convention, not a claim of complete historical
revision evidence.
