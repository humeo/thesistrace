CREATE SCHEMA research_batches;

SET default_tablespace = '';
SET default_table_access_method = heap;

CREATE TABLE research_batches.batches (
    id text PRIMARY KEY,
    batch_kind text NOT NULL,
    status text NOT NULL,
    scope jsonb NOT NULL,
    execution_fence integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT batches_kind_check CHECK (
        batch_kind = ANY (ARRAY['factor_evaluation'::text, 'strategy_sweep'::text])
    ),
    CONSTRAINT batches_status_check CHECK (
        status = ANY (ARRAY[
            'queued'::text,
            'running'::text,
            'cancelling'::text,
            'succeeded'::text,
            'completed_with_failures'::text,
            'failed'::text,
            'cancelled'::text
        ])
    ),
    CONSTRAINT batches_scope_check CHECK (jsonb_typeof(scope) = 'object'),
    CONSTRAINT batches_execution_fence_check CHECK (execution_fence >= 0)
);

CREATE TABLE research_batches.attempts (
    id text PRIMARY KEY,
    batch_id text NOT NULL,
    ordinal integer NOT NULL,
    fence integer NOT NULL,
    generation_pin_id text NOT NULL,
    data_generation_id text NOT NULL,
    data_through_session date NOT NULL,
    status text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    heartbeat_at timestamp with time zone DEFAULT now() NOT NULL,
    lease_expires_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    failure_reason text,
    CONSTRAINT attempts_ordinal_check CHECK (ordinal > 0),
    CONSTRAINT attempts_fence_check CHECK (fence > 0),
    CONSTRAINT attempts_status_check CHECK (
        status = ANY (ARRAY[
            'running'::text,
            'succeeded'::text,
            'failed'::text,
            'cancelled'::text
        ])
    ),
    UNIQUE (batch_id, ordinal),
    UNIQUE (generation_pin_id),
    FOREIGN KEY (batch_id) REFERENCES research_batches.batches(id) ON DELETE CASCADE
);

CREATE TABLE research_batches.items (
    batch_id text NOT NULL,
    ordinal integer NOT NULL,
    item_key text NOT NULL,
    research_run_id text NOT NULL,
    dependency_role text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT items_ordinal_check CHECK (ordinal > 0),
    CONSTRAINT items_key_check CHECK (item_key = btrim(item_key) AND item_key <> ''),
    CONSTRAINT items_dependency_role_check CHECK (
        dependency_role = ANY (ARRAY['factor'::text, 'strategy'::text])
    ),
    PRIMARY KEY (batch_id, ordinal),
    UNIQUE (batch_id, item_key),
    UNIQUE (research_run_id),
    FOREIGN KEY (batch_id) REFERENCES research_batches.batches(id) ON DELETE CASCADE
);

CREATE TABLE research_batches.progress (
    batch_id text PRIMARY KEY,
    completed_items integer DEFAULT 0 NOT NULL,
    total_items integer NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT progress_counts_check CHECK (
        completed_items >= 0
        AND completed_items <= total_items
        AND total_items > 0
        AND total_items <= 20
    ),
    FOREIGN KEY (batch_id) REFERENCES research_batches.batches(id) ON DELETE CASCADE
);

CREATE TABLE research_batches.admission_receipts (
    request_id text PRIMARY KEY,
    request_fingerprint text NOT NULL,
    batch_id text NOT NULL UNIQUE,
    outcome jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT admission_receipts_outcome_check CHECK (jsonb_typeof(outcome) = 'object'),
    FOREIGN KEY (batch_id) REFERENCES research_batches.batches(id)
);

CREATE INDEX research_batches_created_idx
ON research_batches.batches (created_at DESC, id);

CREATE INDEX research_batch_attempts_claim_idx
ON research_batches.attempts (batch_id, ordinal DESC);
