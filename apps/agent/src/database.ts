import { Pool } from "pg";

import { diagnoseAgentFailure } from "./failure.js";

const DATABASE_OPERATION_TIMEOUT_MS = 2_000;

export function createAgentPool(databaseUrl: string): Pool {
  return withIdleClientErrorHandler(new Pool({
    connectionString: databaseUrl,
    connectionTimeoutMillis: DATABASE_OPERATION_TIMEOUT_MS,
    max: 10,
    options: "-c search_path=pg_catalog",
  }));
}

export function createAgentReadinessPool(databaseUrl: string): Pool {
  return withIdleClientErrorHandler(new Pool({
    connectionString: databaseUrl,
    connectionTimeoutMillis: DATABASE_OPERATION_TIMEOUT_MS,
    max: 1,
    options: "-c search_path=pg_catalog",
    query_timeout: DATABASE_OPERATION_TIMEOUT_MS,
  }));
}

export function createAgentInitializerPool(databaseUrl: string): Pool {
  return withIdleClientErrorHandler(new Pool({
    connectionString: databaseUrl,
    connectionTimeoutMillis: DATABASE_OPERATION_TIMEOUT_MS,
    max: 1,
    options: "-c search_path=pg_catalog",
  }));
}

function withIdleClientErrorHandler(pool: Pool): Pool {
  pool.on("error", (error: Error) => {
    process.stderr.write(
      `${JSON.stringify({
        code: "AGENT_DATABASE_UNAVAILABLE",
        event: "agent_database_pool_error",
        ...diagnoseAgentFailure(error),
      })}\n`,
    );
  });
  return pool;
}
