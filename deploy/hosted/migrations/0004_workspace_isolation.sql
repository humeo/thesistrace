DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'thesistrace_api') THEN
        CREATE ROLE thesistrace_api
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'thesistrace_compute') THEN
        CREATE ROLE thesistrace_compute
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'thesistrace_data') THEN
        CREATE ROLE thesistrace_data
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

GRANT thesistrace_api, thesistrace_compute, thesistrace_data TO CURRENT_USER;

CREATE SCHEMA IF NOT EXISTS thesistrace_product;
REVOKE ALL ON SCHEMA thesistrace_product FROM PUBLIC;
GRANT USAGE ON SCHEMA thesistrace_product
TO thesistrace_api, thesistrace_compute, thesistrace_data;

CREATE TABLE IF NOT EXISTS thesistrace_control.api_workspace_contexts (
    backend_pid integer PRIMARY KEY,
    transaction_id bigint NOT NULL,
    workspace_id text NOT NULL
        REFERENCES thesistrace_control.personal_workspaces(id)
        ON DELETE CASCADE
);
REVOKE ALL ON thesistrace_control.api_workspace_contexts FROM PUBLIC;
REVOKE ALL ON thesistrace_control.api_workspace_contexts
FROM thesistrace_api, thesistrace_compute, thesistrace_data;

CREATE OR REPLACE FUNCTION thesistrace_control.set_api_identity(
    verified_insforge_subject text
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
DECLARE
    resolved_workspace_id text;
BEGIN
    SELECT workspace.id
    INTO resolved_workspace_id
    FROM thesistrace_control.product_users AS product_user
    JOIN thesistrace_control.personal_workspaces AS workspace
      ON workspace.user_id = product_user.id
    WHERE product_user.insforge_subject = verified_insforge_subject;

    IF resolved_workspace_id IS NULL THEN
        RAISE EXCEPTION 'verified identity has no Personal Workspace'
            USING ERRCODE = '42501';
    END IF;

    INSERT INTO thesistrace_control.api_workspace_contexts (
        backend_pid,
        transaction_id,
        workspace_id
    )
    VALUES (pg_backend_pid(), txid_current(), resolved_workspace_id)
    ON CONFLICT (backend_pid) DO UPDATE
    SET transaction_id = excluded.transaction_id,
        workspace_id = excluded.workspace_id;

    RETURN resolved_workspace_id;
END;
$$;

CREATE OR REPLACE FUNCTION thesistrace_control.set_service_workspace(
    requested_workspace_id text
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM thesistrace_control.personal_workspaces
        WHERE id = requested_workspace_id
    ) THEN
        RAISE EXCEPTION 'Personal Workspace not found'
            USING ERRCODE = '42501';
    END IF;

    INSERT INTO thesistrace_control.api_workspace_contexts (
        backend_pid,
        transaction_id,
        workspace_id
    )
    VALUES (pg_backend_pid(), txid_current(), requested_workspace_id)
    ON CONFLICT (backend_pid) DO UPDATE
    SET transaction_id = excluded.transaction_id,
        workspace_id = excluded.workspace_id;

    RETURN requested_workspace_id;
END;
$$;

CREATE OR REPLACE FUNCTION thesistrace_control.current_workspace_id()
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
    SELECT workspace_id
    FROM thesistrace_control.api_workspace_contexts
    WHERE backend_pid = pg_backend_pid()
      AND transaction_id = txid_current()
$$;

REVOKE ALL ON FUNCTION thesistrace_control.set_api_identity(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION thesistrace_control.set_service_workspace(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION thesistrace_control.current_workspace_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION thesistrace_control.set_api_identity(text)
TO thesistrace_api;
GRANT EXECUTE ON FUNCTION thesistrace_control.set_service_workspace(text)
TO thesistrace_compute;
GRANT EXECUTE ON FUNCTION thesistrace_control.current_workspace_id()
TO thesistrace_api, thesistrace_compute;

CREATE TABLE IF NOT EXISTS thesistrace_product.workspace (
    singleton integer PRIMARY KEY CHECK (singleton = 1),
    installation_id text NOT NULL,
    created_at text NOT NULL
);

INSERT INTO thesistrace_product.workspace (singleton, installation_id, created_at)
VALUES (1, gen_random_uuid()::text, now()::text)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS thesistrace_product.worker_heartbeat (
    singleton integer PRIMARY KEY CHECK (singleton = 1),
    heartbeat_at text NOT NULL
);

CREATE TABLE IF NOT EXISTS thesistrace_product.dataset_releases (
    id text PRIMARY KEY,
    manifest_json text NOT NULL,
    created_at text NOT NULL
);

CREATE TABLE IF NOT EXISTS thesistrace_product.dataset_release_pointer (
    singleton integer PRIMARY KEY CHECK (singleton = 1),
    release_id text NOT NULL
        REFERENCES thesistrace_product.dataset_releases(id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.publication_idempotency (
    idempotency_key text PRIMARY KEY,
    release_id text NOT NULL
        REFERENCES thesistrace_product.dataset_releases(id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.research_definition_drafts (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    content_json text NOT NULL,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    UNIQUE (workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.research_definitions (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    draft_id text NOT NULL,
    version integer NOT NULL,
    content_json text NOT NULL,
    content_hash text NOT NULL,
    created_at text NOT NULL,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, draft_id, version),
    FOREIGN KEY (workspace_id, draft_id)
        REFERENCES thesistrace_product.research_definition_drafts(workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.research_runs (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    definition_version_id text NOT NULL,
    dataset_release_id text NOT NULL
        REFERENCES thesistrace_product.dataset_releases(id),
    status text NOT NULL,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    started_at text,
    completed_at text,
    result_bundle_id text,
    result_manifest_sha256 text,
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, definition_version_id)
        REFERENCES thesistrace_product.research_definitions(workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.research_run_idempotency (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    idempotency_key text NOT NULL,
    run_id text NOT NULL,
    PRIMARY KEY (workspace_id, idempotency_key),
    FOREIGN KEY (workspace_id, run_id)
        REFERENCES thesistrace_product.research_runs(workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.research_run_attempts (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    run_id text NOT NULL,
    ordinal integer NOT NULL,
    status text NOT NULL,
    started_at text NOT NULL,
    heartbeat_at text NOT NULL,
    completed_at text,
    diagnostic_json text,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, run_id, ordinal),
    FOREIGN KEY (workspace_id, run_id)
        REFERENCES thesistrace_product.research_runs(workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.daily_tracks (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    seed_run_id text NOT NULL,
    definition_version_id text NOT NULL,
    definition_content_hash text NOT NULL,
    activation_release_id text NOT NULL
        REFERENCES thesistrace_product.dataset_releases(id),
    origin_session text NOT NULL,
    numeric_execution_contract text NOT NULL,
    status text NOT NULL,
    current_generation_id text NOT NULL,
    head_checkpoint_id text NOT NULL,
    created_at text NOT NULL,
    stopped_at text,
    fencing_token integer NOT NULL DEFAULT 0,
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, seed_run_id)
        REFERENCES thesistrace_product.research_runs(workspace_id, id),
    FOREIGN KEY (workspace_id, definition_version_id)
        REFERENCES thesistrace_product.research_definitions(workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.daily_track_activation_idempotency (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    idempotency_key text NOT NULL,
    daily_track_id text NOT NULL,
    PRIMARY KEY (workspace_id, idempotency_key),
    FOREIGN KEY (workspace_id, daily_track_id)
        REFERENCES thesistrace_product.daily_tracks(workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.tracking_generations (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    daily_track_id text NOT NULL,
    ordinal integer NOT NULL,
    calculation_kernel text NOT NULL,
    numeric_execution_contract text NOT NULL,
    basis_dataset_release_id text NOT NULL
        REFERENCES thesistrace_product.dataset_releases(id),
    supersedes_generation_id text,
    supersedes_head_checkpoint_id text,
    reason text NOT NULL,
    created_at text NOT NULL,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, daily_track_id, ordinal),
    FOREIGN KEY (workspace_id, daily_track_id)
        REFERENCES thesistrace_product.daily_tracks(workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.tracking_checkpoints (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    daily_track_id text NOT NULL,
    generation_id text NOT NULL,
    predecessor_checkpoint_id text,
    target_dataset_release_id text NOT NULL
        REFERENCES thesistrace_product.dataset_releases(id),
    manifest_sha256 text NOT NULL,
    created_at text NOT NULL,
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, daily_track_id)
        REFERENCES thesistrace_product.daily_tracks(workspace_id, id),
    FOREIGN KEY (workspace_id, generation_id)
        REFERENCES thesistrace_product.tracking_generations(workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.tracking_advances (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    daily_track_id text NOT NULL,
    generation_id text NOT NULL,
    target_dataset_release_id text NOT NULL
        REFERENCES thesistrace_product.dataset_releases(id),
    correction_boundary_json text,
    status text NOT NULL,
    checkpoint_id text,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    UNIQUE (workspace_id, id),
    UNIQUE (
        workspace_id,
        daily_track_id,
        generation_id,
        target_dataset_release_id
    ),
    FOREIGN KEY (workspace_id, daily_track_id)
        REFERENCES thesistrace_product.daily_tracks(workspace_id, id),
    FOREIGN KEY (workspace_id, generation_id)
        REFERENCES thesistrace_product.tracking_generations(workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.tracking_advance_attempts (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    advance_id text NOT NULL,
    ordinal integer NOT NULL,
    status text NOT NULL,
    started_at text NOT NULL,
    completed_at text,
    diagnostic_json text,
    fencing_token integer NOT NULL DEFAULT 0,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, advance_id, ordinal),
    FOREIGN KEY (workspace_id, advance_id)
        REFERENCES thesistrace_product.tracking_advances(workspace_id, id)
);

CREATE TABLE IF NOT EXISTS thesistrace_product.working_cache_deletions (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    daily_track_id text NOT NULL,
    fencing_token integer NOT NULL,
    status text NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0,
    requested_at text NOT NULL,
    completed_at text,
    last_error text,
    PRIMARY KEY (workspace_id, daily_track_id),
    FOREIGN KEY (workspace_id, daily_track_id)
        REFERENCES thesistrace_product.daily_tracks(workspace_id, id)
);

DO $$
DECLARE
    private_table text;
BEGIN
    FOREACH private_table IN ARRAY ARRAY[
        'research_definition_drafts',
        'research_definitions',
        'research_runs',
        'research_run_idempotency',
        'research_run_attempts',
        'daily_tracks',
        'daily_track_activation_idempotency',
        'tracking_generations',
        'tracking_checkpoints',
        'tracking_advances',
        'tracking_advance_attempts',
        'working_cache_deletions'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE thesistrace_product.%I ENABLE ROW LEVEL SECURITY',
            private_table
        );
        EXECUTE format(
            'ALTER TABLE thesistrace_product.%I FORCE ROW LEVEL SECURITY',
            private_table
        );
        EXECUTE format(
            'DROP POLICY IF EXISTS personal_workspace_isolation ON thesistrace_product.%I',
            private_table
        );
        EXECUTE format(
            'CREATE POLICY personal_workspace_isolation ON thesistrace_product.%I '
            'USING (workspace_id = thesistrace_control.current_workspace_id()) '
            'WITH CHECK (workspace_id = thesistrace_control.current_workspace_id())',
            private_table
        );
    END LOOP;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA thesistrace_product FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA thesistrace_product
FROM thesistrace_api, thesistrace_compute, thesistrace_data;

GRANT SELECT ON
    thesistrace_product.workspace,
    thesistrace_product.worker_heartbeat,
    thesistrace_product.dataset_releases,
    thesistrace_product.dataset_release_pointer
TO thesistrace_api, thesistrace_compute, thesistrace_data;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    thesistrace_product.research_definition_drafts,
    thesistrace_product.research_definitions,
    thesistrace_product.research_runs,
    thesistrace_product.research_run_idempotency,
    thesistrace_product.research_run_attempts,
    thesistrace_product.daily_tracks,
    thesistrace_product.daily_track_activation_idempotency,
    thesistrace_product.tracking_generations,
    thesistrace_product.tracking_checkpoints,
    thesistrace_product.tracking_advances,
    thesistrace_product.tracking_advance_attempts,
    thesistrace_product.working_cache_deletions
TO thesistrace_api;

GRANT SELECT, INSERT, UPDATE ON
    thesistrace_product.research_runs,
    thesistrace_product.research_run_attempts,
    thesistrace_product.daily_tracks,
    thesistrace_product.tracking_generations,
    thesistrace_product.tracking_checkpoints,
    thesistrace_product.tracking_advances,
    thesistrace_product.tracking_advance_attempts,
    thesistrace_product.working_cache_deletions
TO thesistrace_compute;

GRANT SELECT, INSERT, UPDATE ON
    thesistrace_product.worker_heartbeat,
    thesistrace_product.dataset_releases,
    thesistrace_product.dataset_release_pointer,
    thesistrace_product.publication_idempotency
TO thesistrace_data;
