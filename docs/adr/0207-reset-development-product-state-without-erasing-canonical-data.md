---
status: accepted
---

# Reset development Product State without erasing Canonical Data

`pnpm dev:reset` becomes the identity-checked Development Product State Reset.
It stops the canonical development Compose project, removes and recreates only
its PostgreSQL and RustFS volumes, initializes the current checkout's schemas,
and leaves the canonical-data volume and filesystem Dataset Head unchanged.
The initialized runtime validates and immediately reuses that mounted Head.

The reset permanently removes old Research Folders and ResearchRuns, Attempts,
Results, Execution Checkpoints, Staged Result Partitions, DailyTracks, receipts,
and other Product State. ThesisTrace writes no Schema migration, compatibility
reader, checkpoint adapter, or legacy execution branch. Browser state that
references removed Product resources is treated as stale local state rather
than migrated server data.

Complete deletion of downloaded Canonical Market and Financial Data moves to a
separate explicit identity-checked `pnpm dev:erase` operation. That command is
the only ordinary development lifecycle action that removes all three named
volumes and requires the operator to bootstrap or restore Canonical Data again.

This changes ADR-0152's development reset boundary while preserving its
canonical Compose identity checks, persistent stop/start behavior, isolated Test
environments, and destructive full-environment cleanup when explicitly chosen.
The hard Schema cut therefore does not require another Tushare download.
