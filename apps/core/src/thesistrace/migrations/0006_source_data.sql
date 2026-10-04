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
    statement_instrument_ids jsonb,
    indicator_collection jsonb,
    indicator_candidate_manifest_sha256 text
        CHECK (indicator_candidate_manifest_sha256 ~ '^[0-9a-f]{64}$'),
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
