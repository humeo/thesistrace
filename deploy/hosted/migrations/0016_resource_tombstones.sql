CREATE TABLE thesistrace_control.resource_tombstones (
    id text PRIMARY KEY,
    workspace_id text NOT NULL
        REFERENCES thesistrace_control.personal_workspaces(id),
    resource_kind text NOT NULL
        CHECK (resource_kind IN ('research_run', 'daily_track')),
    resource_id text NOT NULL,
    authoritative_manifest_sha256 text
        CHECK (
            authoritative_manifest_sha256 IS NULL
            OR authoritative_manifest_sha256 ~ '^[0-9a-f]{64}$'
        ),
    actor text NOT NULL CHECK (actor <> ''),
    deleted_at timestamptz NOT NULL,
    UNIQUE (workspace_id, resource_kind, resource_id)
);

CREATE TABLE thesistrace_control.resource_cleanup_jobs (
    tombstone_id text PRIMARY KEY
        REFERENCES thesistrace_control.resource_tombstones(id),
    daily_track_id text,
    fencing_token integer,
    status text NOT NULL CHECK (status IN ('pending', 'completed')),
    attempt_count integer NOT NULL DEFAULT 0,
    completed_at timestamptz,
    last_error text,
    CHECK (
        (daily_track_id IS NULL AND fencing_token IS NULL)
        OR (daily_track_id IS NOT NULL AND fencing_token IS NOT NULL)
    )
);

REVOKE ALL ON thesistrace_control.resource_tombstones FROM PUBLIC;
REVOKE ALL ON thesistrace_control.resource_cleanup_jobs FROM PUBLIC;
REVOKE ALL ON thesistrace_control.resource_tombstones
FROM thesistrace_api, thesistrace_compute, thesistrace_data,
     thesistrace_relay;
REVOKE ALL ON thesistrace_control.resource_cleanup_jobs
FROM thesistrace_api, thesistrace_compute, thesistrace_data,
     thesistrace_relay;

CREATE TRIGGER resource_tombstones_immutable
BEFORE UPDATE OR DELETE ON thesistrace_control.resource_tombstones
FOR EACH ROW EXECUTE FUNCTION
    thesistrace_control.reject_management_history_mutation();

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
        DELETE FROM thesistrace_product.execution_outbox AS outbox
        WHERE outbox.workspace_id = v_workspace_id
          AND outbox.resource_kind IN ('research_run', 'research_run_cancel')
          AND outbox.resource_id = p_resource_id;
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
        DELETE FROM thesistrace_product.execution_outbox AS outbox
        WHERE outbox.workspace_id = v_workspace_id
          AND (
              outbox.resource_id IN (
                  SELECT request.id
                  FROM thesistrace_product.tracking_equivalence_requests
                      AS request
                  WHERE request.workspace_id = v_workspace_id
                    AND request.daily_track_id = p_resource_id
              )
              OR outbox.resource_id IN (
                  SELECT rebuild.id
                  FROM thesistrace_product.tracking_generation_rebuilds
                      AS rebuild
                  WHERE rebuild.workspace_id = v_workspace_id
                    AND rebuild.daily_track_id = p_resource_id
              )
          );
        DELETE FROM thesistrace_product.tracking_execution_outbox AS outbox
        WHERE outbox.workspace_id = v_workspace_id
          AND outbox.daily_track_id = p_resource_id;
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

CREATE OR REPLACE FUNCTION
thesistrace_control.pending_resource_cleanups()
RETURNS TABLE (
    tombstone_id text,
    resource_kind text,
    resource_id text,
    daily_track_id text,
    fencing_token integer,
    attempt_count integer,
    last_error text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
    SELECT job.tombstone_id,
           tombstone.resource_kind,
           tombstone.resource_id,
           job.daily_track_id,
           job.fencing_token,
           job.attempt_count,
           job.last_error
    FROM thesistrace_control.resource_cleanup_jobs AS job
    JOIN thesistrace_control.resource_tombstones AS tombstone
      ON tombstone.id = job.tombstone_id
    WHERE job.status = 'pending'
    ORDER BY tombstone.deleted_at, job.tombstone_id;
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.resource_cleanup_candidates(p_tombstone_id text)
RETURNS SETOF text
LANGUAGE sql
STABLE
STRICT
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
    SELECT own.object_key
    FROM thesistrace_control.storage_references AS own
    WHERE own.owner_scope = 'workspace'
      AND own.resource_kind = 'resource_tombstone'
      AND own.resource_id = p_tombstone_id
      AND NOT EXISTS (
          SELECT 1
          FROM thesistrace_control.storage_references AS retained
          WHERE retained.object_key = own.object_key
            AND NOT (
                retained.owner_scope = own.owner_scope
                AND retained.workspace_id = own.workspace_id
                AND retained.resource_kind = own.resource_kind
                AND retained.resource_id = own.resource_id
            )
      )
    ORDER BY own.object_key;
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.complete_resource_cleanup(
    p_tombstone_id text,
    p_completed_at timestamptz
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
BEGIN
    DELETE FROM thesistrace_control.storage_references
    WHERE owner_scope = 'workspace'
      AND resource_kind = 'resource_tombstone'
      AND resource_id = p_tombstone_id;
    DELETE FROM thesistrace_control.stored_objects AS stored
    WHERE NOT EXISTS (
        SELECT 1
        FROM thesistrace_control.storage_references AS reference
        WHERE reference.object_key = stored.object_key
    );
    UPDATE thesistrace_control.resource_cleanup_jobs
    SET status = 'completed',
        attempt_count = attempt_count + 1,
        completed_at = p_completed_at,
        last_error = NULL
    WHERE tombstone_id = p_tombstone_id AND status = 'pending';
END;
$$;

CREATE OR REPLACE FUNCTION thesistrace_control.fail_resource_cleanup(
    p_tombstone_id text,
    p_error text
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
    UPDATE thesistrace_control.resource_cleanup_jobs
    SET attempt_count = attempt_count + 1,
        last_error = left(p_error, 1000)
    WHERE tombstone_id = p_tombstone_id AND status = 'pending';
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.request_resource_deletion(
    text, text, text, text, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION
thesistrace_control.pending_resource_cleanups() FROM PUBLIC;
REVOKE ALL ON FUNCTION
thesistrace_control.resource_cleanup_candidates(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION
thesistrace_control.complete_resource_cleanup(text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION
thesistrace_control.fail_resource_cleanup(text, text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
thesistrace_control.request_resource_deletion(
    text, text, text, text, timestamptz
) TO thesistrace_api;
GRANT EXECUTE ON FUNCTION
thesistrace_control.pending_resource_cleanups() TO thesistrace_api;
GRANT EXECUTE ON FUNCTION
thesistrace_control.resource_cleanup_candidates(text) TO thesistrace_api;
GRANT EXECUTE ON FUNCTION
thesistrace_control.complete_resource_cleanup(text, timestamptz)
TO thesistrace_api;
GRANT EXECUTE ON FUNCTION
thesistrace_control.fail_resource_cleanup(text, text) TO thesistrace_api;
