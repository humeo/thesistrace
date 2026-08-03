---
status: superseded by ADR-0151
---

# Enforce Personal Workspace isolation in the API and PostgreSQL RLS

Every product operation goes through the ThesisTrace API, which derives the authoritative Personal Workspace from the verified InsForge identity, while PostgreSQL row-level security independently enforces the same ownership boundary. Users receive only bounded product views through the API; raw artifacts, object downloads, signed object access, and public InsForge Storage are not product surfaces because immutable storage remains private.
