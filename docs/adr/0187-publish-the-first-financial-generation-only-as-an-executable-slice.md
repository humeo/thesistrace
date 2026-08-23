---
status: accepted
---

# Publish the first financial Generation only as an executable slice

The first Dataset Head that references Point-in-Time Financial Data must provide
Financial Research Readiness as one integrated product slice. Its pinned Data
Generation includes validated Raw Financial Batch provenance, the three
Canonical financial version tables, complete Financial Coverage, the Data-owned
point-in-time Series readers, and Alpha Field Capabilities for the initial six
financial fields. Both ResearchRun and DailyTrack must resolve and execute those
fields through the same semantics over Market Coverage beginning at the first
Research Session of 2010 before publication. Acceptance includes one Composite
Alpha that combines at least one market field and one financial field through
`rank` in both execution paths. Development may create and test raw objects,
Canonical tables, and candidate Manifests in stages beside
the active store, but those artifacts remain unpublished and undiscoverable to
ordinary authoring until the complete slice passes acceptance and performance
gates. ThesisTrace does not move the Dataset Head to an ingestion-only financial
Generation or report finance ready merely because tables exist.
