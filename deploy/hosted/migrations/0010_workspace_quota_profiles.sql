CREATE TABLE IF NOT EXISTS thesistrace_control.workspace_quota_profiles (
    workspace_id text PRIMARY KEY
        REFERENCES thesistrace_control.personal_workspaces(id)
        ON DELETE CASCADE,
    max_active_daily_tracks integer NOT NULL
        CHECK (max_active_daily_tracks BETWEEN 1 AND 10),
    max_nonterminal_user_compute_jobs integer NOT NULL
        CHECK (max_nonterminal_user_compute_jobs > 0),
    max_private_storage_bytes bigint NOT NULL
        CHECK (max_private_storage_bytes > 0),
    updated_at timestamptz NOT NULL,
    updated_by text NOT NULL
);

INSERT INTO thesistrace_control.workspace_quota_profiles (
    workspace_id,
    max_active_daily_tracks,
    max_nonterminal_user_compute_jobs,
    max_private_storage_bytes,
    updated_at,
    updated_by
)
SELECT id, 10, 8, 10737418240, created_at, 'system:migration'
FROM thesistrace_control.personal_workspaces
ON CONFLICT (workspace_id) DO NOTHING;

CREATE OR REPLACE FUNCTION thesistrace_control.create_default_workspace_quota_profile()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
BEGIN
    INSERT INTO thesistrace_control.workspace_quota_profiles (
        workspace_id,
        max_active_daily_tracks,
        max_nonterminal_user_compute_jobs,
        max_private_storage_bytes,
        updated_at,
        updated_by
    )
    VALUES (NEW.id, 10, 8, 10737418240, NEW.created_at, 'system:provisioning')
    ON CONFLICT (workspace_id) DO NOTHING;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.create_default_workspace_quota_profile()
FROM PUBLIC;

DROP TRIGGER IF EXISTS personal_workspace_default_quota_profile
ON thesistrace_control.personal_workspaces;
CREATE TRIGGER personal_workspace_default_quota_profile
AFTER INSERT ON thesistrace_control.personal_workspaces
FOR EACH ROW
EXECUTE FUNCTION thesistrace_control.create_default_workspace_quota_profile();

ALTER TABLE thesistrace_control.workspace_quota_profiles
ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS personal_workspace_quota_read
ON thesistrace_control.workspace_quota_profiles;
CREATE POLICY personal_workspace_quota_read
ON thesistrace_control.workspace_quota_profiles
FOR SELECT
USING (workspace_id = thesistrace_control.current_workspace_id());

REVOKE ALL ON thesistrace_control.workspace_quota_profiles FROM PUBLIC;
REVOKE ALL ON thesistrace_control.workspace_quota_profiles
FROM thesistrace_api, thesistrace_compute, thesistrace_data;
GRANT SELECT ON thesistrace_control.workspace_quota_profiles
TO thesistrace_api, thesistrace_compute;

CREATE TABLE IF NOT EXISTS thesistrace_product.user_compute_admissions (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    resource_kind text NOT NULL CHECK (resource_kind <> ''),
    resource_id text NOT NULL CHECK (resource_id <> ''),
    admitted_at text NOT NULL,
    completed_at text,
    PRIMARY KEY (workspace_id, resource_kind, resource_id)
);

CREATE INDEX IF NOT EXISTS active_user_compute_admissions
ON thesistrace_product.user_compute_admissions (workspace_id, admitted_at)
WHERE completed_at IS NULL;

INSERT INTO thesistrace_product.user_compute_admissions (
    workspace_id,
    resource_kind,
    resource_id,
    admitted_at,
    completed_at
)
SELECT workspace_id, 'research_run', id, created_at, NULL
FROM thesistrace_product.research_runs
WHERE status IN ('queued', 'running')
ON CONFLICT (workspace_id, resource_kind, resource_id) DO NOTHING;

ALTER TABLE thesistrace_product.user_compute_admissions
ENABLE ROW LEVEL SECURITY;
ALTER TABLE thesistrace_product.user_compute_admissions
FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS personal_workspace_isolation
ON thesistrace_product.user_compute_admissions;
CREATE POLICY personal_workspace_isolation
ON thesistrace_product.user_compute_admissions
USING (workspace_id = thesistrace_control.current_workspace_id())
WITH CHECK (workspace_id = thesistrace_control.current_workspace_id());

REVOKE ALL ON thesistrace_product.user_compute_admissions FROM PUBLIC;
REVOKE ALL ON thesistrace_product.user_compute_admissions
FROM thesistrace_api, thesistrace_compute, thesistrace_data;
GRANT SELECT, INSERT, UPDATE ON
    thesistrace_product.user_compute_admissions
TO thesistrace_api, thesistrace_compute;
