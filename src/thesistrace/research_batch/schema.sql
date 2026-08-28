CREATE SCHEMA research_batches;

SET default_tablespace = '';
SET default_table_access_method = heap;

CREATE TABLE research_batches.batches (
    researcher_id uuid NOT NULL,
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
    CONSTRAINT batches_execution_fence_check CHECK (execution_fence >= 0),
    UNIQUE (researcher_id, id),
    FOREIGN KEY (researcher_id) REFERENCES researchers.researchers(id)
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
    child_pid integer NOT NULL,
    child_control_path text NOT NULL,
    child_started_at timestamp with time zone NOT NULL,
    child_exited_at timestamp with time zone,
    child_exit_code integer,
    child_acknowledged boolean,
    CONSTRAINT attempts_ordinal_check CHECK (ordinal > 0),
    CONSTRAINT attempts_fence_check CHECK (fence > 0),
    CONSTRAINT attempts_child_check CHECK (
        child_pid > 0
        AND child_control_path = btrim(child_control_path)
        AND child_control_path <> ''
        AND (
            (child_exited_at IS NULL AND child_exit_code IS NULL AND child_acknowledged IS NULL)
            OR (child_exited_at IS NOT NULL AND child_exit_code IS NOT NULL AND child_acknowledged IS NOT NULL)
        )
    ),
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
    UNIQUE (id, batch_id, fence),
    FOREIGN KEY (batch_id) REFERENCES research_batches.batches(id) ON DELETE CASCADE
);

CREATE TABLE research_batches.starting_claims (
    id text PRIMARY KEY,
    batch_id text NOT NULL UNIQUE,
    ordinal integer NOT NULL,
    fence integer NOT NULL,
    generation_pin_id text NOT NULL UNIQUE,
    data_generation_id text NOT NULL,
    data_through_session date NOT NULL,
    child_control_path text NOT NULL,
    heartbeat_at timestamp with time zone DEFAULT now() NOT NULL,
    lease_expires_at timestamp with time zone NOT NULL,
    CONSTRAINT starting_claims_ordinal_check CHECK (ordinal > 0),
    CONSTRAINT starting_claims_fence_check CHECK (fence > 0),
    CONSTRAINT starting_claims_child_control_path_check CHECK (
        child_control_path = btrim(child_control_path) AND child_control_path <> ''
    ),
    UNIQUE (id, batch_id, fence),
    FOREIGN KEY (batch_id) REFERENCES research_batches.batches(id) ON DELETE CASCADE
);

CREATE TABLE research_batches.items (
    researcher_id uuid NOT NULL,
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
    FOREIGN KEY (researcher_id, batch_id)
        REFERENCES research_batches.batches(researcher_id, id) ON DELETE CASCADE,
    FOREIGN KEY (researcher_id, research_run_id)
        REFERENCES research_runs.run_ownership(researcher_id, run_id)
);

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
    CONSTRAINT task_attempts_item_ordinal_check CHECK (
        item_ordinal IS NULL OR item_ordinal > 0
    ),
    CONSTRAINT task_attempts_key_check CHECK (
        task_key = btrim(task_key) AND task_key <> ''
    ),
    CONSTRAINT task_attempts_role_check CHECK (
        (task_role = 'shared_alpha_factor' AND item_ordinal IS NULL)
        OR (
            task_role = ANY (ARRAY['factor'::text, 'strategy'::text])
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

CREATE TABLE research_batches.private_alpha_factor_artifacts (
    batch_id text PRIMARY KEY,
    manifest_sha256 text NOT NULL UNIQUE,
    binding_checksum text NOT NULL,
    binding jsonb NOT NULL,
    content_sha256 text NOT NULL,
    byte_size bigint NOT NULL,
    created_by_attempt_id text NOT NULL,
    created_by_fence integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT private_alpha_factor_artifacts_binding_check CHECK (
        jsonb_typeof(binding) = 'object'
    ),
    CONSTRAINT private_alpha_factor_artifacts_checksum_check CHECK (
        binding_checksum ~ '^[0-9a-f]{64}$'
        AND content_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT private_alpha_factor_artifacts_byte_size_check CHECK (byte_size > 0),
    CONSTRAINT private_alpha_factor_artifacts_fence_check CHECK (created_by_fence > 0),
    FOREIGN KEY (batch_id) REFERENCES research_batches.batches(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_attempt_id, batch_id, created_by_fence)
        REFERENCES research_batches.attempts(id, batch_id, fence) ON DELETE RESTRICT
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
            'failed'::text,
            'cancelled'::text
        ])
    ),
    FOREIGN KEY (batch_id) REFERENCES research_batches.batches(id) ON DELETE CASCADE
);

CREATE TABLE research_batches.admission_receipts (
    researcher_id uuid NOT NULL,
    request_id text NOT NULL,
    request_fingerprint text NOT NULL,
    batch_id text NOT NULL UNIQUE,
    outcome jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT admission_receipts_outcome_check CHECK (jsonb_typeof(outcome) = 'object'),
    PRIMARY KEY (researcher_id, request_id),
    FOREIGN KEY (researcher_id, batch_id)
        REFERENCES research_batches.batches(researcher_id, id)
);

CREATE TABLE research_batches.cancel_receipts (
    researcher_id uuid NOT NULL,
    request_id text NOT NULL,
    request_fingerprint text NOT NULL,
    batch_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    PRIMARY KEY (researcher_id, request_id),
    FOREIGN KEY (researcher_id, batch_id)
        REFERENCES research_batches.batches(researcher_id, id)
);

CREATE INDEX research_batches_created_idx
ON research_batches.batches (researcher_id, created_at DESC, id);

CREATE INDEX research_batch_attempts_claim_idx
ON research_batches.attempts (batch_id, ordinal DESC);

CREATE UNIQUE INDEX research_batch_task_attempts_running_idx
ON research_batches.task_attempts (batch_id)
WHERE status = 'running';
