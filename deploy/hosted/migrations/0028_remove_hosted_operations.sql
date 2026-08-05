-- Historical migrations are immutable. This forward contraction removes the
-- database objects that only supported the retired Hosted operations runtime.

DROP FUNCTION IF EXISTS thesistrace_control.operator_health_snapshot();
DROP FUNCTION IF EXISTS
    thesistrace_control.dataset_release_matches_expected_session();

DROP TRIGGER IF EXISTS reject_dataset_publication_during_maintenance
ON thesistrace_product.dataset_publications;
DROP FUNCTION IF EXISTS
    thesistrace_control.reject_dataset_publication_during_maintenance();
DROP FUNCTION IF EXISTS thesistrace_control.maintenance_enabled();
DROP FUNCTION IF EXISTS
    thesistrace_control.set_platform_maintenance(boolean);
DROP TABLE IF EXISTS thesistrace_control.platform_maintenance;

DROP TABLE IF EXISTS thesistrace_control.capacity_qualifications CASCADE;
DROP FUNCTION IF EXISTS
    thesistrace_control.reject_capacity_qualification_mutation();
DROP TABLE IF EXISTS thesistrace_control.launch_qualifications CASCADE;
DROP FUNCTION IF EXISTS
    thesistrace_control.reject_launch_qualification_mutation();

-- Private object indexing now uses the deployment-neutral publication index.
-- Remove the old per-workspace quota policy but retain the canonical object
-- identity and reference tables until Hosted persistence itself is retired.
DROP TRIGGER IF EXISTS personal_workspace_default_quota_profile
ON thesistrace_control.personal_workspaces;
DROP FUNCTION IF EXISTS
    thesistrace_control.create_default_workspace_quota_profile();
DROP FUNCTION IF EXISTS
    thesistrace_control.commit_workspace_storage_references(text, text, jsonb);
DROP TABLE IF EXISTS thesistrace_control.workspace_quota_profiles;

DROP OWNED BY thesistrace_health;
DROP ROLE thesistrace_health;

-- The remaining deployment-time identity and publication commands run through
-- one private, one-shot container with a narrow database identity.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'thesistrace_management'
    ) THEN
        CREATE ROLE thesistrace_management NOLOGIN NOINHERIT;
    END IF;
END
$$;

GRANT thesistrace_management TO CURRENT_USER;
GRANT USAGE ON SCHEMA thesistrace_control, thesistrace_product
TO thesistrace_management;
GRANT SELECT, INSERT ON TABLE
    thesistrace_control.management_audit_events,
    thesistrace_control.source_authorization_declarations
TO thesistrace_management;
GRANT SELECT, INSERT, UPDATE ON TABLE
    thesistrace_control.registration_invitations
TO thesistrace_management;
GRANT SELECT, INSERT ON TABLE thesistrace_product.dataset_publications
TO thesistrace_management;
