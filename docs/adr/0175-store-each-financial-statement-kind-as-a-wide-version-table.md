---
status: accepted
---

# Store each financial statement kind as a wide version table

ThesisTrace stores accepted income statements, balance sheets, and cash-flow
statements in three separate wide Canonical version tables, with one row per
Source Financial Version and nullable columns for every field in that
statement's pinned source contract. This preserves the source report boundary
and lets Parquet project only requested columns without multiplying each report
into hundreds of long-form rows. Raw accepted response batches remain separate
content-addressed evidence, while Session-Aligned Financial Fields are derived
on demand rather than permanently expanding report values over daily sessions.
