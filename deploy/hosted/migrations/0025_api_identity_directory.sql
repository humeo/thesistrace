REVOKE ALL ON TABLE auth.users FROM PUBLIC, thesistrace_api;
GRANT USAGE ON SCHEMA auth TO thesistrace_api;
GRANT SELECT (id, email, email_verified)
ON TABLE auth.users TO thesistrace_api;
