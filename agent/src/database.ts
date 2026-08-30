import { Pool } from "pg";

const DATABASE_OPERATION_TIMEOUT_MS = 2_000;

export function createAgentPool(databaseUrl: string): Pool {
  return new Pool({
    connectionString: databaseUrl,
    connectionTimeoutMillis: DATABASE_OPERATION_TIMEOUT_MS,
    max: 10,
    options: "-c search_path=pg_catalog",
  });
}

export function createAgentReadinessPool(databaseUrl: string): Pool {
  return new Pool({
    connectionString: databaseUrl,
    connectionTimeoutMillis: DATABASE_OPERATION_TIMEOUT_MS,
    max: 1,
    options: "-c search_path=pg_catalog",
    query_timeout: DATABASE_OPERATION_TIMEOUT_MS,
  });
}

export function createAgentInitializerPool(databaseUrl: string): Pool {
  return new Pool({
    connectionString: databaseUrl,
    connectionTimeoutMillis: DATABASE_OPERATION_TIMEOUT_MS,
    max: 1,
    options: "-c search_path=pg_catalog",
  });
}
