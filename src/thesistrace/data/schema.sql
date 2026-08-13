--
-- Name: data; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA data;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: bootstrap_operations; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.bootstrap_operations (
    idempotency_key text NOT NULL,
    fingerprint text NOT NULL,
    status text NOT NULL,
    owner_token text NOT NULL,
    lease_expires_at timestamp with time zone NOT NULL,
    as_of timestamp with time zone NOT NULL,
    request_start date NOT NULL,
    request_end date NOT NULL,
    generation_manifest_sha256 text,
    data_through_session date,
    prepared_at timestamp with time zone,
    failure_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT bootstrap_operations_check CHECK ((request_start <= request_end)),
    CONSTRAINT bootstrap_operations_check1 CHECK ((((status = 'running'::text) AND (failure_code IS NULL)) OR ((status = 'succeeded'::text) AND (generation_manifest_sha256 IS NOT NULL) AND (data_through_session IS NOT NULL) AND (prepared_at IS NOT NULL) AND (failure_code IS NULL)) OR ((status = 'failed'::text) AND (failure_code IS NOT NULL)))),
    CONSTRAINT bootstrap_operations_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT bootstrap_operations_generation_manifest_sha256_check CHECK (((generation_manifest_sha256 IS NULL) OR (generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT bootstrap_operations_idempotency_key_check CHECK (((idempotency_key <> ''::text) AND (idempotency_key = btrim(idempotency_key)))),
    CONSTRAINT bootstrap_operations_owner_token_check CHECK (((owner_token <> ''::text) AND (owner_token = btrim(owner_token)))),
    CONSTRAINT bootstrap_operations_status_check CHECK ((status = ANY (ARRAY['running'::text, 'succeeded'::text, 'failed'::text])))
);


--
-- Name: collection_operations; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.collection_operations (
    idempotency_key text NOT NULL,
    plan_sha256 text NOT NULL,
    status text NOT NULL,
    target_count integer NOT NULL,
    deleted_count integer DEFAULT 0 NOT NULL,
    failure_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    CONSTRAINT collection_operations_check CHECK (((deleted_count >= 0) AND (deleted_count <= target_count))),
    CONSTRAINT collection_operations_check1 CHECK ((((status = 'running'::text) AND (failure_code IS NULL) AND (finished_at IS NULL)) OR ((status = 'succeeded'::text) AND (deleted_count = target_count) AND (failure_code IS NULL) AND (finished_at IS NOT NULL)) OR ((status = 'failed'::text) AND (failure_code IS NOT NULL) AND (finished_at IS NOT NULL)))),
    CONSTRAINT collection_operations_idempotency_key_check CHECK (((idempotency_key <> ''::text) AND (idempotency_key = btrim(idempotency_key)))),
    CONSTRAINT collection_operations_plan_sha256_check CHECK ((plan_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT collection_operations_status_check CHECK ((status = ANY (ARRAY['running'::text, 'succeeded'::text, 'failed'::text]))),
    CONSTRAINT collection_operations_target_count_check CHECK ((target_count >= 0))
);


--
-- Name: collection_roots; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.collection_roots (
    idempotency_key text NOT NULL,
    generation_manifest_sha256 text NOT NULL,
    CONSTRAINT collection_roots_generation_manifest_sha256_check CHECK ((generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))
);


--
-- Name: collection_targets; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.collection_targets (
    idempotency_key text NOT NULL,
    ordinal integer NOT NULL,
    file_kind text NOT NULL,
    sha256 text NOT NULL,
    status text NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT collection_targets_check CHECK ((((status = ANY (ARRAY['pending'::text, 'deleting'::text])) AND (deleted_at IS NULL)) OR ((status = 'deleted'::text) AND (deleted_at IS NOT NULL)))),
    CONSTRAINT collection_targets_file_kind_check CHECK ((file_kind = ANY (ARRAY['manifest'::text, 'object'::text, 'raw_financial'::text]))),
    CONSTRAINT collection_targets_ordinal_check CHECK ((ordinal >= 0)),
    CONSTRAINT collection_targets_sha256_check CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT collection_targets_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'deleting'::text, 'deleted'::text])))
);


--
-- Name: current_dataset_state; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.current_dataset_state (
    singleton smallint NOT NULL,
    last_market_refresh_at timestamp with time zone,
    last_financial_refresh_at timestamp with time zone,
    CONSTRAINT current_dataset_state_singleton_check CHECK ((singleton = 1))
);

INSERT INTO data.current_dataset_state (singleton) VALUES (1);


--
-- Name: financial_collection_operations; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.financial_collection_operations (
    idempotency_key text NOT NULL,
    fingerprint text NOT NULL,
    generation_manifest_sha256 text NOT NULL,
    capability_sha256 text NOT NULL,
    contract_descriptor jsonb NOT NULL,
    status text NOT NULL,
    target_count integer NOT NULL,
    completed_count integer DEFAULT 0 NOT NULL,
    failure_code text,
    failure_endpoint text,
    failure_instrument text,
    failure_shard text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    retention_released_at timestamp with time zone,
    CONSTRAINT financial_collection_operations_counts_check CHECK ((target_count >= 0) AND (completed_count >= 0) AND (completed_count <= target_count)),
    CONSTRAINT financial_collection_operations_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_collection_operations_generation_check CHECK ((generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_collection_operations_capability_check CHECK ((capability_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_collection_operations_key_check CHECK (((idempotency_key <> ''::text) AND (idempotency_key = btrim(idempotency_key)))),
    CONSTRAINT financial_collection_operations_retention_check CHECK (((retention_released_at IS NULL) OR (status = 'succeeded'::text))),
    CONSTRAINT financial_collection_operations_status_check CHECK ((status = ANY (ARRAY['running'::text, 'succeeded'::text, 'failed'::text]))),
    CONSTRAINT financial_collection_operations_state_check CHECK ((((status = 'running'::text) AND (failure_code IS NULL) AND (finished_at IS NULL)) OR ((status = 'succeeded'::text) AND (completed_count = target_count) AND (failure_code IS NULL) AND (finished_at IS NOT NULL)) OR ((status = 'failed'::text) AND (failure_code IS NOT NULL) AND (failure_endpoint IS NOT NULL) AND (failure_instrument IS NOT NULL) AND (failure_shard IS NOT NULL) AND (finished_at IS NOT NULL))))
);


--
-- Name: financial_refresh_operations; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.financial_refresh_operations (
    idempotency_key text NOT NULL,
    fingerprint text NOT NULL,
    generation_manifest_sha256 text NOT NULL,
    prior_candidate_manifest_sha256 text NOT NULL,
    observation_through_session date NOT NULL,
    status text NOT NULL,
    candidate_manifest_sha256 text,
    expected_shard_count integer,
    completed_shard_count integer,
    resumed_shard_count integer,
    failure_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    retention_released_at timestamp with time zone,
    publication_candidate_manifest_sha256 text,
    composed_generation_manifest_sha256 text,
    publication_prepared_at timestamp with time zone,
    publication_head_moved_at timestamp with time zone,
    published_generation_manifest_sha256 text,
    published_at timestamp with time zone,
    published_outcome jsonb,
    CONSTRAINT financial_refresh_operations_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_refresh_operations_generation_check CHECK ((generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_refresh_operations_prior_check CHECK ((prior_candidate_manifest_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_refresh_operations_candidate_check CHECK (((candidate_manifest_sha256 IS NULL) OR (candidate_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT financial_refresh_operations_publication_candidate_check CHECK (((publication_candidate_manifest_sha256 IS NULL) OR (publication_candidate_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT financial_refresh_operations_composed_generation_check CHECK (((composed_generation_manifest_sha256 IS NULL) OR (composed_generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT financial_refresh_operations_published_generation_check CHECK (((published_generation_manifest_sha256 IS NULL) OR (published_generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT financial_refresh_operations_publication_state_check CHECK (((published_generation_manifest_sha256 IS NULL) = (published_at IS NULL)) AND ((published_generation_manifest_sha256 IS NULL) = (published_outcome IS NULL))),
    CONSTRAINT financial_refresh_operations_key_check CHECK (((idempotency_key <> ''::text) AND (idempotency_key = btrim(idempotency_key)))),
    CONSTRAINT financial_refresh_operations_retention_check CHECK (((retention_released_at IS NULL) OR (status = 'succeeded'::text))),
    CONSTRAINT financial_refresh_operations_counts_check CHECK (((expected_shard_count IS NULL) OR ((expected_shard_count >= 0) AND (completed_shard_count >= 0) AND (completed_shard_count <= expected_shard_count) AND (resumed_shard_count >= 0) AND (resumed_shard_count <= completed_shard_count)))),
    CONSTRAINT financial_refresh_operations_status_check CHECK ((status = ANY (ARRAY['running'::text, 'succeeded'::text, 'failed'::text]))),
    CONSTRAINT financial_refresh_operations_state_check CHECK ((((status = 'running'::text) AND (candidate_manifest_sha256 IS NULL) AND (failure_code IS NULL) AND (finished_at IS NULL)) OR ((status = 'succeeded'::text) AND (candidate_manifest_sha256 IS NOT NULL) AND (expected_shard_count IS NOT NULL) AND (completed_shard_count IS NOT NULL) AND (resumed_shard_count IS NOT NULL) AND (expected_shard_count = completed_shard_count) AND (failure_code IS NULL) AND (finished_at IS NOT NULL)) OR ((status = 'failed'::text) AND (candidate_manifest_sha256 IS NULL) AND (failure_code IS NOT NULL) AND (finished_at IS NOT NULL))))
);


--
-- Name: financial_raw_batches; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.financial_raw_batches (
    batch_sha256 text NOT NULL,
    payload_sha256 text NOT NULL,
    endpoint text NOT NULL,
    parameters jsonb NOT NULL,
    returned_fields jsonb NOT NULL,
    row_count integer NOT NULL,
    source_date_start text,
    source_date_end text,
    byte_count integer NOT NULL,
    first_collected_at timestamp with time zone NOT NULL,
    CONSTRAINT financial_raw_batches_batch_check CHECK ((batch_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_raw_batches_payload_check CHECK ((payload_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_raw_batches_endpoint_check CHECK ((endpoint = ANY (ARRAY['income'::text, 'balancesheet'::text, 'cashflow'::text]))),
    CONSTRAINT financial_raw_batches_counts_check CHECK ((row_count >= 0) AND (byte_count > 0)),
    CONSTRAINT financial_raw_batches_extent_check CHECK (((source_date_start IS NULL) = (source_date_end IS NULL)))
);


--
-- Name: financial_collection_shards; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.financial_collection_shards (
    idempotency_key text NOT NULL,
    ordinal integer NOT NULL,
    endpoint text NOT NULL,
    instrument_id text NOT NULL,
    ts_code text NOT NULL,
    shard_name text NOT NULL,
    parameters jsonb NOT NULL,
    status text NOT NULL,
    batch_sha256 text,
    collected_at timestamp with time zone,
    CONSTRAINT financial_collection_shards_ordinal_check CHECK ((ordinal >= 0)),
    CONSTRAINT financial_collection_shards_endpoint_check CHECK ((endpoint = ANY (ARRAY['income'::text, 'balancesheet'::text, 'cashflow'::text]))),
    CONSTRAINT financial_collection_shards_identity_check CHECK ((instrument_id <> ''::text) AND (ts_code <> ''::text) AND (shard_name <> ''::text)),
    CONSTRAINT financial_collection_shards_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'completed'::text]))),
    CONSTRAINT financial_collection_shards_state_check CHECK ((((status = 'pending'::text) AND (batch_sha256 IS NULL) AND (collected_at IS NULL)) OR ((status = 'completed'::text) AND (batch_sha256 IS NOT NULL) AND (collected_at IS NOT NULL))))
);


--
-- Name: generation_candidates; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.generation_candidates (
    operation_id text NOT NULL,
    generation_manifest_sha256 text NOT NULL,
    status text NOT NULL,
    lease_expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    released_at timestamp with time zone,
    CONSTRAINT generation_candidates_check CHECK ((((status = 'live'::text) AND (released_at IS NULL)) OR ((status = 'released'::text) AND (released_at IS NOT NULL)))),
    CONSTRAINT generation_candidates_generation_manifest_sha256_check CHECK ((generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT generation_candidates_operation_id_check CHECK (((operation_id <> ''::text) AND (operation_id = btrim(operation_id)))),
    CONSTRAINT generation_candidates_status_check CHECK ((status = ANY (ARRAY['live'::text, 'released'::text])))
);


--
-- Name: generation_pins; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.generation_pins (
    id text NOT NULL,
    owner_kind text NOT NULL,
    owner_id text NOT NULL,
    generation_manifest_sha256 text NOT NULL,
    status text NOT NULL,
    lease_expires_at timestamp with time zone NOT NULL,
    heartbeat_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    released_at timestamp with time zone,
    CONSTRAINT generation_pins_check CHECK ((((status = 'active'::text) AND (released_at IS NULL)) OR ((status = ANY (ARRAY['released'::text, 'fenced'::text])) AND (released_at IS NOT NULL)))),
    CONSTRAINT generation_pins_generation_manifest_sha256_check CHECK ((generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT generation_pins_owner_id_check CHECK (((owner_id <> ''::text) AND (owner_id = btrim(owner_id)))),
    CONSTRAINT generation_pins_owner_kind_check CHECK ((owner_kind = ANY (ARRAY['research_run_attempt'::text, 'tracking_advance_attempt'::text]))),
    CONSTRAINT generation_pins_status_check CHECK ((status = ANY (ARRAY['active'::text, 'released'::text, 'fenced'::text])))
);


--
-- Name: refresh_operations; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.refresh_operations (
    idempotency_key text NOT NULL,
    fingerprint text NOT NULL,
    status text NOT NULL,
    owner_token text,
    lease_expires_at timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    outcome text,
    as_of timestamp with time zone NOT NULL,
    expected_generation_manifest_sha256 text,
    candidate_prepared_at timestamp with time zone,
    generation_manifest_sha256 text,
    data_through_session date,
    last_refresh_at timestamp with time zone,
    failure_code text,
    last_failure_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT refresh_operations_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT refresh_operations_check CHECK ((((status = 'accepted'::text) AND (owner_token IS NULL) AND (lease_expires_at IS NULL) AND (outcome IS NULL) AND (failure_code IS NULL)) OR ((status = 'running'::text) AND (outcome IS NULL) AND (owner_token IS NOT NULL) AND (lease_expires_at IS NOT NULL) AND (attempt_count > 0) AND (failure_code IS NULL) AND (started_at IS NOT NULL)) OR ((status = 'succeeded'::text) AND (outcome IS NOT NULL) AND (generation_manifest_sha256 IS NOT NULL) AND (data_through_session IS NOT NULL) AND (last_refresh_at IS NOT NULL) AND (failure_code IS NULL) AND (last_failure_code IS NULL) AND (finished_at IS NOT NULL)) OR ((status = 'failed'::text) AND (outcome IS NULL) AND (failure_code IS NOT NULL) AND (finished_at IS NOT NULL)))),
    CONSTRAINT refresh_operations_expected_generation_manifest_sha256_check CHECK (((expected_generation_manifest_sha256 IS NULL) OR (expected_generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT refresh_operations_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT refresh_operations_generation_manifest_sha256_check CHECK (((generation_manifest_sha256 IS NULL) OR (generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT refresh_operations_idempotency_key_check CHECK (((idempotency_key <> ''::text) AND (idempotency_key = btrim(idempotency_key)))),
    CONSTRAINT refresh_operations_outcome_check CHECK (((outcome IS NULL) OR (outcome = ANY (ARRAY['published'::text, 'no_change'::text])))),
    CONSTRAINT refresh_operations_owner_token_check CHECK (((owner_token IS NULL) OR ((owner_token <> ''::text) AND (owner_token = btrim(owner_token))))),
    CONSTRAINT refresh_operations_status_check CHECK ((status = ANY (ARRAY['accepted'::text, 'running'::text, 'succeeded'::text, 'failed'::text])))
);


--
-- Name: bootstrap_operations bootstrap_operations_pkey; Type: CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.bootstrap_operations
    ADD CONSTRAINT bootstrap_operations_pkey PRIMARY KEY (idempotency_key);


--
-- Name: collection_operations collection_operations_pkey; Type: CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.collection_operations
    ADD CONSTRAINT collection_operations_pkey PRIMARY KEY (idempotency_key);


--
-- Name: collection_roots collection_roots_pkey; Type: CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.collection_roots
    ADD CONSTRAINT collection_roots_pkey PRIMARY KEY (idempotency_key, generation_manifest_sha256);


--
-- Name: collection_targets collection_targets_idempotency_key_file_kind_sha256_key; Type: CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.collection_targets
    ADD CONSTRAINT collection_targets_idempotency_key_file_kind_sha256_key UNIQUE (idempotency_key, file_kind, sha256);


--
-- Name: collection_targets collection_targets_pkey; Type: CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.collection_targets
    ADD CONSTRAINT collection_targets_pkey PRIMARY KEY (idempotency_key, ordinal);


--
-- Name: current_dataset_state current_dataset_state_pkey; Type: CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.current_dataset_state
    ADD CONSTRAINT current_dataset_state_pkey PRIMARY KEY (singleton);


--
-- Name: generation_candidates generation_candidates_pkey; Type: CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.generation_candidates
    ADD CONSTRAINT generation_candidates_pkey PRIMARY KEY (operation_id);


ALTER TABLE ONLY data.financial_collection_operations
    ADD CONSTRAINT financial_collection_operations_pkey PRIMARY KEY (idempotency_key);


ALTER TABLE ONLY data.financial_refresh_operations
    ADD CONSTRAINT financial_refresh_operations_pkey PRIMARY KEY (idempotency_key);


ALTER TABLE ONLY data.financial_raw_batches
    ADD CONSTRAINT financial_raw_batches_pkey PRIMARY KEY (batch_sha256);


ALTER TABLE ONLY data.financial_collection_shards
    ADD CONSTRAINT financial_collection_shards_pkey PRIMARY KEY (idempotency_key, ordinal);


ALTER TABLE ONLY data.financial_collection_shards
    ADD CONSTRAINT financial_collection_shards_identity_key UNIQUE (idempotency_key, endpoint, instrument_id, shard_name);


--
-- Name: generation_pins generation_pins_owner_kind_owner_id_key; Type: CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.generation_pins
    ADD CONSTRAINT generation_pins_owner_kind_owner_id_key UNIQUE (owner_kind, owner_id);


--
-- Name: generation_pins generation_pins_pkey; Type: CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.generation_pins
    ADD CONSTRAINT generation_pins_pkey PRIMARY KEY (id);


--
-- Name: refresh_operations refresh_operations_pkey; Type: CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.refresh_operations
    ADD CONSTRAINT refresh_operations_pkey PRIMARY KEY (idempotency_key);


--
-- Name: data_active_generation_pins_idx; Type: INDEX; Schema: data; Owner: -
--

CREATE INDEX data_active_generation_pins_idx ON data.generation_pins USING btree (generation_manifest_sha256) WHERE (status = 'active'::text);


--
-- Name: data_live_generation_candidates_idx; Type: INDEX; Schema: data; Owner: -
--

CREATE INDEX data_live_generation_candidates_idx ON data.generation_candidates USING btree (generation_manifest_sha256) WHERE (status = 'live'::text);


--
-- Name: data_one_active_refresh_idx; Type: INDEX; Schema: data; Owner: -
--

CREATE UNIQUE INDEX data_one_active_refresh_idx ON data.refresh_operations USING btree ((true)) WHERE (status = ANY (ARRAY['accepted'::text, 'running'::text]));


--
-- Name: collection_roots collection_roots_idempotency_key_fkey; Type: FK CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.collection_roots
    ADD CONSTRAINT collection_roots_idempotency_key_fkey FOREIGN KEY (idempotency_key) REFERENCES data.collection_operations(idempotency_key) ON DELETE CASCADE;


--
-- Name: collection_targets collection_targets_idempotency_key_fkey; Type: FK CONSTRAINT; Schema: data; Owner: -
--

ALTER TABLE ONLY data.collection_targets
    ADD CONSTRAINT collection_targets_idempotency_key_fkey FOREIGN KEY (idempotency_key) REFERENCES data.collection_operations(idempotency_key) ON DELETE CASCADE;


ALTER TABLE ONLY data.financial_collection_shards
    ADD CONSTRAINT financial_collection_shards_operation_fkey FOREIGN KEY (idempotency_key) REFERENCES data.financial_collection_operations(idempotency_key) ON DELETE CASCADE;


ALTER TABLE ONLY data.financial_collection_shards
    ADD CONSTRAINT financial_collection_shards_batch_fkey FOREIGN KEY (batch_sha256) REFERENCES data.financial_raw_batches(batch_sha256);
