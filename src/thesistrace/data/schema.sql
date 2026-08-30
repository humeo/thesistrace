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
    last_industry_refresh_at timestamp with time zone,
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
    prior_candidate_manifest_sha256 text,
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
-- Name: financial_daily_refresh_operations; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.financial_daily_refresh_operations (
    idempotency_key text PRIMARY KEY,
    fingerprint text NOT NULL,
    source_generation_manifest_sha256 text NOT NULL,
    prior_financial_manifest_sha256 text NOT NULL,
    discovery_baseline_session date NOT NULL,
    prior_attempted_through_session date NOT NULL,
    prior_complete_through_session date NOT NULL,
    target_session date NOT NULL,
    discovery_start_date date,
    discovery_end_date date,
    discovery_evidence jsonb,
    source_lineage_sha256 text,
    status text NOT NULL,
    candidate_manifest_sha256 text,
    composed_generation_manifest_sha256 text,
    publication_prepared_at timestamp with time zone,
    publication_head_moved_at timestamp with time zone,
    published_generation_manifest_sha256 text,
    published_at timestamp with time zone,
    published_outcome jsonb,
    failure_code text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    retention_released_at timestamp with time zone,
    CONSTRAINT financial_daily_refresh_operations_key_check CHECK (((idempotency_key <> ''::text) AND (idempotency_key = btrim(idempotency_key)))),
    CONSTRAINT financial_daily_refresh_operations_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_daily_refresh_operations_source_generation_check CHECK ((source_generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_daily_refresh_operations_prior_financial_check CHECK ((prior_financial_manifest_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_daily_refresh_operations_lineage_check CHECK (((source_lineage_sha256 IS NULL) OR (source_lineage_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT financial_daily_refresh_operations_candidate_check CHECK (((candidate_manifest_sha256 IS NULL) OR (candidate_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT financial_daily_refresh_operations_composed_generation_check CHECK (((composed_generation_manifest_sha256 IS NULL) OR (composed_generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT financial_daily_refresh_operations_published_generation_check CHECK (((published_generation_manifest_sha256 IS NULL) OR (published_generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT financial_daily_refresh_operations_coordinates_check CHECK ((discovery_baseline_session <= prior_complete_through_session) AND (prior_complete_through_session <= prior_attempted_through_session) AND (prior_attempted_through_session <= target_session)),
    CONSTRAINT financial_daily_refresh_operations_discovery_check CHECK (((discovery_evidence IS NULL) = (source_lineage_sha256 IS NULL)) AND ((discovery_evidence IS NULL) = (discovery_start_date IS NULL)) AND ((discovery_evidence IS NULL) = (discovery_end_date IS NULL)) AND ((discovery_start_date IS NULL) OR (discovery_start_date <= discovery_end_date))),
    CONSTRAINT financial_daily_refresh_operations_status_check CHECK ((status = ANY (ARRAY['running'::text, 'succeeded'::text, 'succeeded_with_pending'::text, 'succeeded_with_gaps'::text, 'failed'::text]))),
    CONSTRAINT financial_daily_refresh_operations_publication_state_check CHECK (((composed_generation_manifest_sha256 IS NULL) = (publication_prepared_at IS NULL)) AND ((published_generation_manifest_sha256 IS NULL) = (published_at IS NULL)) AND ((published_generation_manifest_sha256 IS NULL) = (published_outcome IS NULL))),
    CONSTRAINT financial_daily_refresh_operations_state_check CHECK ((((status = 'running'::text) AND (published_generation_manifest_sha256 IS NULL) AND (failure_code IS NULL) AND (finished_at IS NULL)) OR ((status = ANY (ARRAY['succeeded'::text, 'succeeded_with_pending'::text, 'succeeded_with_gaps'::text])) AND (candidate_manifest_sha256 IS NOT NULL) AND (composed_generation_manifest_sha256 IS NOT NULL) AND (publication_prepared_at IS NOT NULL) AND (publication_head_moved_at IS NOT NULL) AND (published_generation_manifest_sha256 IS NOT NULL) AND (failure_code IS NULL) AND (finished_at IS NOT NULL)) OR ((status = 'failed'::text) AND (published_generation_manifest_sha256 IS NULL) AND (failure_code IS NOT NULL) AND (finished_at IS NOT NULL))))
);


--
-- Name: financial_discovery_gaps; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.financial_discovery_gaps (
    gap_id text PRIMARY KEY,
    category text NOT NULL,
    query_start_date date NOT NULL,
    query_end_date date NOT NULL,
    unresolved_from_date date NOT NULL,
    failure_code text NOT NULL,
    status text NOT NULL,
    first_seen_operation_key text NOT NULL REFERENCES data.financial_daily_refresh_operations(idempotency_key) ON DELETE CASCADE,
    last_seen_operation_key text NOT NULL,
    resolved_by_operation_key text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    resolved_at timestamp with time zone,
    CONSTRAINT financial_discovery_gaps_id_check CHECK ((gap_id ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_discovery_gaps_category_check CHECK ((category = ANY (ARRAY['年报'::text, '半年报'::text, '一季报'::text, '三季报'::text, '补充更正'::text]))),
    CONSTRAINT financial_discovery_gaps_range_check CHECK ((query_start_date <= unresolved_from_date) AND (unresolved_from_date <= query_end_date)),
    CONSTRAINT financial_discovery_gaps_status_check CHECK ((status = ANY (ARRAY['open'::text, 'resolved'::text]))),
    CONSTRAINT financial_discovery_gaps_state_check CHECK ((((status = 'open'::text) AND (resolved_by_operation_key IS NULL) AND (resolved_at IS NULL)) OR ((status = 'resolved'::text) AND (resolved_by_operation_key IS NOT NULL) AND (resolved_at IS NOT NULL))))
);


--
-- Name: financial_announcement_triggers; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.financial_announcement_triggers (
    announcement_id text PRIMARY KEY,
    category text NOT NULL,
    instrument_id text NOT NULL,
    ts_code text NOT NULL,
    instrument_name text NOT NULL,
    title text NOT NULL,
    source_published_date date NOT NULL,
    report_period date,
    source_url text NOT NULL,
    source_lineage_sha256 text NOT NULL,
    status text NOT NULL,
    accepted_no_match_count integer DEFAULT 0 NOT NULL,
    first_seen_operation_key text NOT NULL REFERENCES data.financial_daily_refresh_operations(idempotency_key) ON DELETE CASCADE,
    last_attempt_operation_key text,
    resolution_code text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    resolved_at timestamp with time zone,
    CONSTRAINT financial_announcement_triggers_id_check CHECK ((announcement_id ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_announcement_triggers_category_check CHECK ((category = ANY (ARRAY['年报'::text, '半年报'::text, '一季报'::text, '三季报'::text, '补充更正'::text]))),
    CONSTRAINT financial_announcement_triggers_identity_check CHECK (((instrument_id <> ''::text) AND (ts_code <> ''::text))),
    CONSTRAINT financial_announcement_triggers_lineage_check CHECK ((source_lineage_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT financial_announcement_triggers_count_check CHECK (((accepted_no_match_count >= 0) AND (accepted_no_match_count <= 5))),
    CONSTRAINT financial_announcement_triggers_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'matched'::text, 'checked_no_structured_change'::text]))),
    CONSTRAINT financial_announcement_triggers_state_check CHECK ((((status = 'pending'::text) AND (resolution_code IS NULL) AND (resolved_at IS NULL)) OR ((status = 'matched'::text) AND (resolution_code = 'matched_source_version'::text) AND (resolved_at IS NOT NULL)) OR ((status = 'checked_no_structured_change'::text) AND (accepted_no_match_count = 5) AND (resolution_code = 'checked_no_structured_change'::text) AND (resolved_at IS NOT NULL))))
);


--
-- Name: financial_refresh_instrument_attempts; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.financial_refresh_instrument_attempts (
    idempotency_key text NOT NULL REFERENCES data.financial_daily_refresh_operations(idempotency_key) ON DELETE CASCADE,
    instrument_id text NOT NULL,
    status text NOT NULL,
    matched_announcement_ids jsonb NOT NULL,
    checkpoints jsonb NOT NULL,
    failure_code text,
    failure_endpoint text,
    attempted_at timestamp with time zone NOT NULL,
    PRIMARY KEY (idempotency_key, instrument_id),
    CONSTRAINT financial_refresh_instrument_attempts_identity_check CHECK ((instrument_id <> ''::text)),
    CONSTRAINT financial_refresh_instrument_attempts_status_check CHECK ((status = ANY (ARRAY['accepted'::text, 'failed'::text]))),
    CONSTRAINT financial_refresh_instrument_attempts_state_check CHECK ((((status = 'accepted'::text) AND (failure_code IS NULL) AND (failure_endpoint IS NULL)) OR ((status = 'failed'::text) AND (failure_code IS NOT NULL) AND (failure_endpoint IS NOT NULL))))
);


--
-- Name: industry_refresh_operations; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.industry_refresh_operations (
    idempotency_key text NOT NULL,
    fingerprint text NOT NULL,
    source_generation_manifest_sha256 text NOT NULL,
    prior_industry_manifest_sha256 text,
    observation_through_session date NOT NULL,
    status text NOT NULL,
    source_lineage_sha256 text,
    failure_code text,
    failure_diagnostic jsonb,
    candidate_manifest_sha256 text,
    composed_generation_manifest_sha256 text,
    publication_prepared_at timestamp with time zone,
    publication_head_moved_at timestamp with time zone,
    published_generation_manifest_sha256 text,
    published_at timestamp with time zone,
    published_outcome jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    retention_released_at timestamp with time zone,
    CONSTRAINT industry_refresh_operations_key_check CHECK (((idempotency_key <> ''::text) AND (idempotency_key = btrim(idempotency_key)))),
    CONSTRAINT industry_refresh_operations_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT industry_refresh_operations_source_generation_check CHECK ((source_generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT industry_refresh_operations_prior_check CHECK (((prior_industry_manifest_sha256 IS NULL) OR (prior_industry_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT industry_refresh_operations_lineage_check CHECK (((source_lineage_sha256 IS NULL) OR (source_lineage_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT industry_refresh_operations_candidate_check CHECK (((candidate_manifest_sha256 IS NULL) OR (candidate_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT industry_refresh_operations_composed_check CHECK (((composed_generation_manifest_sha256 IS NULL) OR (composed_generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT industry_refresh_operations_published_check CHECK (((published_generation_manifest_sha256 IS NULL) OR (published_generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT industry_refresh_operations_publication_state_check CHECK (((published_generation_manifest_sha256 IS NULL) = (published_at IS NULL)) AND ((published_generation_manifest_sha256 IS NULL) = (published_outcome IS NULL))),
    CONSTRAINT industry_refresh_operations_status_check CHECK ((status = ANY (ARRAY['running'::text, 'succeeded'::text, 'failed'::text]))),
    CONSTRAINT industry_refresh_operations_state_check CHECK ((((status = 'running'::text) AND (candidate_manifest_sha256 IS NULL) AND (failure_code IS NULL) AND (finished_at IS NULL)) OR ((status = 'succeeded'::text) AND (candidate_manifest_sha256 IS NOT NULL) AND (source_lineage_sha256 IS NOT NULL) AND (failure_code IS NULL) AND (finished_at IS NOT NULL)) OR ((status = 'failed'::text) AND (candidate_manifest_sha256 IS NULL) AND (failure_code IS NOT NULL) AND (finished_at IS NOT NULL))))
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
    CONSTRAINT generation_pins_owner_kind_check CHECK ((owner_kind = ANY (ARRAY['research_batch_attempt'::text, 'research_run_attempt'::text, 'tracking_advance_attempt'::text]))),
    CONSTRAINT generation_pins_status_check CHECK ((status = ANY (ARRAY['active'::text, 'released'::text, 'fenced'::text])))
);


--
-- Name: refresh_operations; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.refresh_operations (
    idempotency_key text NOT NULL,
    kind text NOT NULL,
    fingerprint text NOT NULL,
    status text NOT NULL,
    owner_token text,
    lease_expires_at timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    phase text,
    last_heartbeat_at timestamp with time zone,
    outcome text,
    as_of timestamp with time zone,
    observation_through_session date,
    expected_generation_manifest_sha256 text,
    candidate_prepared_at timestamp with time zone,
    generation_manifest_sha256 text,
    data_through_session date,
    last_refresh_at timestamp with time zone,
    financial_complete_through_session date,
    matched_trigger_count integer,
    checked_no_structured_change_count integer,
    accepted_instrument_count integer,
    failed_instrument_count integer,
    pending_instrument_count integer,
    discovery_gap_count integer,
    failure_code text,
    last_failure_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT refresh_operations_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT refresh_operations_check CHECK (
        (
            status = 'accepted'::text
            AND owner_token IS NULL
            AND lease_expires_at IS NULL
            AND phase IS NULL
            AND outcome IS NULL
            AND failure_code IS NULL
        )
        OR (
            status = 'running'::text
            AND outcome IS NULL
            AND owner_token IS NOT NULL
            AND lease_expires_at IS NOT NULL
            AND attempt_count > 0
            AND phase IS NOT NULL
            AND last_heartbeat_at IS NOT NULL
            AND failure_code IS NULL
            AND started_at IS NOT NULL
        )
        OR (
            status = 'succeeded'::text
            AND (
                (
                    kind = ANY (ARRAY['market'::text, 'industry'::text])
                    AND outcome = ANY (ARRAY['published'::text, 'no_change'::text])
                )
                OR (
                    kind = 'financial'::text
                    AND outcome = ANY (
                        ARRAY['published'::text, 'no_change'::text, 'degraded'::text]
                    )
                )
            )
            AND generation_manifest_sha256 IS NOT NULL
            AND data_through_session IS NOT NULL
            AND last_refresh_at IS NOT NULL
            AND phase IS NOT NULL
            AND last_heartbeat_at IS NOT NULL
            AND failure_code IS NULL
            AND last_failure_code IS NULL
            AND finished_at IS NOT NULL
        )
        OR (
            status = 'failed'::text
            AND (
                (kind = 'market'::text AND outcome IS NULL)
                OR (
                    kind = ANY (ARRAY['financial'::text, 'industry'::text])
                    AND outcome = ANY (
                        ARRAY['business_rejected'::text, 'infrastructure_failed'::text]
                    )
                )
            )
            AND phase IS NOT NULL
            AND last_heartbeat_at IS NOT NULL
            AND failure_code IS NOT NULL
            AND finished_at IS NOT NULL
        )
        OR (
            status = 'cancelled'::text
            AND owner_token IS NULL
            AND lease_expires_at IS NULL
            AND outcome IS NULL
            AND failure_code IS NULL
            AND finished_at IS NOT NULL
        )
    ),
    CONSTRAINT refresh_operations_counts_check CHECK (((matched_trigger_count IS NULL OR matched_trigger_count >= 0) AND (checked_no_structured_change_count IS NULL OR checked_no_structured_change_count >= 0) AND (accepted_instrument_count IS NULL OR accepted_instrument_count >= 0) AND (failed_instrument_count IS NULL OR failed_instrument_count >= 0) AND (pending_instrument_count IS NULL OR pending_instrument_count >= 0) AND (discovery_gap_count IS NULL OR discovery_gap_count >= 0))),
    CONSTRAINT refresh_operations_expected_generation_manifest_sha256_check CHECK (((expected_generation_manifest_sha256 IS NULL) OR (expected_generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT refresh_operations_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT refresh_operations_financial_receipt_check CHECK (
        (
            kind IN ('market', 'industry')
            AND financial_complete_through_session IS NULL
            AND matched_trigger_count IS NULL
            AND checked_no_structured_change_count IS NULL
            AND accepted_instrument_count IS NULL
            AND failed_instrument_count IS NULL
            AND pending_instrument_count IS NULL
            AND discovery_gap_count IS NULL
        )
        OR (
            kind = 'financial'
            AND (
                (
                    status IN ('accepted', 'running', 'cancelled')
                    AND financial_complete_through_session IS NULL
                    AND matched_trigger_count IS NULL
                    AND checked_no_structured_change_count IS NULL
                    AND accepted_instrument_count IS NULL
                    AND failed_instrument_count IS NULL
                    AND pending_instrument_count IS NULL
                    AND discovery_gap_count IS NULL
                )
                OR (
                    status = 'failed'
                    AND financial_complete_through_session IS NULL
                    AND (
                        (
                            matched_trigger_count IS NULL
                            AND checked_no_structured_change_count IS NULL
                            AND accepted_instrument_count IS NULL
                            AND failed_instrument_count IS NULL
                            AND pending_instrument_count IS NULL
                            AND discovery_gap_count IS NULL
                        )
                        OR (
                            matched_trigger_count IS NOT NULL
                            AND checked_no_structured_change_count IS NOT NULL
                            AND accepted_instrument_count IS NOT NULL
                            AND failed_instrument_count IS NOT NULL
                            AND pending_instrument_count IS NOT NULL
                            AND discovery_gap_count IS NOT NULL
                        )
                    )
                )
                OR (
                    status = 'succeeded'
                    AND financial_complete_through_session IS NOT NULL
                    AND matched_trigger_count IS NOT NULL
                    AND checked_no_structured_change_count IS NOT NULL
                    AND accepted_instrument_count IS NOT NULL
                    AND failed_instrument_count IS NOT NULL
                    AND pending_instrument_count IS NOT NULL
                    AND discovery_gap_count IS NOT NULL
                    AND (
                        (
                            outcome = 'degraded'
                            AND (pending_instrument_count > 0 OR discovery_gap_count > 0)
                        )
                        OR (
                            outcome IN ('published', 'no_change')
                            AND pending_instrument_count = 0
                            AND discovery_gap_count = 0
                        )
                    )
                )
            )
        )
    ),
    CONSTRAINT refresh_operations_generation_manifest_sha256_check CHECK (((generation_manifest_sha256 IS NULL) OR (generation_manifest_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT refresh_operations_idempotency_key_check CHECK (((idempotency_key <> ''::text) AND (idempotency_key = btrim(idempotency_key)))),
    CONSTRAINT refresh_operations_kind_check CHECK ((kind = ANY (ARRAY['market'::text, 'financial'::text, 'industry'::text]))),
    CONSTRAINT refresh_operations_outcome_check CHECK (((outcome IS NULL) OR (outcome = ANY (ARRAY['published'::text, 'no_change'::text, 'degraded'::text, 'business_rejected'::text, 'infrastructure_failed'::text])))),
    CONSTRAINT refresh_operations_owner_token_check CHECK (((owner_token IS NULL) OR ((owner_token <> ''::text) AND (owner_token = btrim(owner_token))))),
    CONSTRAINT refresh_operations_phase_check CHECK (
        phase IS NULL OR phase = ANY (ARRAY[
            'claim'::text,
            'current_head'::text,
            'market'::text,
            'validation'::text,
            'benchmark'::text,
            'materialization'::text,
            'candidate_validation'::text,
            'publication'::text,
            'financial'::text,
            'industry'::text
        ])
    ),
    CONSTRAINT refresh_operations_status_check CHECK ((status = ANY (ARRAY['accepted'::text, 'running'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text]))),
    CONSTRAINT refresh_operations_target_check CHECK ((((kind = 'market'::text) AND (as_of IS NOT NULL) AND (observation_through_session IS NULL)) OR ((kind = ANY (ARRAY['financial'::text, 'industry'::text])) AND (as_of IS NULL) AND (observation_through_session IS NOT NULL))))
);


--
-- Name: refresh_cursor_secrets; Type: TABLE; Schema: data; Owner: -
--

CREATE TABLE data.refresh_cursor_secrets (
    singleton smallint PRIMARY KEY,
    secret text DEFAULT (
        replace(gen_random_uuid()::text, '-', '')
        || replace(gen_random_uuid()::text, '-', '')
    ) NOT NULL,
    CONSTRAINT refresh_cursor_secrets_singleton_check CHECK (singleton = 1),
    CONSTRAINT refresh_cursor_secrets_secret_check CHECK (secret ~ '^[0-9a-f]{64}$')
);

INSERT INTO data.refresh_cursor_secrets (singleton) VALUES (1);


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


ALTER TABLE ONLY data.industry_refresh_operations
    ADD CONSTRAINT industry_refresh_operations_pkey PRIMARY KEY (idempotency_key);


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
-- Name: data_one_running_refresh_idx; Type: INDEX; Schema: data; Owner: -
--

CREATE UNIQUE INDEX data_one_running_refresh_idx ON data.refresh_operations USING btree ((true)) WHERE (status = 'running'::text);


--
-- Name: data_refresh_history_idx; Type: INDEX; Schema: data; Owner: -
--

CREATE INDEX data_refresh_history_idx ON data.refresh_operations USING btree (created_at DESC, idempotency_key DESC);


--
-- Name: data_refresh_latest_kind_idx; Type: INDEX; Schema: data; Owner: -
--

CREATE INDEX data_refresh_latest_kind_idx ON data.refresh_operations USING btree (kind, created_at DESC, idempotency_key DESC);


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
