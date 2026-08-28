REVOKE ALL ON SCHEMA auth FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA auth FROM PUBLIC;
REVOKE ALL ON SCHEMA auth FROM core_runtime;
REVOKE ALL ON ALL TABLES IN SCHEMA auth FROM core_runtime;

GRANT USAGE ON SCHEMA auth TO auth_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    auth."user",
    auth."session",
    auth."account",
    auth."verification",
    auth."rateLimit"
TO auth_runtime;
GRANT SELECT ON TABLE auth.schema_contract TO auth_runtime;
