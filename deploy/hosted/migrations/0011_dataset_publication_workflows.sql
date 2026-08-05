CREATE TABLE thesistrace_product.dataset_publications (
    id text PRIMARY KEY,
    request_version text NOT NULL CHECK (request_version = 'v1'),
    kind text NOT NULL CHECK (
        kind IN (
            'fixture_bootstrap',
            'fixture_increment',
            'live_bootstrap',
            'live_increment'
        )
    ),
    parameters_json jsonb NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    trigger_kind text NOT NULL CHECK (
        trigger_kind IN ('operator', 'schedule')
    ),
    status text NOT NULL CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    result_release_id text
        REFERENCES thesistrace_product.dataset_releases(id),
    result_manifest_sha256 text,
    diagnostic_json jsonb,
    created_at text NOT NULL,
    updated_at text NOT NULL
);

CREATE TABLE thesistrace_product.dataset_publication_attempts (
    id text PRIMARY KEY,
    publication_id text NOT NULL
        REFERENCES thesistrace_product.dataset_publications(id),
    ordinal integer NOT NULL,
    status text NOT NULL CHECK (
        status IN ('running', 'succeeded', 'failed', 'cancelled')
    ),
    diagnostic_json jsonb,
    started_at text NOT NULL,
    finished_at text,
    UNIQUE (publication_id, ordinal)
);

CREATE TABLE thesistrace_product.tracking_release_triggers (
    release_id text PRIMARY KEY
        REFERENCES thesistrace_product.dataset_releases(id),
    status text NOT NULL CHECK (status IN ('pending', 'dispatched')),
    created_at text NOT NULL
);

CREATE UNIQUE INDEX one_running_dataset_publication
ON thesistrace_product.dataset_publications ((status))
WHERE status = 'running';

GRANT USAGE ON SCHEMA thesistrace_control TO thesistrace_data;

REVOKE ALL ON
    thesistrace_product.dataset_publications,
    thesistrace_product.dataset_publication_attempts,
    thesistrace_product.tracking_release_triggers
FROM PUBLIC;
REVOKE ALL ON
    thesistrace_product.dataset_publications,
    thesistrace_product.dataset_publication_attempts,
    thesistrace_product.tracking_release_triggers
FROM thesistrace_api, thesistrace_compute, thesistrace_data, thesistrace_relay;
GRANT SELECT, UPDATE ON
    thesistrace_product.dataset_publications
TO thesistrace_data;
GRANT SELECT, INSERT, UPDATE ON
    thesistrace_product.dataset_publication_attempts
TO thesistrace_data;
GRANT SELECT, INSERT ON
    thesistrace_product.tracking_release_triggers
TO thesistrace_data;

CREATE OR REPLACE FUNCTION thesistrace_control.request_scheduled_dataset_publication(
    requested_id text,
    requested_version text,
    requested_kind text,
    requested_parameters jsonb,
    requested_idempotency_key text,
    requested_at text
)
RETURNS TABLE (publication_id text, created boolean)
LANGUAGE plpgsql
SECURITY DEFINER
STRICT
SET search_path = pg_catalog, thesistrace_product
AS $$
DECLARE
    existing_id text;
BEGIN
    IF requested_id = ''
       OR requested_version <> 'v1'
       OR requested_kind NOT IN (
           'fixture_bootstrap',
           'fixture_increment',
           'live_bootstrap',
           'live_increment'
       )
       OR requested_idempotency_key = ''
       OR octet_length(requested_parameters::text) > 65536
    THEN
        RAISE EXCEPTION 'invalid scheduled Dataset Publication request';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'dataset-publication-request:' || requested_idempotency_key,
            0
        )
    );
    SELECT publication.id
    INTO existing_id
    FROM thesistrace_product.dataset_publications AS publication
    WHERE publication.idempotency_key = requested_idempotency_key;
    IF existing_id IS NOT NULL THEN
        RETURN QUERY SELECT existing_id, false;
        RETURN;
    END IF;

    INSERT INTO thesistrace_product.dataset_publications (
        id,
        request_version,
        kind,
        parameters_json,
        idempotency_key,
        trigger_kind,
        status,
        created_at,
        updated_at
    )
    VALUES (
        requested_id,
        requested_version,
        requested_kind,
        requested_parameters,
        requested_idempotency_key,
        'schedule',
        'queued',
        requested_at,
        requested_at
    );
    RETURN QUERY SELECT requested_id, true;
END;
$$;

REVOKE ALL ON FUNCTION
    thesistrace_control.request_scheduled_dataset_publication(
        text, text, text, jsonb, text, text
    )
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    thesistrace_control.request_scheduled_dataset_publication(
        text, text, text, jsonb, text, text
    )
TO thesistrace_data;

CREATE OR REPLACE FUNCTION thesistrace_control.hosted_tushare_authorized()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM thesistrace_control.source_authorization_declarations
        WHERE source = 'tushare'
          AND intended_scope = 'hosted-shared-dataset-releases'
    )
$$;

REVOKE ALL ON FUNCTION thesistrace_control.hosted_tushare_authorized()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION thesistrace_control.hosted_tushare_authorized()
TO thesistrace_data;
