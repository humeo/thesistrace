# Reuse published indicator projections with checked evidence

A Financial Refresh may reuse an unchanged financial indicator partition from its accepted source Generation. The refresh obtains that Generation from Dataset Head and persists its address at admission. Its exact indicator Family reference is the authority for the prior source-to-projection proof; an arbitrary candidate address, a user-supplied reference, or a cached validated flag is not publication authority.

Reopening this published Family verifies the addressed manifest, current object bytes and schemas, source evidence and observation references, collection coverage, discovery gaps, and the exact Family reference. It does not regenerate the already accepted projection. Full source replay remains the audit and untrusted-candidate validation path. Changing projection semantics requires the existing explicit contract evolution process; an old proof cannot authorize a different projection contract.

Incremental construction compares security identities and observation addresses. It reuses partitions only when those inputs are unchanged and the old research calendar is an exact prefix of the new calendar. Calendar extension invalidates partitions containing facts outside the old calendar. A changed identity, observation, or non-prefix calendar requires projection. Readiness and unresolved discovery metadata are recomputed independently of partition reuse. Missing or damaged source evidence and objects fail validation; they never trigger silent reuse.

Publication must still establish that each newly proposed partition either equals its accepted, unchanged predecessor or matches the projection of its changed inputs. A successful build alone is not publication authority. Differential full-replay tests and operation-level projection counts verify the incremental boundary.

One refresh may share compact verified collection indexes, manifest descriptors and partition metadata between coverage, construction and composition. This session retains neither decoded observation rows nor wide Parquet tables, ends with that refresh, and is recreated after recovery. Before publication validation reuses a proof, it rehashes its addressed sources, manifests and objects through the ordinary bounded, symlink-safe reader. Schema and identity checks need only their relevant columns; changed partitions still undergo source projection comparison. Returned mutable metadata cannot alter the session's proof, and no persisted cache flag substitutes for the current bytes or the exact accepted predecessor.

Financial statement refreshes apply the same task lifetime to their SQLite workset.
The published logical view contains metadata and physical object/row positions;
only selected companies and companies affected by calendar extension load full
values, batched by object. The exact source Family pins its source Generation;
the collection fields and calendar also bind reuse. Metadata scanning verifies
addressed bytes, the complete schema, ordering, row counts and partition boundaries.
Neither research availability filtering nor history compaction defines report presence.

The published view is immutable during the task. Candidate deltas override it by
`endpoint + source_row_sha256` before report presence and quarantine are computed.
An accepted version can still prove report presence when another version does not;
`pending_calendar` and `outside_calendar` retain their existing presence semantics.
Unioning old and new report-period sets cannot implement these rules.

Preparation writes immutable delta objects and returns a private draft containing
the final report inventory, quarantine summary and Family template, without global
financial values. Daily refresh and retained reprojection reconcile coverage from
that draft and finalize one Family. Finalization independently reprojects retained
and collected inputs per company, checks exact delta bytes and old referenced
objects, and verifies that the resulting inventory equals the draft. Only then may
the existing transaction record the candidate and reconcile pending requirements.
The newly validated inventory can be read without rebuilding a candidate-wide
workset; reuse still rechecks addressed objects. The draft and successful construction
alone never authorize publication. Recovery rebuilds the task workset from durable
checkpoints; completion and interruption release it. Historical Generations continue
to validate their stored facts, without applying current projection rules retroactively.

Immediately before composition, daily refresh and retained reprojection rehash the
candidate's addressed table objects again. A proof established earlier in the task
cannot authorize changed bytes at publication. Recovery without that task-local
source-to-candidate proof independently validates the candidate before this check;
the check itself does not decode values or rebuild the global workset.
