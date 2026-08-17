---
status: accepted
---

# Start Financial Coverage in 2010 with minimal pre-start seeds

The initial Point-in-Time Financial Data product sets Financial Coverage Start
to the first Research Session of 2010, and its first executable Dataset Head
also backfills Market Coverage to that session. It retains every accepted Source
Financial Version that becomes available on or after that session, regardless
of the version's report period. For every Instrument Identity already in scope
at Coverage Start, it also retains only the pre-start Financial Seed Facts
needed by the initial authorable fields: the latest available full-year facts
for Latest Annual Financial Fields and the latest available balance-sheet facts
for Latest Reported Stock Fields. Instruments listed later begin with their
first available facts. Seed Facts do not create pre-2010 research support or
move Financial Coverage Start backward. Collection and validation must use the
historical Instrument Identity set rather than only currently listed equities,
so the bootstrap does not introduce survivorship bias. Bootstrap uses one
complete-history logical shard for each `endpoint × instrument` when the
deployment capability probe proves that response complete. As specified by
[ADR-0192](0192-paginate-the-ordinary-balance-sheet-inside-one-logical-shard.md),
the ordinary balance-sheet adapter fulfills that shard with deterministic
provider pagination. The exact ordered logical response is retained as a Raw
Financial Batch, while Canonical version tables materialize only versions
inside Financial Coverage plus the required Financial Seed Facts. Earlier rows
in the Raw Financial Batch are evidence, not pre-2010 Financial Coverage. If a
complete response cannot be proven, the collector fails closed; it does not
switch to date shards at runtime.
