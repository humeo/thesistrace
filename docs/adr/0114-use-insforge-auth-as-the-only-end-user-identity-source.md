---
status: accepted
---

# Use InsForge Auth as the only end-user identity source

Hosted Platform V2 delegates end-user registration, credential verification,
session issuance, and identity recovery to InsForge Auth. ThesisTrace stores no
passwords and issues no parallel end-user sessions. An authenticated InsForge
user identity maps to one ThesisTrace User, and provisioning that User's
Personal Workspace is idempotent.

Authentication does not grant resource access by itself. ThesisTrace enforces
Personal Workspace ownership, authorization, RLS, and quota boundaries for the
authenticated User. Platform schedulers and Workers use separate service
identities rather than impersonating end users.

The first hosted release accepts registration only through a single-use
Registration Invitation bound to a verified email address. Public login remains
available, but public self-service Workspace creation remains disabled until
quota enforcement, rate limiting, audit, abuse controls, and capacity evidence
are ready.

InsForge Auth exposes email-and-password registration and login as the only
end-User login method in the first hosted release. InsForge also owns email
verification and password recovery. The product enables no social OAuth,
enterprise SSO, magic-link-only login, or parallel ThesisTrace credential
flow. ADR-0143 protects these public Auth routes without routing credentials
through the ThesisTrace API.
