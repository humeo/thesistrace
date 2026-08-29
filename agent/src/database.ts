import { Pool } from "pg";

export function createAgentPool(databaseUrl: string): Pool {
  return new Pool({
    connectionString: databaseUrl,
    max: 10,
    options: "-c search_path=pg_catalog",
  });
}

export function createAgentInitializerPool(databaseUrl: string): Pool {
  return new Pool({
    connectionString: databaseUrl,
    max: 1,
    options: "-c search_path=pg_catalog",
  });
}
