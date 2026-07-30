CREATE TABLE IF NOT EXISTS thesistrace_control.management_audit_events (
    id text PRIMARY KEY,
    occurred_at timestamptz NOT NULL,
    actor text NOT NULL,
    action text NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('succeeded', 'rejected')),
    reason_code text,
    subject_type text NOT NULL,
    subject_id text NOT NULL,
    details_json jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS thesistrace_control.source_authorization_declarations (
    id text PRIMARY KEY,
    source text NOT NULL,
    intended_scope text NOT NULL,
    actor text NOT NULL,
    declared_at timestamptz NOT NULL,
    audit_event_id text NOT NULL
        REFERENCES thesistrace_control.management_audit_events(id)
);

CREATE OR REPLACE FUNCTION thesistrace_control.reject_management_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'management history is immutable';
END;
$$;

DROP TRIGGER IF EXISTS management_audit_events_immutable
ON thesistrace_control.management_audit_events;
CREATE TRIGGER management_audit_events_immutable
BEFORE UPDATE OR DELETE ON thesistrace_control.management_audit_events
FOR EACH ROW EXECUTE FUNCTION thesistrace_control.reject_management_history_mutation();

DROP TRIGGER IF EXISTS source_authorizations_immutable
ON thesistrace_control.source_authorization_declarations;
CREATE TRIGGER source_authorizations_immutable
BEFORE UPDATE OR DELETE ON thesistrace_control.source_authorization_declarations
FOR EACH ROW EXECUTE FUNCTION thesistrace_control.reject_management_history_mutation();
