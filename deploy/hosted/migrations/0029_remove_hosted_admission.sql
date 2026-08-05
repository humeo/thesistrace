-- Historical migrations are immutable. Replace the retained deletion
-- function without its retired admission-state cleanup before dropping that
-- state table.

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

DROP TABLE thesistrace_product.user_compute_admissions;
