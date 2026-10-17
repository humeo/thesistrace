
-- Billing subscriptions: paid rights remain associated with supporting transactions.
CREATE TABLE auth.billing_account (
    researcher_id uuid PRIMARY KEY REFERENCES auth."user"(id),
    customer_id text UNIQUE,
    subscription_id text UNIQUE,
    checkout_request_id uuid NOT NULL UNIQUE DEFAULT pg_catalog.gen_random_uuid(),
    checkout_plan text CHECK (checkout_plan IN ('pro','max')),
    checkout_id text UNIQUE,
    checkout_url text,
    provider_status text,
    renewal_plan text CHECK (renewal_plan IN ('pro','max')),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE auth.billing_payment (
    transaction_id text PRIMARY KEY,
    researcher_id uuid NOT NULL REFERENCES auth."user"(id),
    subscription_id text NOT NULL,
    plan_key text NOT NULL CHECK (plan_key IN ('pro','max')),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    amount integer NOT NULL CHECK (amount > 0),
    refunded_amount integer NOT NULL DEFAULT 0 CHECK (refunded_amount >= 0 AND refunded_amount <= amount),
    disputed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (ends_at > starts_at)
);
CREATE INDEX billing_payment_researcher_period ON auth.billing_payment(researcher_id,ends_at);
CREATE TABLE auth.billing_adjustment (
    transaction_id text PRIMARY KEY,
    refunded_amount integer NOT NULL DEFAULT 0 CHECK (refunded_amount >= 0),
    disputed boolean NOT NULL DEFAULT false,
    dispute_resolved_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE auth.billing_event (
    id text PRIMARY KEY,
    event_type text NOT NULL,
    raw_body text NOT NULL,
    body_sha256 bytea NOT NULL CHECK (octet_length(body_sha256) = 32),
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    failure_code text
);
CREATE INDEX billing_event_pending ON auth.billing_event(received_at) WHERE processed_at IS NULL;

CREATE TABLE auth.billing_command (
    id uuid PRIMARY KEY,
    researcher_id uuid NOT NULL REFERENCES auth."user"(id),
    kind text NOT NULL CHECK (kind IN ('checkout','change','cancel')),
    plan_key text CHECK (plan_key IN ('pro','max')),
    status text NOT NULL CHECK (status IN ('prepared','dispatched','completed','uncertain')),
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind = 'cancel') = (plan_key IS NULL))
);
CREATE UNIQUE INDEX billing_command_open_per_researcher ON auth.billing_command(researcher_id)
    WHERE status IN ('prepared','dispatched','uncertain');
