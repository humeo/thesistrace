CREATE TABLE IF NOT EXISTS thesistrace_control.registration_invitations (
    id text PRIMARY KEY,
    normalized_email text NOT NULL,
    state text NOT NULL CHECK (state IN ('issued', 'revoked', 'expired', 'consumed')),
    issued_by text NOT NULL,
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > issued_at),
    revoked_by text,
    revoked_at timestamptz,
    consumed_at timestamptz,
    consumed_by_user_id text,
    CHECK (
        (state = 'issued' AND revoked_by IS NULL AND revoked_at IS NULL
            AND consumed_at IS NULL AND consumed_by_user_id IS NULL)
        OR (state = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL
            AND consumed_at IS NULL AND consumed_by_user_id IS NULL)
        OR (state = 'expired' AND revoked_by IS NULL AND revoked_at IS NULL
            AND consumed_at IS NULL AND consumed_by_user_id IS NULL)
        OR (state = 'consumed' AND revoked_by IS NULL AND revoked_at IS NULL
            AND consumed_at IS NOT NULL AND consumed_by_user_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS one_issued_invitation_per_email
ON thesistrace_control.registration_invitations (normalized_email)
WHERE state = 'issued';

CREATE TABLE IF NOT EXISTS thesistrace_control.product_users (
    id text PRIMARY KEY,
    insforge_subject text NOT NULL UNIQUE,
    normalized_email text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS thesistrace_control.personal_workspaces (
    id text PRIMARY KEY,
    user_id text NOT NULL UNIQUE
        REFERENCES thesistrace_control.product_users(id),
    created_at timestamptz NOT NULL
);

ALTER TABLE thesistrace_control.registration_invitations
DROP CONSTRAINT IF EXISTS registration_invitations_consumed_by_user_id_fkey;
ALTER TABLE thesistrace_control.registration_invitations
ADD CONSTRAINT registration_invitations_consumed_by_user_id_fkey
FOREIGN KEY (consumed_by_user_id)
REFERENCES thesistrace_control.product_users(id);
