-- Frozen target tables for the explicit 0009 execution timing migration.


CREATE TABLE research_runs.attempts (
    id text NOT NULL,
    run_id text NOT NULL,
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
    processing_seconds double precision,
    processing_chunk_ordinal integer DEFAULT 0 NOT NULL,
    CONSTRAINT attempts_processing_check CHECK (
        (processing_seconds IS NULL OR (processing_seconds >= 0 AND processing_seconds < 'Infinity'::float8))
        AND processing_chunk_ordinal >= 0
    ),
    CONSTRAINT attempts_fence_check CHECK ((fence > 0)),
    CONSTRAINT attempts_ordinal_check CHECK ((ordinal > 0)),
    CONSTRAINT attempts_status_check CHECK ((status = ANY (ARRAY['running'::text, 'cancelling'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text])))
);

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_generation_pin_id_key UNIQUE (generation_pin_id);

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_run_id_ordinal_key UNIQUE (run_id, ordinal);

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_run_id_id_key UNIQUE (run_id, id);

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_run_id_fkey FOREIGN KEY (run_id) REFERENCES research_runs.runs(id);

CREATE TABLE research_batches.task_attempts (
    id text PRIMARY KEY,
    batch_id text NOT NULL,
    item_ordinal integer,
    task_key text NOT NULL,
    task_role text NOT NULL,
    ordinal integer NOT NULL,
    batch_attempt_id text NOT NULL,
    fence integer NOT NULL,
    status text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    failure_reason text,
    failure_diagnostic jsonb,
    live_completed_sessions integer,
    live_total_sessions integer,
    processing_seconds double precision,
    CONSTRAINT task_attempts_processing_check CHECK (
        processing_seconds IS NULL OR (processing_seconds >= 0 AND processing_seconds < 'Infinity'::float8)
    ),
    CONSTRAINT task_attempts_live_sessions_check CHECK (
        (live_completed_sessions IS NULL AND live_total_sessions IS NULL)
        OR (live_completed_sessions IS NOT NULL AND live_total_sessions IS NOT NULL
            AND live_completed_sessions >= 0 AND live_total_sessions > 0
            AND live_completed_sessions <= live_total_sessions)
    ),
    CONSTRAINT task_attempts_item_ordinal_check CHECK (
        item_ordinal IS NULL OR item_ordinal > 0
    ),
    CONSTRAINT task_attempts_key_check CHECK (
        task_key = btrim(task_key) AND task_key <> ''
    ),
    CONSTRAINT task_attempts_role_check CHECK (
        (task_role = 'shared_alpha_factor' AND item_ordinal IS NULL)
        OR (
            task_role = ANY (ARRAY['factor'::text, 'strategy'::text, 'independent_strategy'::text])
            AND item_ordinal IS NOT NULL
        )
    ),
    CONSTRAINT task_attempts_ordinal_check CHECK (
        ordinal > 0 AND ordinal <= 3
    ),
    CONSTRAINT task_attempts_fence_check CHECK (fence > 0),
    CONSTRAINT task_attempts_status_check CHECK (
        status = ANY (ARRAY[
            'running'::text,
            'succeeded'::text,
            'failed'::text,
            'cancelled'::text
        ])
    ),
    CONSTRAINT task_attempts_failure_diagnostic_check CHECK (
        failure_diagnostic IS NULL OR jsonb_typeof(failure_diagnostic) = 'object'
    ),
    CONSTRAINT task_attempts_lifecycle_check CHECK ((
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
    ) IS TRUE),
    UNIQUE (batch_id, task_role, task_key, ordinal),
    FOREIGN KEY (batch_id, item_ordinal)
        REFERENCES research_batches.items(batch_id, ordinal) ON DELETE CASCADE,
    FOREIGN KEY (batch_attempt_id, batch_id, fence)
        REFERENCES research_batches.attempts(id, batch_id, fence) ON DELETE CASCADE
);
