---
status: accepted
---

# Separate InsForge identity from ThesisTrace Auth Sessions

Hosted Platform V2 keeps InsForge as the sole source for registration,
credentials, identity verification, email verification, and password recovery,
while the ThesisTrace Control API establishes the sole browser-facing Auth
Session after privately exchanging credentials with InsForge. ThesisTrace
stores no password, the browser never receives or directly uses an InsForge
token, and a Registration Invitation remains product authorization to provision
the verified User and Personal Workspace rather than a second identity
mechanism. This supersedes ADR-0114 because keeping InsForge tokens behind the
Control API reduces the public interface and decouples the browser from the
identity provider at the cost of operating a revocable application-session
module. Each Auth Session is server-side state in PostgreSQL: the browser holds
only an opaque high-entropy secret, PostgreSQL stores only its hash and
lifecycle state, and any InsForge refresh token is encrypted at rest behind the
Control API. This is preferred over a self-contained signed cookie so logout,
operator-assisted revocation, multi-device sessions, and API restarts retain one
authoritative revocation seam.
