GRANT USAGE ON SCHEMA thesistrace_control TO thesistrace_api;

REVOKE ALL ON TABLE
    thesistrace_control.management_audit_events,
    thesistrace_control.personal_workspaces,
    thesistrace_control.product_users,
    thesistrace_control.registration_invitations
FROM PUBLIC, thesistrace_api;

GRANT INSERT ON TABLE
    thesistrace_control.management_audit_events
TO thesistrace_api;

GRANT SELECT, INSERT ON TABLE
    thesistrace_control.personal_workspaces,
    thesistrace_control.product_users
TO thesistrace_api;

GRANT SELECT, UPDATE ON TABLE
    thesistrace_control.registration_invitations
TO thesistrace_api;
