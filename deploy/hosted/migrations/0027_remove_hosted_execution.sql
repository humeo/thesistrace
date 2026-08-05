-- Historical migrations are immutable. This forward contraction disables
-- retired Hosted service identities and removes their dispatch state after
-- replacing retained functions that formerly referenced it.

ALTER ROLE thesistrace_relay NOLOGIN;
ALTER ROLE thesistrace_data NOLOGIN;
ALTER ROLE thesistrace_compute NOLOGIN;

CREATE OR REPLACE FUNCTION thesistrace_control.request_resource_deletion(
    p_tombstone_id text,
    p_resource_kind text,
    p_resource_id text,
    p_actor text,
    p_deleted_at timestamptz
)
RETURNS TABLE (
    tombstone_id text,
    workspace_id text,
    resource_kind text,
    resource_id text,
    authoritative_manifest_sha256 text,
    actor text,
    deleted_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control, thesistrace_product
AS $$
DECLARE
    v_workspace_id text;
    v_status text;
    v_result_bundle_id text;
    v_manifest_sha256 text;
    v_fencing_token integer;
BEGIN
    v_workspace_id := thesistrace_control.current_workspace_id();
    IF v_workspace_id IS NULL THEN
        RAISE EXCEPTION 'Personal Workspace context is missing';
    END IF;
    IF p_tombstone_id IS NULL OR p_tombstone_id = ''
       OR p_resource_id IS NULL OR p_resource_id = ''
       OR p_actor IS NULL OR p_actor = ''
       OR p_resource_kind NOT IN ('research_run', 'daily_track') THEN
        RAISE EXCEPTION 'Resource deletion request is invalid';
    END IF;

    IF p_resource_kind = 'research_run' THEN
        SELECT run.status, run.result_bundle_id,
               run.result_manifest_sha256
        INTO v_status, v_result_bundle_id, v_manifest_sha256
        FROM thesistrace_product.research_runs AS run
        WHERE run.workspace_id = v_workspace_id
          AND run.id = p_resource_id
        FOR UPDATE;
        IF NOT FOUND THEN
            RETURN;
        END IF;
        IF v_status NOT IN ('succeeded', 'failed', 'cancelled') THEN
            RAISE EXCEPTION 'RESOURCE_NOT_TERMINAL';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM thesistrace_product.daily_tracks AS track
            WHERE track.workspace_id = v_workspace_id
              AND track.seed_run_id = p_resource_id
        ) THEN
            RAISE EXCEPTION 'RESOURCE_RETAINED';
        END IF;
        IF v_result_bundle_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM thesistrace_control.storage_references AS reference
            WHERE reference.owner_scope = 'workspace'
              AND reference.workspace_id = v_workspace_id
              AND reference.resource_kind = 'research_run'
              AND reference.resource_id = p_resource_id
        ) THEN
            RAISE EXCEPTION 'RESOURCE_STORAGE_UNINDEXED';
        END IF;
        v_fencing_token := NULL;
    ELSE
        SELECT track.status, track.fencing_token,
               checkpoint.manifest_sha256
        INTO v_status, v_fencing_token, v_manifest_sha256
        FROM thesistrace_product.daily_tracks AS track
        LEFT JOIN thesistrace_product.tracking_checkpoints AS checkpoint
          ON checkpoint.workspace_id = track.workspace_id
         AND checkpoint.id = track.head_checkpoint_id
        WHERE track.workspace_id = v_workspace_id
          AND track.id = p_resource_id
        FOR UPDATE OF track;
        IF NOT FOUND THEN
            RETURN;
        END IF;
        IF v_status <> 'stopped' THEN
            RAISE EXCEPTION 'RESOURCE_NOT_TERMINAL';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM thesistrace_product.tracking_checkpoints AS checkpoint
            WHERE checkpoint.workspace_id = v_workspace_id
              AND checkpoint.daily_track_id = p_resource_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM thesistrace_control.storage_references AS reference
                  WHERE reference.owner_scope = 'workspace'
                    AND reference.workspace_id = v_workspace_id
                    AND reference.resource_kind = 'tracking_checkpoint'
                    AND reference.resource_id = checkpoint.id
              )
        ) THEN
            RAISE EXCEPTION 'RESOURCE_STORAGE_UNINDEXED';
        END IF;
    END IF;

    INSERT INTO thesistrace_control.resource_tombstones (
        id, workspace_id, resource_kind, resource_id,
        authoritative_manifest_sha256, actor, deleted_at
    ) VALUES (
        p_tombstone_id, v_workspace_id, p_resource_kind, p_resource_id,
        v_manifest_sha256, p_actor, p_deleted_at
    );
    INSERT INTO thesistrace_control.resource_cleanup_jobs (
        tombstone_id, daily_track_id, fencing_token, status
    ) VALUES (
        p_tombstone_id,
        CASE WHEN p_resource_kind = 'daily_track' THEN p_resource_id END,
        v_fencing_token,
        'pending'
    );

    IF p_resource_kind = 'research_run' THEN
        INSERT INTO thesistrace_control.storage_references (
            owner_scope, workspace_id, resource_kind,
            resource_id, object_key, created_at
        )
        SELECT DISTINCT 'workspace', v_workspace_id,
               'resource_tombstone', p_tombstone_id,
               reference.object_key, p_deleted_at
        FROM thesistrace_control.storage_references AS reference
        WHERE reference.owner_scope = 'workspace'
          AND reference.workspace_id = v_workspace_id
          AND reference.resource_kind = 'research_run'
          AND reference.resource_id = p_resource_id
        ON CONFLICT DO NOTHING;

        DELETE FROM thesistrace_control.storage_references AS reference
        WHERE reference.owner_scope = 'workspace'
          AND reference.workspace_id = v_workspace_id
          AND reference.resource_kind = 'research_run'
          AND reference.resource_id = p_resource_id;
        DELETE FROM thesistrace_product.user_compute_admissions AS admission
        WHERE admission.workspace_id = v_workspace_id
          AND admission.resource_kind = 'research_run'
          AND admission.resource_id = p_resource_id;
        DELETE FROM thesistrace_product.research_run_attempts AS attempt
        WHERE attempt.workspace_id = v_workspace_id
          AND attempt.run_id = p_resource_id;
        DELETE FROM thesistrace_product.research_run_idempotency AS request
        WHERE request.workspace_id = v_workspace_id
          AND request.run_id = p_resource_id;
        DELETE FROM
            thesistrace_product.daily_track_activation_reservations AS reservation
        WHERE reservation.workspace_id = v_workspace_id
          AND reservation.seed_run_id = p_resource_id;
        DELETE FROM thesistrace_product.research_runs AS run
        WHERE run.workspace_id = v_workspace_id AND run.id = p_resource_id;
    ELSE
        INSERT INTO thesistrace_control.storage_references (
            owner_scope, workspace_id, resource_kind,
            resource_id, object_key, created_at
        )
        SELECT DISTINCT 'workspace', v_workspace_id,
               'resource_tombstone', p_tombstone_id,
               reference.object_key, p_deleted_at
        FROM thesistrace_control.storage_references AS reference
        WHERE reference.owner_scope = 'workspace'
          AND reference.workspace_id = v_workspace_id
          AND reference.resource_kind = 'tracking_checkpoint'
          AND reference.resource_id IN (
              SELECT checkpoint.id
              FROM thesistrace_product.tracking_checkpoints AS checkpoint
              WHERE checkpoint.workspace_id = v_workspace_id
                AND checkpoint.daily_track_id = p_resource_id
          )
        ON CONFLICT DO NOTHING;

        DELETE FROM thesistrace_control.storage_references AS reference
        WHERE reference.owner_scope = 'workspace'
          AND reference.workspace_id = v_workspace_id
          AND reference.resource_kind = 'tracking_checkpoint'
          AND reference.resource_id IN (
              SELECT checkpoint.id
              FROM thesistrace_product.tracking_checkpoints AS checkpoint
              WHERE checkpoint.workspace_id = v_workspace_id
                AND checkpoint.daily_track_id = p_resource_id
          );
        DELETE FROM thesistrace_product.tracking_advance_attempts AS attempt
        WHERE attempt.workspace_id = v_workspace_id
          AND attempt.advance_id IN (
              SELECT advance.id
              FROM thesistrace_product.tracking_advances AS advance
              WHERE advance.workspace_id = v_workspace_id
                AND advance.daily_track_id = p_resource_id
          );
        DELETE FROM
            thesistrace_product.tracking_equivalence_requests AS request
        WHERE request.workspace_id = v_workspace_id
          AND request.daily_track_id = p_resource_id;
        DELETE FROM
            thesistrace_product.tracking_generation_rebuilds AS rebuild
        WHERE rebuild.workspace_id = v_workspace_id
          AND rebuild.daily_track_id = p_resource_id;
        DELETE FROM thesistrace_product.tracking_advances AS advance
        WHERE advance.workspace_id = v_workspace_id
          AND advance.daily_track_id = p_resource_id;
        DELETE FROM thesistrace_product.tracking_checkpoints AS checkpoint
        WHERE checkpoint.workspace_id = v_workspace_id
          AND checkpoint.daily_track_id = p_resource_id;
        DELETE FROM thesistrace_product.tracking_generations AS generation
        WHERE generation.workspace_id = v_workspace_id
          AND generation.daily_track_id = p_resource_id;
        DELETE FROM
            thesistrace_product.daily_track_activation_idempotency AS activation
        WHERE activation.workspace_id = v_workspace_id
          AND activation.daily_track_id = p_resource_id;
        DELETE FROM
            thesistrace_product.daily_track_activation_reservations AS reservation
        WHERE reservation.workspace_id = v_workspace_id
          AND reservation.track_id = p_resource_id;
        DELETE FROM thesistrace_product.working_cache_deletions AS deletion
        WHERE deletion.workspace_id = v_workspace_id
          AND deletion.daily_track_id = p_resource_id;
        DELETE FROM thesistrace_product.daily_tracks AS track
        WHERE track.workspace_id = v_workspace_id AND track.id = p_resource_id;
    END IF;

    RETURN QUERY SELECT
        p_tombstone_id,
        v_workspace_id,
        p_resource_kind,
        p_resource_id,
        v_manifest_sha256,
        p_actor,
        p_deleted_at;
END;
$$;

CREATE OR REPLACE FUNCTION thesistrace_control.operator_health_snapshot()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control, thesistrace_product
AS $$
    WITH
    current_release AS (
        SELECT pointer.release_id,
               release.manifest_json::jsonb AS manifest,
               release.created_at::timestamptz AS created_at
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
    current_data AS (
        SELECT
            release.manifest,
            release.created_at,
            EXTRACT(EPOCH FROM clock_timestamp() - release.created_at) AS age_seconds,
            (
                release.manifest ->> 'canonical_schema_version' = 'canonical-eod-v1'
                AND jsonb_typeof(release.manifest -> 'schemas') = 'array'
                AND jsonb_array_length(release.manifest -> 'schemas') > 0
                AND jsonb_typeof(release.manifest -> 'canonical_tables') = 'array'
            ) AS schema_valid,
            (
                COALESCE(release.manifest ->> 'session_count', '') ~ '^[1-9][0-9]*$'
                AND COALESCE(release.manifest ->> 'instrument_count', '') ~ '^[1-9][0-9]*$'
                AND release.manifest #>> '{appended_session_range,start}' IS NOT NULL
                AND release.manifest #>> '{appended_session_range,end}' IS NOT NULL
            ) AS coverage_valid,
            (
                release.manifest -> 'predecessor_id' = 'null'::jsonb
                OR EXISTS (
                    SELECT 1
                    FROM thesistrace_product.dataset_releases AS predecessor
                    WHERE predecessor.id = release.manifest ->> 'predecessor_id'
                )
            ) AS lineage_valid,
            COALESCE(
                publication.status = 'succeeded'
                AND publication.result_release_id = release.release_id
                AND publication.result_manifest_sha256
                    = release.manifest ->> 'manifest_sha256'
                AND publication.result_manifest_sha256 ~ '^[0-9a-f]{64}$',
                false
            ) AS publication_validation_succeeded,
            COALESCE(
                publication.kind LIKE 'fixture_%'
                OR release.manifest #>> '{appended_session_range,end}'
                    = publication.parameters_json ->> 'as_of',
                false
            ) AS release_session_current
        FROM current_release AS release
        LEFT JOIN committed_publication AS publication ON true
    ),
    latest_equivalence AS (
        SELECT status, updated_at::timestamptz AS updated_at
        FROM thesistrace_product.tracking_equivalence_requests
        ORDER BY updated_at::timestamptz DESC
        LIMIT 1
    )
    SELECT jsonb_build_object(
        'system', jsonb_build_object(
            'active_jobs',
                (SELECT count(*) FROM thesistrace_product.research_runs
                 WHERE status IN ('queued', 'running'))
                + (SELECT count(*) FROM thesistrace_product.dataset_publications
                   WHERE status IN ('queued', 'running'))
                + (SELECT count(*) FROM thesistrace_product.tracking_advances
                   WHERE status IN ('queued', 'running'))
                + (SELECT count(*) FROM thesistrace_product.tracking_equivalence_requests
                   WHERE status IN ('queued', 'running'))
                + (SELECT count(*) FROM thesistrace_product.tracking_generation_rebuilds
                   WHERE status IN ('queued', 'running'))
        ),
        'data', jsonb_build_object(
            'release_present', EXISTS (SELECT 1 FROM current_data),
            'release_age_seconds', COALESCE(
                (SELECT age_seconds FROM current_data), -1
            ),
            'publication_validation_succeeded', COALESCE(
                (SELECT publication_validation_succeeded FROM current_data), false
            ),
            'release_session_current', COALESCE(
                (SELECT release_session_current FROM current_data), false
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

DROP FUNCTION thesistrace_control.request_scheduled_dataset_publication(
    text, text, text, jsonb, text, text
);
DROP FUNCTION thesistrace_control.hosted_tushare_authorized();
DROP FUNCTION thesistrace_control.active_daily_track_scan_bound();
DROP FUNCTION thesistrace_control.active_daily_track_refs(
    text, text, text, text, integer
);
DROP FUNCTION thesistrace_control.pending_execution_outbox(integer);
DROP FUNCTION thesistrace_control.mark_execution_dispatched(text);

DROP TABLE thesistrace_product.tracking_execution_outbox;
DROP TABLE thesistrace_product.tracking_release_triggers;
DROP TABLE thesistrace_product.platform_execution_outbox;
DROP TABLE thesistrace_product.execution_outbox;

REVOKE ALL ON FUNCTION thesistrace_control.operator_health_snapshot()
FROM thesistrace_relay, thesistrace_data, thesistrace_compute;
