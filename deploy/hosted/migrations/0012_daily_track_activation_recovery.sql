CREATE TABLE thesistrace_product.daily_track_activation_reservations (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    track_id text NOT NULL,
    idempotency_key text NOT NULL,
    seed_run_id text NOT NULL,
    created_at text NOT NULL,
    PRIMARY KEY (workspace_id, track_id),
    UNIQUE (workspace_id, idempotency_key),
    FOREIGN KEY (workspace_id, seed_run_id)
        REFERENCES thesistrace_product.research_runs(workspace_id, id)
);

ALTER TABLE
thesistrace_product.daily_track_activation_reservations
ENABLE ROW LEVEL SECURITY;

ALTER TABLE
thesistrace_product.daily_track_activation_reservations
FORCE ROW LEVEL SECURITY;

CREATE POLICY personal_workspace_isolation
ON thesistrace_product.daily_track_activation_reservations
USING (
    workspace_id = thesistrace_control.current_workspace_id()
)
WITH CHECK (
    workspace_id = thesistrace_control.current_workspace_id()
);

REVOKE ALL ON
thesistrace_product.daily_track_activation_reservations
FROM PUBLIC, thesistrace_api, thesistrace_compute, thesistrace_data;

GRANT SELECT, INSERT, DELETE ON
thesistrace_product.daily_track_activation_reservations
TO thesistrace_api;

CREATE OR REPLACE FUNCTION
thesistrace_control.daily_track_head_manifest_sha256(
    requested_track_id text
)
RETURNS text
LANGUAGE sql
STABLE
STRICT
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
    SELECT checkpoint.manifest_sha256
    FROM thesistrace_product.daily_tracks AS track
    JOIN thesistrace_product.tracking_checkpoints AS checkpoint
      ON checkpoint.workspace_id = track.workspace_id
     AND checkpoint.id = track.head_checkpoint_id
    WHERE track.id = requested_track_id
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.daily_track_head_manifest_sha256(text)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
thesistrace_control.daily_track_head_manifest_sha256(text)
TO thesistrace_api, thesistrace_compute;

CREATE OR REPLACE FUNCTION
thesistrace_control.daily_track_activation_reservation_ids()
RETURNS SETOF text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
    SELECT reservation.track_id
    FROM thesistrace_product.daily_track_activation_reservations
        AS reservation
    ORDER BY reservation.track_id
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.delete_daily_track_activation_reservation(
    requested_track_id text
)
RETURNS boolean
LANGUAGE plpgsql
STRICT
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
BEGIN
    DELETE FROM
        thesistrace_product.daily_track_activation_reservations
    WHERE track_id = requested_track_id;
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.daily_track_cache_states(
    requested_track_ids text[]
)
RETURNS TABLE (
    track_id text,
    status text,
    fencing_token integer
)
LANGUAGE sql
STABLE
SECURITY DEFINER
STRICT
SET search_path = pg_catalog, thesistrace_product
AS $$
    SELECT track.id, track.status, track.fencing_token
    FROM thesistrace_product.daily_tracks AS track
    WHERE track.id = ANY(requested_track_ids)
    ORDER BY track.id
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.pending_working_cache_deletions(
    requested_track_id text
)
RETURNS TABLE (
    daily_track_id text,
    fencing_token integer,
    attempt_count integer,
    track_status text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
    SELECT deletion.daily_track_id,
           deletion.fencing_token,
           deletion.attempt_count,
           track.status
    FROM thesistrace_product.working_cache_deletions AS deletion
    LEFT JOIN thesistrace_product.daily_tracks AS track
      ON track.workspace_id = deletion.workspace_id
     AND track.id = deletion.daily_track_id
    WHERE deletion.status = 'pending'
      AND (
          requested_track_id IS NULL
          OR deletion.daily_track_id = requested_track_id
      )
    ORDER BY deletion.requested_at, deletion.daily_track_id
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.fail_working_cache_deletion(
    requested_track_id text,
    failure_message text
)
RETURNS boolean
LANGUAGE plpgsql
STRICT
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
BEGIN
    UPDATE thesistrace_product.working_cache_deletions
    SET attempt_count = attempt_count + 1,
        last_error = failure_message
    WHERE daily_track_id = requested_track_id
      AND status = 'pending';
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.complete_working_cache_deletion(
    requested_track_id text,
    deletion_completed_at text
)
RETURNS boolean
LANGUAGE plpgsql
STRICT
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
BEGIN
    UPDATE thesistrace_product.working_cache_deletions
    SET status = 'completed',
        attempt_count = attempt_count + 1,
        completed_at = deletion_completed_at,
        last_error = NULL
    WHERE daily_track_id = requested_track_id
      AND status = 'pending';
    RETURN FOUND;
END;
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.daily_track_activation_reservation_ids()
FROM PUBLIC;

REVOKE ALL ON FUNCTION
thesistrace_control.delete_daily_track_activation_reservation(text)
FROM PUBLIC;

REVOKE ALL ON FUNCTION
thesistrace_control.daily_track_cache_states(text[])
FROM PUBLIC;

REVOKE ALL ON FUNCTION
thesistrace_control.pending_working_cache_deletions(text)
FROM PUBLIC;

REVOKE ALL ON FUNCTION
thesistrace_control.fail_working_cache_deletion(text, text)
FROM PUBLIC;

REVOKE ALL ON FUNCTION
thesistrace_control.complete_working_cache_deletion(text, text)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
thesistrace_control.daily_track_activation_reservation_ids()
TO thesistrace_api, thesistrace_compute;

GRANT EXECUTE ON FUNCTION
thesistrace_control.delete_daily_track_activation_reservation(text)
TO thesistrace_api, thesistrace_compute;

GRANT EXECUTE ON FUNCTION
thesistrace_control.daily_track_cache_states(text[])
TO thesistrace_api, thesistrace_compute;

GRANT EXECUTE ON FUNCTION
thesistrace_control.pending_working_cache_deletions(text)
TO thesistrace_api, thesistrace_compute;

GRANT EXECUTE ON FUNCTION
thesistrace_control.fail_working_cache_deletion(text, text)
TO thesistrace_api, thesistrace_compute;

GRANT EXECUTE ON FUNCTION
thesistrace_control.complete_working_cache_deletion(text, text)
TO thesistrace_api, thesistrace_compute;
