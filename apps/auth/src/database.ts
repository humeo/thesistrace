import { Pool } from "pg";

export function createAuthPool(databaseUrl: string): Pool {
  return new Pool({
    application_name: "thesistrace_auth",
    connectionString: databaseUrl,
    connectionTimeoutMillis: 2_000,
    idle_in_transaction_session_timeout: 5_000,
    lock_timeout: 1_000,
    max: 10,
    options: "-c search_path=auth",
    query_timeout: 3_000,
    statement_timeout: 2_500,
  });
}

export function createAuthCoordinationPool(databaseUrl: string): Pool {
  return new Pool({
    application_name: "thesistrace_auth_coordination",
    connectionString: databaseUrl,
    connectionTimeoutMillis: 10_000,
    idle_in_transaction_session_timeout: 10_000,
    lock_timeout: 3_000,
    max: 2,
    options: "-c search_path=auth",
    query_timeout: 10_000,
    statement_timeout: 8_000,
  });
}

export function createAuthInitializerPool(databaseUrl: string): Pool {
  return new Pool({
    application_name: "thesistrace_auth_initializer",
    connectionString: databaseUrl,
    connectionTimeoutMillis: 5_000,
    idle_in_transaction_session_timeout: 30_000,
    lock_timeout: 2_000,
    max: 1,
    options: "-c search_path=pg_catalog",
    query_timeout: 35_000,
    statement_timeout: 30_000,
  });
}
