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

CREATE TABLE auth.operator_proof (
    id uuid DEFAULT pg_catalog.gen_random_uuid() NOT NULL,
    token_hash bytea NOT NULL,
    session_id uuid NOT NULL,
    operation text NOT NULL,
    request_hash bytea NOT NULL,
    state text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    claimed_at timestamp with time zone,
    consumed_at timestamp with time zone,
    CONSTRAINT operator_proof_pkey PRIMARY KEY (id),
    CONSTRAINT operator_proof_token_hash_key UNIQUE (token_hash),
    CONSTRAINT operator_proof_session_id_fkey FOREIGN KEY (session_id)
        REFERENCES auth."session" (id) ON DELETE CASCADE,
    CONSTRAINT operator_proof_token_hash_check CHECK (
        pg_catalog.octet_length(token_hash) = 32
    ),
    CONSTRAINT operator_proof_request_hash_check CHECK (
        pg_catalog.octet_length(request_hash) = 32
    ),
    CONSTRAINT operator_proof_operation_check CHECK (
        operation = ANY (ARRAY[
            'invitation.issue'::text,
            'invitation.reissue'::text,
            'researcher.sessions.revoke'::text,
            'data.refresh.market.submit'::text,
            'data.refresh.financial.submit'::text,
            'data.refresh.industry.submit'::text,
            'data.refresh.cancel'::text,
            'data.refresh.retry'::text
        ])
    ),
    CONSTRAINT operator_proof_state_check CHECK (
        state = ANY (ARRAY[
            'available'::text,
            'claimed'::text,
            'consumed'::text
        ])
    ),
    CONSTRAINT operator_proof_expiry_check CHECK (expires_at > created_at),
    CONSTRAINT operator_proof_lifecycle_check CHECK (
        (state = 'available' AND claimed_at IS NULL AND consumed_at IS NULL)
        OR (state = 'claimed' AND claimed_at IS NOT NULL
            AND consumed_at IS NULL)
        OR (state = 'consumed' AND claimed_at IS NOT NULL
            AND consumed_at IS NOT NULL)
    )
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
            'replacement_pending'::text,
            'delivered'::text,
            'delivery_failed'::text,
            'consumed'::text,
            'revoked'::text
        ])
    ),
    CONSTRAINT researcher_invitation_lifecycle_check CHECK (
        (status = 'delivery_pending' AND delivered_at IS NULL
            AND terminal_at IS NULL AND user_id IS NULL)
        OR (status = 'replacement_pending' AND delivered_at IS NULL
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
CREATE INDEX operator_proof_session_id_idx
    ON auth.operator_proof (session_id);
CREATE INDEX operator_proof_expires_at_idx
    ON auth.operator_proof (expires_at);
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

-- OAuth provider 1.7.2: current schema, installed only into an empty auth scope.

CREATE TABLE auth."oauthClient" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() PRIMARY KEY,
    "clientId" text NOT NULL UNIQUE,
    "clientSecret" text,
    "clientDiscoveryId" text,
    "disabled" boolean,
    "skipConsent" boolean,
    "enableEndSession" boolean,
    "subjectType" text,
    "scopes" jsonb,
    "clientCredentialsScopes" jsonb,
    "userId" uuid REFERENCES auth."user" ("id") ON DELETE CASCADE,
    "createdAt" timestamp with time zone,
    "updatedAt" timestamp with time zone,
    "name" text,
    "uri" text,
    "icon" text,
    "contacts" jsonb,
    "tos" text,
    "policy" text,
    "softwareId" text,
    "softwareVersion" text,
    "softwareStatement" text,
    "redirectUris" jsonb NOT NULL,
    "postLogoutRedirectUris" jsonb,
    "backchannelLogoutUri" text,
    "backchannelLogoutSessionRequired" boolean,
    "tokenEndpointAuthMethod" text,
    "applicationType" text,
    "jwks" text,
    "jwksUri" text,
    "grantTypes" jsonb,
    "responseTypes" jsonb,
    "requirePKCE" boolean,
    "dpopBoundAccessTokens" boolean,
    "referenceId" text,
    "metadata" jsonb
);
CREATE INDEX "oauthClient_userId_idx" ON auth."oauthClient" ("userId");

CREATE TABLE auth."oauthResource" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() PRIMARY KEY,
    "identifier" text NOT NULL UNIQUE,
    "name" text NOT NULL,
    "accessTokenTtl" integer,
    "refreshTokenTtl" integer,
    "signingAlgorithm" text,
    "signingKeyId" text,
    "allowedScopes" jsonb,
    "customClaims" jsonb,
    "dpopBoundAccessTokensRequired" boolean,
    "disabled" boolean,
    "createdAt" timestamp with time zone,
    "updatedAt" timestamp with time zone,
    "policyVersion" integer,
    "metadata" jsonb
);


CREATE TABLE auth."oauthClientResource" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() PRIMARY KEY,
    "clientId" text NOT NULL REFERENCES auth."oauthClient" ("clientId") ON DELETE CASCADE,
    "resourceId" text NOT NULL REFERENCES auth."oauthResource" ("identifier") ON DELETE CASCADE,
    "metadata" jsonb,
    "createdAt" timestamp with time zone
);
CREATE INDEX "oauthClientResource_clientId_idx" ON auth."oauthClientResource" ("clientId");
CREATE INDEX "oauthClientResource_resourceId_idx" ON auth."oauthClientResource" ("resourceId");

CREATE TABLE auth."oauthRefreshToken" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() PRIMARY KEY,
    "token" text NOT NULL UNIQUE,
    "clientId" text NOT NULL REFERENCES auth."oauthClient" ("clientId") ON DELETE CASCADE,
    "sessionId" uuid REFERENCES auth."session" ("id") ON DELETE SET NULL,
    "userId" uuid NOT NULL REFERENCES auth."user" ("id") ON DELETE CASCADE,
    "referenceId" text,
    "authorizationCodeId" text,
    "resources" jsonb,
    "requestedUserInfoClaims" jsonb,
    "expiresAt" timestamp with time zone NOT NULL,
    "createdAt" timestamp with time zone NOT NULL,
    "revoked" timestamp with time zone,
    "rotatedAt" timestamp with time zone,
    "rotationReplayResponse" text,
    "rotationReplayExpiresAt" timestamp with time zone,
    "authTime" timestamp with time zone,
    "confirmation" jsonb,
    "scopes" jsonb NOT NULL
);
CREATE INDEX "oauthRefreshToken_clientId_idx" ON auth."oauthRefreshToken" ("clientId");
CREATE INDEX "oauthRefreshToken_sessionId_idx" ON auth."oauthRefreshToken" ("sessionId");
CREATE INDEX "oauthRefreshToken_userId_idx" ON auth."oauthRefreshToken" ("userId");
CREATE INDEX "oauthRefreshToken_authorizationCodeId_idx" ON auth."oauthRefreshToken" ("authorizationCodeId");

CREATE TABLE auth."oauthAccessToken" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() PRIMARY KEY,
    "token" text NOT NULL UNIQUE,
    "clientId" text NOT NULL REFERENCES auth."oauthClient" ("clientId") ON DELETE CASCADE,
    "sessionId" uuid REFERENCES auth."session" ("id") ON DELETE SET NULL,
    "userId" uuid REFERENCES auth."user" ("id") ON DELETE CASCADE,
    "referenceId" text,
    "authorizationCodeId" text,
    "resources" jsonb,
    "requestedUserInfoClaims" jsonb,
    "refreshId" uuid REFERENCES auth."oauthRefreshToken" ("id") ON DELETE CASCADE,
    "expiresAt" timestamp with time zone NOT NULL,
    "createdAt" timestamp with time zone NOT NULL,
    "revoked" timestamp with time zone,
    "confirmation" jsonb,
    "scopes" jsonb NOT NULL
);
CREATE INDEX "oauthAccessToken_clientId_idx" ON auth."oauthAccessToken" ("clientId");
CREATE INDEX "oauthAccessToken_sessionId_idx" ON auth."oauthAccessToken" ("sessionId");
CREATE INDEX "oauthAccessToken_userId_idx" ON auth."oauthAccessToken" ("userId");
CREATE INDEX "oauthAccessToken_authorizationCodeId_idx" ON auth."oauthAccessToken" ("authorizationCodeId");
CREATE INDEX "oauthAccessToken_refreshId_idx" ON auth."oauthAccessToken" ("refreshId");

CREATE TABLE auth."oauthConsent" (
    "id" uuid DEFAULT pg_catalog.gen_random_uuid() PRIMARY KEY,
    "clientId" text NOT NULL REFERENCES auth."oauthClient" ("clientId") ON DELETE CASCADE,
    "userId" uuid REFERENCES auth."user" ("id") ON DELETE CASCADE,
    "referenceId" text,
    "resources" jsonb,
    "requestedUserInfoClaims" jsonb,
    "scopes" jsonb NOT NULL,
    "createdAt" timestamp with time zone NOT NULL,
    "updatedAt" timestamp with time zone NOT NULL
);
CREATE INDEX "oauthConsent_clientId_idx" ON auth."oauthConsent" ("clientId");
CREATE INDEX "oauthConsent_userId_idx" ON auth."oauthConsent" ("userId");

CREATE TABLE auth."oauthClientAssertion" (
    "id" text PRIMARY KEY,
    "expiresAt" timestamp with time zone NOT NULL
);
