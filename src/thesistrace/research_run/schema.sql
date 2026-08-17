--
-- Name: research_runs; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA research_runs;


SET default_tablespace = '';

SET default_table_access_method = heap;

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
    id text NOT NULL,
    folder_id text NOT NULL,
    name text NOT NULL,
    requested_start_date date NOT NULL,
    requested_end_date date NOT NULL,
    status text NOT NULL,
    immutable_input jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    execution_fence integer DEFAULT 0 NOT NULL,
    result_manifest_sha256 text,
    result_provenance jsonb,
    failure_reason text,
    CONSTRAINT runs_check CHECK ((requested_start_date <= requested_end_date)),
    CONSTRAINT runs_name_check CHECK (name = btrim(name) AND name <> ''),
    CONSTRAINT runs_execution_fence_check CHECK ((execution_fence >= 0)),
    CONSTRAINT runs_immutable_input_check CHECK ((jsonb_typeof(immutable_input) = 'object'::text)),
    CONSTRAINT runs_result_provenance_check CHECK (((result_provenance IS NULL) OR (jsonb_typeof(result_provenance) = 'object'::text))),
    CONSTRAINT runs_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'cancelling'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text])))
);


CREATE TABLE research_runs.admission_requests (
    request_id text NOT NULL,
    request_fingerprint text NOT NULL,
    run_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: start_tracking_receipts; Type: TABLE; Schema: research_runs; Owner: -
--

CREATE TABLE research_runs.start_tracking_receipts (
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


--
-- Name: cancel_receipts cancel_receipts_pkey; Type: CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.cancel_receipts
    ADD CONSTRAINT cancel_receipts_pkey PRIMARY KEY (request_id);


ALTER TABLE ONLY research_runs.admission_requests
    ADD CONSTRAINT admission_requests_pkey PRIMARY KEY (request_id);

ALTER TABLE ONLY research_runs.admission_requests
    ADD CONSTRAINT admission_requests_run_id_key UNIQUE (run_id);


--
-- Name: runs runs_pkey; Type: CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.runs
    ADD CONSTRAINT runs_pkey PRIMARY KEY (id);


ALTER TABLE ONLY research_runs.runs
    ADD CONSTRAINT runs_folder_id_fkey FOREIGN KEY (folder_id) REFERENCES research_folders.folders(id);


--
-- Name: start_tracking_receipts start_tracking_receipts_pkey; Type: CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.start_tracking_receipts
    ADD CONSTRAINT start_tracking_receipts_pkey PRIMARY KEY (request_id);


--
-- Name: research_runs_one_running_attempt_idx; Type: INDEX; Schema: research_runs; Owner: -
--

CREATE UNIQUE INDEX research_runs_one_running_attempt_idx ON research_runs.attempts USING btree (run_id) WHERE (status = 'running'::text);


--
-- Name: research_runs_runs_created_idx; Type: INDEX; Schema: research_runs; Owner: -
--

CREATE INDEX research_runs_runs_created_idx ON research_runs.runs USING btree (created_at DESC, id);

CREATE INDEX research_runs_runs_folder_created_idx ON research_runs.runs USING btree (folder_id, created_at DESC, id);


--
-- Name: attempts attempts_run_id_fkey; Type: FK CONSTRAINT; Schema: research_runs; Owner: -
--

ALTER TABLE ONLY research_runs.attempts
    ADD CONSTRAINT attempts_run_id_fkey FOREIGN KEY (run_id) REFERENCES research_runs.runs(id);


ALTER TABLE ONLY research_runs.admission_requests
    ADD CONSTRAINT admission_requests_run_id_fkey FOREIGN KEY (run_id) REFERENCES research_runs.runs(id);
