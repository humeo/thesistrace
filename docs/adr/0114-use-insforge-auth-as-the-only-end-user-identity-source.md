---
status: accepted
---

# Use InsForge Auth as the only end-user identity source

Hosted Platform V2 uses InsForge Auth as the sole provider of end-user registration, credentials, sessions, email verification, and password recovery; ThesisTrace stores no passwords and issues no parallel end-user sessions. A single-use Registration Invitation is ThesisTrace authorization to provision the authenticated identity's User and Personal Workspace, not a second identity mechanism, while ThesisTrace remains responsible for Personal Workspace authorization, RLS, and quota enforcement.
