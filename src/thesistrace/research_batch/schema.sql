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
    failure_diagnostic jsonb,
    current_task_role text,
    current_item_key text,
    current_phase text,
    completed_research_sessions integer,
    total_research_sessions integer,
    task_started_at timestamp with time zone,
    live_progress_updated_at timestamp with time zone,
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
    CONSTRAINT attempts_failure_diagnostic_check CHECK (
        failure_diagnostic IS NULL OR jsonb_typeof(failure_diagnostic) = 'object'
    ),
    CONSTRAINT attempts_lifecycle_check CHECK (
        (
            status = 'running'
            AND finished_at IS NULL
            AND failure_reason IS NULL
            AND failure_diagnostic IS NULL
        )
        OR (
            status = 'succeeded'
            AND finished_at IS NOT NULL
            AND failure_reason IS NULL
            AND failure_diagnostic IS NULL
        )
        OR (
            status = 'failed'
            AND finished_at IS NOT NULL
            AND failure_reason IS NOT NULL
            AND failure_diagnostic IS NOT NULL
        )
        OR (
            status = 'cancelled'
            AND finished_at IS NOT NULL
            AND failure_reason IS NULL
            AND failure_diagnostic IS NULL
        )
    ),
    CONSTRAINT attempts_live_progress_check CHECK (
        (
            current_task_role IS NULL
            AND current_item_key IS NULL
            AND current_phase IS NULL
            AND completed_research_sessions IS NULL
            AND total_research_sessions IS NULL
            AND task_started_at IS NULL
            AND live_progress_updated_at IS NULL
        )
        OR (
            status = 'running'
            AND
            current_task_role = ANY (ARRAY[
                'preparation'::text,
                'factor'::text,
                'shared_alpha_factor'::text,
                'strategy'::text
            ])
            AND current_phase = ANY (ARRAY[
                'preparing_data'::text,
                'warmup'::text,
                'research'::text,
                'strategy'::text,
                'finalizing'::text
            ])
            AND (completed_research_sessions IS NULL) =
                (total_research_sessions IS NULL)
            AND (
                completed_research_sessions IS NULL
                OR (
                    completed_research_sessions >= 0
                    AND completed_research_sessions <= total_research_sessions
                    AND total_research_sessions > 0
                )
            )
            AND task_started_at IS NOT NULL
            AND live_progress_updated_at IS NOT NULL
        )
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
    outcome text,
    diagnostic jsonb,
    run_deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT items_ordinal_check CHECK (ordinal > 0),
    CONSTRAINT items_key_check CHECK (item_key = btrim(item_key) AND item_key <> ''),
    CONSTRAINT items_dependency_role_check CHECK (
        dependency_role = ANY (ARRAY['factor'::text, 'strategy'::text])
    ),
    CONSTRAINT items_outcome_check CHECK (
        outcome IS NULL OR outcome = ANY (ARRAY[
            'succeeded'::text,
            'failed'::text,
            'cancelled'::text
        ])
    ),
    CONSTRAINT items_diagnostic_check CHECK (
        diagnostic IS NULL OR jsonb_typeof(diagnostic) = 'object'
    ),
    CONSTRAINT items_outcome_diagnostic_check CHECK ((
        (outcome IS NULL AND diagnostic IS NULL AND run_deleted_at IS NULL)
        OR (outcome = 'succeeded' AND diagnostic IS NULL)
        OR (outcome = 'failed' AND diagnostic IS NOT NULL)
        OR outcome = 'cancelled'
    ) IS TRUE),
    CONSTRAINT items_deletion_terminal_check CHECK (
        run_deleted_at IS NULL OR outcome IS NOT NULL
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
    shared_alpha_factor_status text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT progress_counts_check CHECK (
        completed_items >= 0
        AND completed_items <= total_items
        AND total_items > 0
        AND total_items <= 20
    ),
    CONSTRAINT progress_shared_status_check CHECK (
        shared_alpha_factor_status IS NULL
        OR shared_alpha_factor_status = ANY (ARRAY[
            'pending'::text,
            'running'::text,
            'succeeded'::text,
            'failed'::text
        ])
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
