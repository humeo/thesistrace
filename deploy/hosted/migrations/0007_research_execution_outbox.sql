DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'thesistrace_relay') THEN
        CREATE ROLE thesistrace_relay
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

GRANT thesistrace_relay TO CURRENT_USER;
GRANT USAGE ON SCHEMA thesistrace_control TO thesistrace_relay;

CREATE TABLE thesistrace_product.execution_outbox (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    resource_kind text NOT NULL CHECK (resource_kind = 'research_run'),
    resource_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'dispatched')),
    created_at text NOT NULL,
    dispatched_at text,
    UNIQUE (workspace_id, resource_kind, resource_id),
    FOREIGN KEY (workspace_id, resource_id)
        REFERENCES thesistrace_product.research_runs(workspace_id, id)
);

ALTER TABLE thesistrace_product.execution_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE thesistrace_product.execution_outbox FORCE ROW LEVEL SECURITY;

CREATE POLICY personal_workspace_isolation
ON thesistrace_product.execution_outbox
USING (workspace_id = thesistrace_control.current_workspace_id())
WITH CHECK (workspace_id = thesistrace_control.current_workspace_id());

REVOKE ALL ON thesistrace_product.execution_outbox FROM PUBLIC;
REVOKE ALL ON thesistrace_product.execution_outbox
FROM thesistrace_api, thesistrace_compute, thesistrace_data, thesistrace_relay;
GRANT SELECT, INSERT ON thesistrace_product.execution_outbox TO thesistrace_api;

CREATE OR REPLACE FUNCTION thesistrace_control.pending_execution_outbox(
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
    SELECT
        entry.id,
        entry.workspace_id,
        entry.resource_kind,
        entry.resource_id
    FROM thesistrace_product.execution_outbox AS entry
    WHERE entry.status = 'pending'
    ORDER BY entry.created_at, entry.id
    LIMIT LEAST(GREATEST(requested_limit, 1), 100)
$$;

CREATE OR REPLACE FUNCTION thesistrace_control.mark_execution_dispatched(
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
    RETURN FOUND;
END;
$$;

REVOKE ALL ON FUNCTION thesistrace_control.pending_execution_outbox(integer)
FROM PUBLIC;
REVOKE ALL ON FUNCTION thesistrace_control.mark_execution_dispatched(text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION thesistrace_control.pending_execution_outbox(integer)
TO thesistrace_relay;
GRANT EXECUTE ON FUNCTION thesistrace_control.mark_execution_dispatched(text)
TO thesistrace_relay;
