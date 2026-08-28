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

CREATE TABLE auth.schema_contract (
    singleton boolean NOT NULL,
    schema_fingerprint text NOT NULL,
    CONSTRAINT schema_contract_pkey PRIMARY KEY (singleton),
    CONSTRAINT schema_contract_singleton_check CHECK (singleton),
    CONSTRAINT schema_contract_schema_fingerprint_check
        CHECK (schema_fingerprint ~ '^[0-9a-f]{64}$'::text)
);

CREATE INDEX "session_userId_idx" ON auth."session" ("userId");
CREATE INDEX "account_userId_idx" ON auth."account" ("userId");
CREATE INDEX "verification_identifier_idx" ON auth."verification" ("identifier");
CREATE UNIQUE INDEX "account_issuer_accountId_uidx"
    ON auth."account" ("issuer", "accountId");
