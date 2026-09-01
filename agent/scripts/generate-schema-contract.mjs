import { readFile, writeFile } from "node:fs/promises";

import pg from "pg";

import { collectAgentSchemaCatalog } from "../dist/schema-contract.js";

const ownerDatabaseUrl = process.env.THESISTRACE_AGENT_TEST_OWNER_DATABASE_URL;
if (
  process.env.THESISTRACE_AGENT_SCHEMA_GENERATION !== "isolated"
  || ownerDatabaseUrl === undefined
) {
  throw new Error(
    "Schema generation requires an isolated PostgreSQL URL and THESISTRACE_AGENT_SCHEMA_GENERATION=isolated",
  );
}

const schemaUrl = new URL("../schema/schema.sql", import.meta.url);
const artifactUrl = new URL("../schema/catalog-contract.json", import.meta.url);
const pool = new pg.Pool({ connectionString: ownerDatabaseUrl, max: 1 });
const client = await pool.connect();
let catalog;
try {
  await client.query("BEGIN");
  await client.query("SET LOCAL search_path = pg_catalog");
  const identity = await client.query("SELECT current_user");
  if (identity.rows[0]?.current_user !== "thesistrace_owner") {
    throw new Error("Schema contract must be generated as thesistrace_owner");
  }
  const scope = await client.query(
    "SELECT pg_catalog.to_regnamespace('agent') IS NULL AS absent",
  );
  if (scope.rows[0]?.absent !== true) {
    throw new Error("Schema contract generation database is not empty");
  }
  await client.query("CREATE SCHEMA agent AUTHORIZATION thesistrace_owner");
  await client.query(await readFile(schemaUrl, "utf8"));
  catalog = await collectAgentSchemaCatalog(client);
  await client.query("ROLLBACK");
} catch (error) {
  await client.query("ROLLBACK").catch(() => undefined);
  throw error;
} finally {
  client.release();
  await pool.end();
}

await writeFile(artifactUrl, `${JSON.stringify(catalog, null, 2)}\n`, "utf8");
