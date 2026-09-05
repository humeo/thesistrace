# Separate Better Auth identity from Core Research authorization

A dedicated Better Auth service owns invite-only identity and Login Sessions, while Core owns Research Ownership and verifies browser sessions through a private Auth call behind one public origin. Independent schemas and runtime privileges accept the cost of that call to make access revocation observable without duplicating identities, trusting proxy identity headers, or introducing organization-wide roles.
