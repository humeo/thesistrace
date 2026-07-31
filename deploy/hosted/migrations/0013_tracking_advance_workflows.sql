CREATE TABLE thesistrace_product.tracking_execution_outbox (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    daily_track_id text NOT NULL,
    advance_id text NOT NULL,
    status text NOT NULL
        CHECK (status IN ('pending', 'dispatched')),
    created_at text NOT NULL,
    dispatched_at text,
    UNIQUE (workspace_id, advance_id),
    FOREIGN KEY (workspace_id, daily_track_id)
        REFERENCES thesistrace_product.daily_tracks(workspace_id, id),
    FOREIGN KEY (workspace_id, advance_id)
        REFERENCES thesistrace_product.tracking_advances(workspace_id, id)
);

CREATE INDEX tracking_execution_outbox_pending_order
ON thesistrace_product.tracking_execution_outbox (created_at, id)
WHERE status = 'pending';

ALTER TABLE
thesistrace_product.tracking_execution_outbox
ENABLE ROW LEVEL SECURITY;

ALTER TABLE
thesistrace_product.tracking_execution_outbox
FORCE ROW LEVEL SECURITY;

CREATE POLICY personal_workspace_isolation
ON thesistrace_product.tracking_execution_outbox
USING (
    workspace_id = thesistrace_control.current_workspace_id()
)
WITH CHECK (
    workspace_id = thesistrace_control.current_workspace_id()
);

REVOKE ALL ON
thesistrace_product.tracking_execution_outbox
FROM PUBLIC, thesistrace_api, thesistrace_compute,
     thesistrace_data, thesistrace_relay;

GRANT SELECT, INSERT ON
thesistrace_product.tracking_execution_outbox
TO thesistrace_api, thesistrace_compute;

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

CREATE OR REPLACE FUNCTION
thesistrace_control.pending_execution_outbox(
    requested_limit integer
)
RETURNS TABLE (
    outbox_id text,
    workspace_id text,
    resource_kind text,
    resource_id text
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
    SELECT pending.outbox_id,
           pending.workspace_id,
           pending.resource_kind,
           pending.resource_id
    FROM (
        SELECT entry.id AS outbox_id,
               entry.workspace_id,
               entry.resource_kind,
               entry.resource_id,
               entry.created_at
        FROM thesistrace_product.execution_outbox AS entry
        WHERE entry.status = 'pending'

        UNION ALL

        SELECT entry.id AS outbox_id,
               NULL::text AS workspace_id,
               entry.resource_kind,
               entry.resource_id,
               entry.created_at
        FROM thesistrace_product.platform_execution_outbox AS entry
        WHERE entry.status = 'pending'

        UNION ALL

        SELECT 'tracking-release-outbox:' || trigger.release_id,
               NULL::text AS workspace_id,
               'tracking_release'::text AS resource_kind,
               trigger.release_id,
               trigger.created_at
        FROM thesistrace_product.tracking_release_triggers AS trigger
        WHERE trigger.status = 'pending'

        UNION ALL

        SELECT entry.id AS outbox_id,
               entry.workspace_id,
               'tracking_advance'::text AS resource_kind,
               entry.advance_id,
               entry.created_at
        FROM thesistrace_product.tracking_execution_outbox AS entry
        WHERE entry.status = 'pending'
    ) AS pending
    ORDER BY pending.created_at, pending.outbox_id
    LIMIT LEAST(GREATEST(requested_limit, 1), 100)
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.mark_execution_dispatched(
    requested_outbox_id text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
BEGIN
    UPDATE thesistrace_product.execution_outbox
    SET status = 'dispatched',
        dispatched_at = now()::text
    WHERE id = requested_outbox_id
      AND status = 'pending';
    IF FOUND THEN
        RETURN true;
    END IF;

    UPDATE thesistrace_product.platform_execution_outbox
    SET status = 'dispatched',
        dispatched_at = now()::text
    WHERE id = requested_outbox_id
      AND status = 'pending';
    IF FOUND THEN
        RETURN true;
    END IF;

    -- Tracking dispatch rows are delivery intents, not product history. Delete
    -- them after Temporal accepts the stable Workflow ID so daily fanout does
    -- not accumulate an unbounded dispatched tail.
    DELETE FROM thesistrace_product.tracking_execution_outbox
    WHERE id = requested_outbox_id
      AND status = 'pending';
    IF FOUND THEN
        RETURN true;
    END IF;

    UPDATE thesistrace_product.tracking_release_triggers
    SET status = 'dispatched'
    WHERE 'tracking-release-outbox:' || release_id =
          requested_outbox_id
      AND status = 'pending';
    RETURN FOUND;
END;
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.active_daily_track_scan_bound()
FROM PUBLIC;

REVOKE ALL ON FUNCTION
thesistrace_control.active_daily_track_refs(
    text, text, text, text, integer
)
FROM PUBLIC;

REVOKE ALL ON FUNCTION
thesistrace_control.pending_execution_outbox(integer)
FROM PUBLIC;

REVOKE ALL ON FUNCTION
thesistrace_control.mark_execution_dispatched(text)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
thesistrace_control.active_daily_track_scan_bound()
TO thesistrace_compute;

GRANT EXECUTE ON FUNCTION
thesistrace_control.active_daily_track_refs(
    text, text, text, text, integer
)
TO thesistrace_compute;

GRANT EXECUTE ON FUNCTION
thesistrace_control.pending_execution_outbox(integer)
TO thesistrace_relay;

GRANT EXECUTE ON FUNCTION
thesistrace_control.mark_execution_dispatched(text)
TO thesistrace_relay;
