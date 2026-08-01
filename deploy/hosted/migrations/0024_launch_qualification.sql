CREATE TABLE IF NOT EXISTS thesistrace_control.launch_qualifications (
    id text PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('passed', 'failed')),
    release_bundle_id text NOT NULL,
    evidence_sha256 text NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    evidence_json jsonb NOT NULL,
    failures_json jsonb NOT NULL,
    recorded_by text NOT NULL,
    measured_at timestamptz NOT NULL,
    audit_event_id text NOT NULL UNIQUE
        REFERENCES thesistrace_control.management_audit_events(id)
);

CREATE OR REPLACE FUNCTION thesistrace_control.reject_launch_qualification_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'launch qualifications are immutable';
END
$$;

DROP TRIGGER IF EXISTS launch_qualifications_no_mutation
ON thesistrace_control.launch_qualifications;
CREATE TRIGGER launch_qualifications_no_mutation
BEFORE UPDATE OR DELETE ON thesistrace_control.launch_qualifications
FOR EACH ROW EXECUTE FUNCTION
    thesistrace_control.reject_launch_qualification_mutation();

REVOKE ALL ON thesistrace_control.launch_qualifications FROM PUBLIC;
