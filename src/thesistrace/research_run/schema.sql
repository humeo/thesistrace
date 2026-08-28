--
-- Name: research_runs; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA research_runs;


SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE TABLE research_runs.run_ownership (
    researcher_id uuid NOT NULL,
    run_id text PRIMARY KEY,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    UNIQUE (researcher_id, run_id),
    FOREIGN KEY (researcher_id) REFERENCES researchers.researchers(id)
);

--
-- Name: attempts; Type: TABLE; Schema: research_runs; Owner: -
--

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
    CONSTRAINT attempts_fence_check CHECK ((fence > 0)),
    CONSTRAINT attempts_ordinal_check CHECK ((ordinal > 0)),
    CONSTRAINT attempts_status_check CHECK ((status = ANY (ARRAY['running'::text, 'cancelling'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text])))
);


--
-- Name: cancel_receipts; Type: TABLE; Schema: research_runs; Owner: -
--

CREATE TABLE research_runs.cancel_receipts (
    researcher_id uuid NOT NULL,
    request_id text NOT NULL,
    request_fingerprint text NOT NULL,
    run_id text NOT NULL,
    outcome jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT cancel_receipts_outcome_check CHECK ((jsonb_typeof(outcome) = 'object'::text))
);


--
-- Name: runs; Type: TABLE; Schema: research_runs; Owner: -
--

CREATE TABLE research_runs.runs (
    researcher_id uuid NOT NULL,
    id text NOT NULL,
    folder_id text NOT NULL,
    name text NOT NULL,
    requested_start_date date NOT NULL,
    requested_end_date date NOT NULL,
    status text NOT NULL,
    execution_owner text DEFAULT 'ordinary' NOT NULL,
    immutable_input jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    execution_fence integer DEFAULT 0 NOT NULL,
    result_manifest_sha256 text,
    result_provenance jsonb,
    key_metrics jsonb,
    failure_reason text,
    CONSTRAINT runs_check CHECK ((requested_start_date <= requested_end_date)),
    CONSTRAINT runs_name_check CHECK (name = btrim(name) AND name <> ''),
    CONSTRAINT runs_execution_fence_check CHECK ((execution_fence >= 0)),
    CONSTRAINT runs_execution_owner_check CHECK (
        execution_owner = ANY (ARRAY['ordinary'::text, 'research_batch'::text])
    ),
    CONSTRAINT runs_immutable_input_check CHECK (
        jsonb_typeof(immutable_input) = 'object'::text
        AND immutable_input ? 'research_kind'
        AND jsonb_typeof(immutable_input->'research_kind') = 'string'::text
        AND immutable_input->>'research_kind' IN ('factor_evaluation', 'strategy_backtest')
        AND (
            (
                immutable_input->>'research_kind' = 'factor_evaluation'
                AND NOT immutable_input ? 'strategy'
                AND NOT immutable_input ? 'costs'
                AND NOT immutable_input ? 'risk_free_rate'
            )
            OR (
                immutable_input->>'research_kind' = 'strategy_backtest'
                AND immutable_input ? 'strategy'
                AND jsonb_typeof(immutable_input->'strategy') = 'object'::text
                AND immutable_input ? 'costs'
                AND jsonb_typeof(immutable_input->'costs') = 'object'::text
                AND immutable_input ? 'risk_free_rate'
                AND jsonb_typeof(immutable_input->'risk_free_rate') = 'string'::text
            )
        )
    ),
    CONSTRAINT runs_result_provenance_check CHECK (((result_provenance IS NULL) OR (jsonb_typeof(result_provenance) = 'object'::text))),
    CONSTRAINT runs_key_metrics_check CHECK (
        key_metrics IS NULL
        OR (
            jsonb_typeof(key_metrics) = 'object'::text
            AND key_metrics->>'research_kind' = immutable_input->>'research_kind'
            AND (
                (
                    key_metrics->>'research_kind' = 'factor_evaluation'
                    AND key_metrics ?& ARRAY[
                        'one_session_rank_ic',
                        'five_session_rank_ic',
                        'twenty_session_rank_ic'
                    ]
                    AND key_metrics - ARRAY[
                        'research_kind',
                        'one_session_rank_ic',
                        'five_session_rank_ic',
                        'twenty_session_rank_ic'
                    ] = '{}'::jsonb
                )
                OR (
                    key_metrics->>'research_kind' = 'strategy_backtest'
                    AND key_metrics ?& ARRAY[
                        'annualized_excess_return',
                        'sharpe',
                        'maximum_drawdown'
                    ]
                    AND key_metrics - ARRAY[
                        'research_kind',
                        'annualized_excess_return',
                        'sharpe',
                        'maximum_drawdown'
                    ] = '{}'::jsonb
                )
            )
        )
    ),
    CONSTRAINT runs_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'cancelling'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text])))
);


CREATE TABLE research_runs.progress (
    run_id text NOT NULL,
    phase text NOT NULL,
    completed_warmup_sessions integer NOT NULL,
    total_warmup_sessions integer NOT NULL,
    completed_research_sessions integer NOT NULL,
    total_research_sessions integer NOT NULL,
    committed_chunk_count integer NOT NULL,
    last_completed_warmup_session date,
    last_completed_research_session date,
    remaining_duration_estimate_seconds integer,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT progress_phase_check CHECK ((phase = ANY (ARRAY['queued'::text, 'warmup'::text, 'research'::text, 'finalizing'::text, 'succeeded'::text]))),
    CONSTRAINT progress_counts_check CHECK (
        completed_warmup_sessions >= 0
        AND completed_warmup_sessions <= total_warmup_sessions
        AND completed_research_sessions >= 0
        AND completed_research_sessions <= total_research_sessions
        AND committed_chunk_count >= 0
    )
);


CREATE TABLE research_runs.execution_checkpoints (
    id text NOT NULL,
    run_id text NOT NULL,
    attempt_id text NOT NULL,
    ordinal integer NOT NULL,
    boundary_session date NOT NULL,
    phase text NOT NULL,
    completed_warmup_sessions integer NOT NULL,
    completed_research_sessions integer NOT NULL,
    continuation_payload jsonb NOT NULL,
    observation_payload jsonb,
    final_values_payload jsonb,
    observation_row_count integer NOT NULL,
    observation_first_session date,
    observation_last_session date,
    checkpoint_manifest_sha256 text NOT NULL,
    chain_sha256 text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT execution_checkpoints_ordinal_check CHECK (ordinal > 0),
    CONSTRAINT execution_checkpoints_phase_check CHECK ((phase = ANY (ARRAY['warmup'::text, 'research'::text]))),
    CONSTRAINT execution_checkpoints_counts_check CHECK (
        completed_warmup_sessions >= 0
        AND completed_research_sessions >= 0
        AND observation_row_count >= 0
    ),
    CONSTRAINT execution_checkpoints_continuation_check CHECK (jsonb_typeof(continuation_payload) = 'object'),
    CONSTRAINT execution_checkpoints_observation_check CHECK (observation_payload IS NULL OR jsonb_typeof(observation_payload) = 'object'),
    CONSTRAINT execution_checkpoints_final_values_check CHECK (final_values_payload IS NULL OR jsonb_typeof(final_values_payload) = 'object'),
    CONSTRAINT execution_checkpoints_manifest_check CHECK (checkpoint_manifest_sha256 ~ '^[0-9a-f]{64}$')
);


CREATE TABLE research_runs.admission_requests (
    researcher_id uuid NOT NULL,
    request_id text NOT NULL,
    request_fingerprint text NOT NULL,
    run_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: start_tracking_receipts; Type: TABLE; Schema: research_runs; Owner: -
--

CREATE TABLE research_runs.start_tracking_receipts (
    researcher_id uuid NOT NULL,
    request_id text NOT NULL,
    request_fingerprint text NOT NULL,
    seed_run_id text NOT NULL,
    track_id text NOT NULL,
    outcome jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT start_tracking_receipts_outcome_check CHECK ((jsonb_typeof(outcome) = 'object'::text))
);


--
-- Name: attempts attempts_generation_pin_id_key; Type: CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_generation_pin_id_key UNIQUE (generation_pin_id);


--
-- Name: attempts attempts_pkey; Type: CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_pkey PRIMARY KEY (id);


--
-- Name: attempts attempts_run_id_ordinal_key; Type: CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_run_id_ordinal_key UNIQUE (run_id, ordinal);

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_run_id_id_key UNIQUE (run_id, id);


--
-- Name: cancel_receipts cancel_receipts_pkey; Type: CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.cancel_receipts
    ADD CONSTRAINT cancel_receipts_pkey PRIMARY KEY (researcher_id, request_id);


ALTER TABLE ONLY research_runs.admission_requests
    ADD CONSTRAINT admission_requests_pkey PRIMARY KEY (researcher_id, request_id);

ALTER TABLE ONLY research_runs.admission_requests
    ADD CONSTRAINT admission_requests_run_id_key UNIQUE (run_id);


--
-- Name: runs runs_pkey; Type: CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.runs
    ADD CONSTRAINT runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY research_runs.runs
    ADD CONSTRAINT runs_researcher_id_id_key UNIQUE (researcher_id, id);

ALTER TABLE ONLY research_runs.progress
    ADD CONSTRAINT progress_pkey PRIMARY KEY (run_id);

ALTER TABLE ONLY research_runs.execution_checkpoints
    ADD CONSTRAINT execution_checkpoints_pkey PRIMARY KEY (id);

ALTER TABLE ONLY research_runs.execution_checkpoints
    ADD CONSTRAINT execution_checkpoints_run_id_ordinal_key UNIQUE (run_id, ordinal);


ALTER TABLE ONLY research_runs.runs
    ADD CONSTRAINT runs_ownership_fkey
    FOREIGN KEY (researcher_id, id)
    REFERENCES research_runs.run_ownership(researcher_id, run_id);

ALTER TABLE ONLY research_runs.runs
    ADD CONSTRAINT runs_folder_fkey
    FOREIGN KEY (researcher_id, folder_id)
    REFERENCES research_folders.folders(researcher_id, id);


--
-- Name: start_tracking_receipts start_tracking_receipts_pkey; Type: CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.start_tracking_receipts
    ADD CONSTRAINT start_tracking_receipts_pkey PRIMARY KEY (researcher_id, request_id);


--
-- Name: research_runs_one_running_attempt_idx; Type: INDEX; Schema: research_runs; Owner: -
--

CREATE UNIQUE INDEX research_runs_one_running_attempt_idx ON research_runs.attempts USING btree (run_id) WHERE (status = 'running'::text);


--
-- Name: research_runs_runs_created_idx; Type: INDEX; Schema: research_runs; Owner: -
--

CREATE INDEX research_runs_runs_created_idx ON research_runs.runs USING btree (researcher_id, created_at DESC, id);

CREATE INDEX research_runs_runs_folder_created_idx ON research_runs.runs USING btree (researcher_id, folder_id, created_at DESC, id);

CREATE INDEX research_runs_runs_kind_created_idx ON research_runs.runs USING btree (researcher_id, (immutable_input->>'research_kind'), created_at DESC, id);

CREATE INDEX research_runs_runs_folder_kind_created_idx ON research_runs.runs USING btree (researcher_id, folder_id, (immutable_input->>'research_kind'), created_at DESC, id);


--
-- Name: attempts attempts_run_id_fkey; Type: FK CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_run_id_fkey FOREIGN KEY (run_id) REFERENCES research_runs.runs(id);


ALTER TABLE ONLY research_runs.admission_requests
    ADD CONSTRAINT admission_requests_run_fkey
    FOREIGN KEY (researcher_id, run_id)
    REFERENCES research_runs.runs(researcher_id, id);

ALTER TABLE ONLY research_runs.cancel_receipts
    ADD CONSTRAINT cancel_receipts_run_fkey
    FOREIGN KEY (researcher_id, run_id)
    REFERENCES research_runs.runs(researcher_id, id);

ALTER TABLE ONLY research_runs.start_tracking_receipts
    ADD CONSTRAINT start_tracking_receipts_seed_run_fkey
    FOREIGN KEY (researcher_id, seed_run_id)
    REFERENCES research_runs.runs(researcher_id, id);

ALTER TABLE ONLY research_runs.progress
    ADD CONSTRAINT progress_run_id_fkey FOREIGN KEY (run_id) REFERENCES research_runs.runs(id) ON DELETE CASCADE;

ALTER TABLE ONLY research_runs.execution_checkpoints
    ADD CONSTRAINT execution_checkpoints_run_id_fkey FOREIGN KEY (run_id) REFERENCES research_runs.runs(id) ON DELETE CASCADE;

ALTER TABLE ONLY research_runs.execution_checkpoints
    ADD CONSTRAINT execution_checkpoints_run_attempt_fkey
    FOREIGN KEY (run_id, attempt_id)
    REFERENCES research_runs.attempts(run_id, id);
