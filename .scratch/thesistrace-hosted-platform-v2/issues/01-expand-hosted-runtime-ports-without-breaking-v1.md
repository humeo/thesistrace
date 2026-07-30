# 01 — Expand Hosted runtime ports without breaking V1

**What to build:** Introduce the narrow runtime boundaries needed to run the
existing research product against hosted control metadata, immutable objects,
and durable execution while preserving the current local V1 deployment and all
of its externally visible behavior. This is the deliberate prefactor exception
that makes later hosted vertical slices small enough to land independently.

**Blocked by:** `thesistrace-bounded-research-storage/01 — Write deterministic Parquet Physical Data Objects`.

**Status:** resolved

- [x] Research, Dataset Publication, and Daily Tracking services depend on explicit control-metadata, ObjectStore, and execution-dispatch ports rather than constructing one concrete runtime internally.
- [x] The existing local SQLite, filesystem ObjectStore, and local Worker adapters continue to support every V1 API and browser workflow without changing quantitative semantics.
- [x] Hosted adapters can be selected through deployment configuration without branching inside Alpha, Factor, Strategy, or Tracking calculations.
- [x] The ObjectStore boundary accepts the typed immutable JSON and Parquet Physical Data Objects established by the storage specification without exposing physical paths to domain services.
- [x] Existing backend, frontend, and browser acceptance suites remain green before any hosted implementation is selected.
