# Separate Better Auth identity from Core Research authorization

A dedicated Better Auth service owns email-verified identity and Login Sessions, while Core owns Research Ownership and verifies browser sessions through a private Auth call behind one public origin. Independent schemas and runtime privileges accept the cost of that call to make access revocation observable without duplicating identities, trusting proxy identity headers, or introducing organization-wide roles.

Public access uses email OTP verification: first successful verification creates a Researcher and subsequent verification authenticates the same canonical, database-unique email. This is the sole registration and login path. Operator-issued invitations and password credentials are no longer provisioned; password sign-in, change and recovery remain unavailable. Existing identities and Sessions survive the explicit data-preserving Auth upgrade.
