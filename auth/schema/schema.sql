CREATE TABLE auth."user" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() NOT NULL,
    "name" text NOT NULL,
    "email" text NOT NULL,
    "emailVerified" boolean NOT NULL,
    "image" text,
    "createdAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "active" boolean NOT NULL,
    CONSTRAINT user_pkey PRIMARY KEY ("id"),
    CONSTRAINT user_email_key UNIQUE ("email"),
    CONSTRAINT user_email_canonical_check CHECK (
        "email" = pg_catalog.lower(pg_catalog.btrim("email"))
        AND pg_catalog.char_length("email") <= 254
    )
);

CREATE TABLE auth.operator_assignment (
    singleton boolean NOT NULL,
    researcher_id uuid NOT NULL,
    assigned_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT operator_assignment_pkey PRIMARY KEY (singleton),
    CONSTRAINT operator_assignment_singleton_check CHECK (singleton),
    CONSTRAINT operator_assignment_researcher_id_key UNIQUE (researcher_id),
    CONSTRAINT operator_assignment_researcher_id_fkey FOREIGN KEY (researcher_id)
        REFERENCES auth."user" (id) ON DELETE RESTRICT
);

CREATE TABLE auth."session" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() NOT NULL,
    "expiresAt" timestamp with time zone NOT NULL,
    "token" text NOT NULL,
    "createdAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp with time zone NOT NULL,
    "ipAddress" text,
    "userAgent" text,
    "userId" uuid NOT NULL,
    CONSTRAINT session_pkey PRIMARY KEY ("id"),
    CONSTRAINT session_token_key UNIQUE ("token"),
    CONSTRAINT session_userId_fkey FOREIGN KEY ("userId")
        REFERENCES auth."user" ("id") ON DELETE CASCADE
);

CREATE TABLE auth."account" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() NOT NULL,
    "issuer" text NOT NULL,
    "accountId" text NOT NULL,
    "providerId" text NOT NULL,
    "userId" uuid NOT NULL,
    "accessToken" text,
    "refreshToken" text,
    "idToken" text,
    "accessTokenExpiresAt" timestamp with time zone,
    "refreshTokenExpiresAt" timestamp with time zone,
    "scope" text,
    "password" text,
    "createdAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp with time zone NOT NULL,
    CONSTRAINT account_pkey PRIMARY KEY ("id"),
    CONSTRAINT account_userId_fkey FOREIGN KEY ("userId")
        REFERENCES auth."user" ("id") ON DELETE CASCADE
);

CREATE TABLE auth."verification" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() NOT NULL,
    "identifier" text NOT NULL,
    "value" text NOT NULL,
    "expiresAt" timestamp with time zone NOT NULL,
    "createdAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT verification_pkey PRIMARY KEY ("id")
);

CREATE TABLE auth."rateLimit" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() NOT NULL,
    "key" text NOT NULL,
    "count" integer NOT NULL,
    "lastRequest" bigint NOT NULL,
    CONSTRAINT rateLimit_pkey PRIMARY KEY ("id"),
    CONSTRAINT rateLimit_key_key UNIQUE ("key")
);

CREATE TABLE auth.researcher_invitation (
    id uuid DEFAULT pg_catalog.gen_random_uuid() NOT NULL,
    email text NOT NULL,
    token_hash bytea NOT NULL,
    status text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    delivered_at timestamp with time zone,
    terminal_at timestamp with time zone,
    user_id uuid,
    CONSTRAINT researcher_invitation_pkey PRIMARY KEY (id),
    CONSTRAINT researcher_invitation_token_hash_key UNIQUE (token_hash),
    CONSTRAINT researcher_invitation_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES auth."user" (id) ON DELETE CASCADE,
    CONSTRAINT researcher_invitation_email_canonical_check CHECK (
        email = pg_catalog.lower(pg_catalog.btrim(email))
        AND pg_catalog.char_length(email) <= 254
    ),
    CONSTRAINT researcher_invitation_token_hash_check CHECK (
        pg_catalog.octet_length(token_hash) = 32
    ),
    CONSTRAINT researcher_invitation_status_check CHECK (
        status = ANY (ARRAY[
            'delivery_pending'::text,
            'delivered'::text,
            'delivery_failed'::text,
            'consumed'::text,
            'revoked'::text
        ])
    ),
    CONSTRAINT researcher_invitation_lifecycle_check CHECK (
        (status = 'delivery_pending' AND delivered_at IS NULL
            AND terminal_at IS NULL AND user_id IS NULL)
        OR (status = 'delivered' AND delivered_at IS NOT NULL
            AND terminal_at IS NULL AND user_id IS NULL)
        OR (status IN ('delivery_failed', 'revoked')
            AND terminal_at IS NOT NULL AND user_id IS NULL)
        OR (status = 'consumed' AND delivered_at IS NOT NULL
            AND terminal_at IS NOT NULL AND user_id IS NOT NULL)
    )
);

CREATE TABLE auth.password_reset (
    id uuid DEFAULT pg_catalog.gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    token_hash bytea NOT NULL,
    status text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    delivered_at timestamp with time zone,
    terminal_at timestamp with time zone,
    CONSTRAINT password_reset_pkey PRIMARY KEY (id),
    CONSTRAINT password_reset_token_hash_key UNIQUE (token_hash),
    CONSTRAINT password_reset_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES auth."user" (id) ON DELETE CASCADE,
    CONSTRAINT password_reset_token_hash_check CHECK (
        pg_catalog.octet_length(token_hash) = 32
    ),
    CONSTRAINT password_reset_status_check CHECK (
        status = ANY (ARRAY[
            'delivery_pending'::text,
            'delivered'::text,
            'delivery_failed'::text,
            'consumed'::text,
            'revoked'::text
        ])
    ),
    CONSTRAINT password_reset_lifecycle_check CHECK (
        (status = 'delivery_pending' AND delivered_at IS NULL
            AND terminal_at IS NULL)
        OR (status = 'delivered' AND delivered_at IS NOT NULL
            AND terminal_at IS NULL)
        OR (status IN ('delivery_failed', 'revoked')
            AND terminal_at IS NOT NULL)
        OR (status = 'consumed' AND delivered_at IS NOT NULL
            AND terminal_at IS NOT NULL)
    )
);

CREATE TABLE auth.security_audit (
    id uuid DEFAULT pg_catalog.gen_random_uuid() NOT NULL,
    occurred_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    event text NOT NULL,
    outcome text NOT NULL,
    researcher_id uuid,
    unknown_email_hmac bytea,
    CONSTRAINT security_audit_pkey PRIMARY KEY (id),
    CONSTRAINT security_audit_researcher_id_fkey FOREIGN KEY (researcher_id)
        REFERENCES auth."user" (id) ON DELETE RESTRICT,
    CONSTRAINT security_audit_event_check CHECK (
        event = ANY (ARRAY[
            'invitation_issued'::text,
            'invitation_revoked'::text,
            'invitation_accepted'::text,
            'sign_in_succeeded'::text,
            'sign_in_failed'::text,
            'password_reset_requested'::text,
            'password_reset_succeeded'::text,
            'password_reset_failed'::text,
            'password_changed'::text,
            'sessions_revoked'::text,
            'researcher_deactivated'::text,
            'researcher_reactivated'::text,
            'display_label_corrected'::text
        ])
    ),
    CONSTRAINT security_audit_outcome_check CHECK (
        outcome = ANY (ARRAY[
            'succeeded'::text,
            'failed'::text,
            'rejected'::text,
            'no_change'::text
        ])
    ),
    CONSTRAINT security_audit_identity_check CHECK (
        pg_catalog.num_nonnulls(researcher_id, unknown_email_hmac) = 1
    ),
    CONSTRAINT security_audit_unknown_email_hmac_check CHECK (
        unknown_email_hmac IS NULL
        OR pg_catalog.octet_length(unknown_email_hmac) = 32
    )
);

CREATE TABLE auth.auth_secret_contract (
    singleton boolean NOT NULL,
    secret_fingerprint text NOT NULL,
    CONSTRAINT auth_secret_contract_pkey PRIMARY KEY (singleton),
    CONSTRAINT auth_secret_contract_singleton_check CHECK (singleton),
    CONSTRAINT auth_secret_contract_secret_fingerprint_check CHECK (
        secret_fingerprint ~ '^[0-9a-f]{64}$'::text
    )
);

CREATE TABLE auth.schema_contract (
    singleton boolean NOT NULL,
    schema_fingerprint text NOT NULL,
    CONSTRAINT schema_contract_pkey PRIMARY KEY (singleton),
    CONSTRAINT schema_contract_singleton_check CHECK (singleton),
    CONSTRAINT schema_contract_schema_fingerprint_check
        CHECK (schema_fingerprint ~ '^[0-9a-f]{64}$'::text)
);

CREATE FUNCTION auth.enforce_active_session_owner()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
BEGIN
    PERFORM 1
    FROM auth."user"
    WHERE id = NEW."userId" AND active = TRUE
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN NEW;
END;
$function$;

CREATE TRIGGER session_active_researcher_trigger
BEFORE INSERT ON auth."session"
FOR EACH ROW
EXECUTE FUNCTION auth.enforce_active_session_owner();

CREATE INDEX "session_userId_idx" ON auth."session" ("userId");
CREATE INDEX "account_userId_idx" ON auth."account" ("userId");
CREATE INDEX "verification_identifier_idx" ON auth."verification" ("identifier");
CREATE UNIQUE INDEX "account_issuer_accountId_uidx"
    ON auth."account" ("issuer", "accountId");
CREATE UNIQUE INDEX researcher_invitation_effective_email_uidx
    ON auth.researcher_invitation (email)
    WHERE status IN ('delivery_pending', 'delivered');
CREATE INDEX researcher_invitation_user_id_idx
    ON auth.researcher_invitation (user_id);
CREATE UNIQUE INDEX password_reset_effective_user_id_uidx
    ON auth.password_reset (user_id)
    WHERE status IN ('delivery_pending', 'delivered');
CREATE INDEX security_audit_occurred_at_idx
    ON auth.security_audit (occurred_at);
CREATE INDEX security_audit_researcher_id_idx
    ON auth.security_audit (researcher_id);
CREATE INDEX security_audit_unknown_email_hmac_idx
    ON auth.security_audit (unknown_email_hmac);
