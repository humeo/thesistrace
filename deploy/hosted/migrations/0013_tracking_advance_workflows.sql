CREATE OR REPLACE FUNCTION
thesistrace_control.active_daily_track_scan_bound()
RETURNS TABLE (
    workspace_id text,
    track_id text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
    SELECT track.workspace_id, track.id
    FROM thesistrace_product.daily_tracks AS track
    WHERE track.status = 'active'
    ORDER BY track.workspace_id DESC, track.id DESC
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.active_daily_track_refs(
    after_workspace_id text DEFAULT NULL,
    after_track_id text DEFAULT NULL,
    through_workspace_id text DEFAULT NULL,
    through_track_id text DEFAULT NULL,
    requested_limit integer DEFAULT 101
)
RETURNS TABLE (
    workspace_id text,
    track_id text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
    SELECT track.workspace_id, track.id
    FROM thesistrace_product.daily_tracks AS track
    WHERE track.status = 'active'
      AND (
          after_workspace_id IS NULL
          OR (track.workspace_id, track.id) >
             (after_workspace_id, after_track_id)
      )
      AND (
          through_workspace_id IS NULL
          OR (track.workspace_id, track.id) <=
             (through_workspace_id, through_track_id)
      )
    ORDER BY track.workspace_id, track.id
    LIMIT LEAST(GREATEST(requested_limit, 1), 101)
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.active_daily_track_scan_bound()
FROM PUBLIC;

REVOKE ALL ON FUNCTION
thesistrace_control.active_daily_track_refs(
    text, text, text, text, integer
)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
thesistrace_control.active_daily_track_scan_bound()
TO thesistrace_compute;

GRANT EXECUTE ON FUNCTION
thesistrace_control.active_daily_track_refs(
    text, text, text, text, integer
)
TO thesistrace_compute;
