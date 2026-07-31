ALTER FUNCTION thesistrace_control.operator_health_snapshot()
RENAME TO operator_health_snapshot_legacy;

REVOKE ALL ON FUNCTION
thesistrace_control.operator_health_snapshot_legacy()
FROM PUBLIC, thesistrace_health, thesistrace_api, thesistrace_relay,
     thesistrace_data, thesistrace_compute;

CREATE FUNCTION thesistrace_control.operator_health_snapshot()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control, thesistrace_product
AS $$
    WITH
    legacy AS (
        SELECT thesistrace_control.operator_health_snapshot_legacy() AS snapshot
    ),
    current_release AS (
        SELECT pointer.release_id,
               release.manifest_json::jsonb AS manifest
        FROM thesistrace_product.dataset_release_pointer AS pointer
        JOIN thesistrace_product.dataset_releases AS release
          ON release.id = pointer.release_id
        WHERE pointer.singleton = 1
    ),
    committed_publication AS (
        SELECT publication.status,
               publication.kind,
               publication.parameters_json,
               publication.result_release_id,
               publication.result_manifest_sha256
        FROM current_release
        JOIN thesistrace_product.dataset_publications AS publication
          ON publication.result_release_id = current_release.release_id
        WHERE publication.status = 'succeeded'
        ORDER BY publication.updated_at::timestamptz DESC
        LIMIT 1
    ),
    evidence AS (
        SELECT
            EXISTS (SELECT 1 FROM current_release) AS release_present,
            COALESCE(
                (
                    SELECT
                        publication.status = 'succeeded'
                        AND publication.result_release_id = release.release_id
                        AND publication.result_manifest_sha256
                            = release.manifest ->> 'manifest_sha256'
                        AND publication.result_manifest_sha256
                            ~ '^[0-9a-f]{64}$'
                    FROM committed_publication AS publication
                    CROSS JOIN current_release AS release
                ),
                false
            ) AS publication_validation_succeeded,
            COALESCE(
                (
                    SELECT
                        publication.kind LIKE 'fixture_%'
                        OR release.manifest #>> '{appended_session_range,end}'
                           = publication.parameters_json ->> 'as_of'
                    FROM committed_publication AS publication
                    CROSS JOIN current_release AS release
                ),
                false
            ) AS release_session_current
    )
    SELECT jsonb_set(
        jsonb_set(
            legacy.snapshot,
            '{system}',
            (legacy.snapshot -> 'system')
                - 'task_queue_user_pending'
                - 'task_queue_data_pending'
                - 'task_queue_tracking_pending'
                - 'workflow_capacity'
        ),
        '{data}',
        (legacy.snapshot -> 'data')
            - 'manifest_checksum_valid'
            || jsonb_build_object(
                'release_present', evidence.release_present,
                'publication_validation_succeeded',
                    evidence.publication_validation_succeeded,
                'release_session_current', evidence.release_session_current
            )
    )
    FROM legacy
    CROSS JOIN evidence
$$;

REVOKE ALL ON FUNCTION thesistrace_control.operator_health_snapshot()
FROM PUBLIC, thesistrace_api, thesistrace_relay,
     thesistrace_data, thesistrace_compute;
GRANT EXECUTE ON FUNCTION thesistrace_control.operator_health_snapshot()
TO thesistrace_health;
