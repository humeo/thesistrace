DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'thesistrace_health'
    ) THEN
        CREATE ROLE thesistrace_health
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

GRANT thesistrace_health TO CURRENT_USER;
GRANT USAGE ON SCHEMA thesistrace_control TO thesistrace_health;

CREATE OR REPLACE FUNCTION thesistrace_control.operator_health_snapshot()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control, thesistrace_product
AS $$
    WITH
    pending_outbox AS (
        SELECT 'user_compute'::text AS queue, created_at::timestamptz AS created_at
        FROM thesistrace_product.execution_outbox
        WHERE status = 'pending'
        UNION ALL
        SELECT 'data'::text, created_at::timestamptz
        FROM thesistrace_product.platform_execution_outbox
        WHERE status = 'pending'
        UNION ALL
        SELECT 'tracking'::text, created_at::timestamptz
        FROM thesistrace_product.tracking_execution_outbox
        WHERE status = 'pending'
    ),
    current_release AS (
        SELECT release.manifest_json::jsonb AS manifest,
               release.created_at::timestamptz AS created_at
        FROM thesistrace_product.dataset_release_pointer AS pointer
        JOIN thesistrace_product.dataset_releases AS release
          ON release.id = pointer.release_id
        WHERE pointer.singleton = 1
    ),
    current_data AS (
        SELECT
            manifest,
            created_at,
            EXTRACT(EPOCH FROM clock_timestamp() - created_at) AS age_seconds,
            (
                manifest ->> 'manifest_sha256' ~ '^[0-9a-f]{64}$'
                AND jsonb_typeof(manifest -> 'objects') = 'array'
                AND NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(manifest -> 'objects') AS object
                    WHERE object ->> 'sha256' !~ '^[0-9a-f]{64}$'
                       OR jsonb_typeof(object -> 'bytes') <> 'number'
                )
            ) AS manifest_checksum_valid,
            (
                manifest ->> 'canonical_schema_version' = 'canonical-eod-v1'
                AND jsonb_typeof(manifest -> 'schemas') = 'array'
                AND jsonb_array_length(manifest -> 'schemas') > 0
                AND jsonb_typeof(manifest -> 'canonical_tables') = 'array'
            ) AS schema_valid,
            (
                COALESCE(manifest ->> 'session_count', '') ~ '^[1-9][0-9]*$'
                AND COALESCE(manifest ->> 'instrument_count', '') ~ '^[1-9][0-9]*$'
                AND manifest #>> '{appended_session_range,start}' IS NOT NULL
                AND manifest #>> '{appended_session_range,end}' IS NOT NULL
            ) AS coverage_valid,
            (
                manifest -> 'predecessor_id' = 'null'::jsonb
                OR EXISTS (
                    SELECT 1
                    FROM thesistrace_product.dataset_releases AS predecessor
                    WHERE predecessor.id = manifest ->> 'predecessor_id'
                )
            ) AS lineage_valid
        FROM current_release
    ),
    latest_equivalence AS (
        SELECT status, updated_at::timestamptz AS updated_at
        FROM thesistrace_product.tracking_equivalence_requests
        ORDER BY updated_at::timestamptz DESC
        LIMIT 1
    )
    SELECT jsonb_build_object(
        'system', jsonb_build_object(
            'outbox_pending', (SELECT count(*) FROM pending_outbox),
            'outbox_oldest_age_seconds', COALESCE(
                (
                    SELECT EXTRACT(EPOCH FROM clock_timestamp() - min(created_at))
                    FROM pending_outbox
                ),
                0
            ),
            'task_queue_user_pending', (
                SELECT count(*) FROM pending_outbox WHERE queue = 'user_compute'
            ),
            'task_queue_data_pending', (
                SELECT count(*) FROM pending_outbox WHERE queue = 'data'
            ),
            'task_queue_tracking_pending', (
                SELECT count(*) FROM pending_outbox WHERE queue = 'tracking'
            ),
            'workflow_running',
                (SELECT count(*) FROM thesistrace_product.research_runs
                 WHERE status IN ('queued', 'running'))
                + (SELECT count(*) FROM thesistrace_product.dataset_publications
                   WHERE status IN ('queued', 'running'))
                + (SELECT count(*) FROM thesistrace_product.tracking_advances
                   WHERE status IN ('queued', 'running'))
                + (SELECT count(*) FROM thesistrace_product.tracking_equivalence_requests
                   WHERE status IN ('queued', 'running'))
                + (SELECT count(*) FROM thesistrace_product.tracking_generation_rebuilds
                   WHERE status IN ('queued', 'running')),
            'workflow_capacity', 4
        ),
        'data', jsonb_build_object(
            'release_present', EXISTS (SELECT 1 FROM current_data),
            'release_age_seconds', COALESCE(
                (SELECT age_seconds FROM current_data), -1
            ),
            'manifest_checksum_valid', COALESCE(
                (SELECT manifest_checksum_valid FROM current_data), false
            ),
            'schema_valid', COALESCE(
                (SELECT schema_valid FROM current_data), false
            ),
            'coverage_valid', COALESCE(
                (SELECT coverage_valid FROM current_data), false
            ),
            'lineage_valid', COALESCE(
                (SELECT lineage_valid FROM current_data), false
            ),
            'failed_publications', (
                SELECT count(*)
                FROM thesistrace_product.dataset_publications AS publication
                WHERE publication.status = 'failed'
                  AND publication.updated_at::timestamptz > COALESCE(
                      (SELECT created_at FROM current_data), '-infinity'::timestamptz
                  )
            ),
            'previous_release_preserved',
                EXISTS (SELECT 1 FROM current_data)
                AND NOT EXISTS (
                    SELECT 1
                    FROM thesistrace_product.dataset_publications AS publication
                    WHERE publication.status = 'failed'
                      AND publication.result_release_id IS NOT NULL
                )
        ),
        'quantitative', jsonb_build_object(
            'equivalence_status', COALESCE(
                (SELECT status FROM latest_equivalence), 'not_run'
            ),
            'equivalence_age_seconds', COALESCE(
                (
                    SELECT EXTRACT(EPOCH FROM clock_timestamp() - updated_at)
                    FROM latest_equivalence
                ),
                -1
            )
        )
    )
$$;

REVOKE ALL ON FUNCTION thesistrace_control.operator_health_snapshot()
FROM PUBLIC, thesistrace_api, thesistrace_relay,
     thesistrace_data, thesistrace_compute;
GRANT EXECUTE ON FUNCTION thesistrace_control.operator_health_snapshot()
TO thesistrace_health;
