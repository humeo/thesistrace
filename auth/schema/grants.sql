REVOKE ALL ON SCHEMA auth FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA auth FROM PUBLIC;
REVOKE ALL ON FUNCTION auth.enforce_active_session_owner() FROM PUBLIC;
REVOKE ALL ON SCHEMA auth FROM core_runtime;
REVOKE ALL ON ALL TABLES IN SCHEMA auth FROM core_runtime;

GRANT USAGE ON SCHEMA auth TO auth_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    auth."user",
    auth."session",
    auth."account",
    auth."verification",
    auth."rateLimit",
    auth.operator_assignment,
    auth.operator_proof,
    auth.researcher_invitation,
    auth.password_reset,
    auth.security_audit,
    auth.auth_secret_contract
TO auth_runtime;
GRANT SELECT ON TABLE auth.schema_contract TO auth_runtime;
GRANT EXECUTE ON FUNCTION auth.enforce_active_session_owner() TO auth_runtime;
