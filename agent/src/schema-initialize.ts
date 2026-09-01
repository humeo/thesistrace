import { readFile } from "node:fs/promises";

import type { Pool, PoolClient } from "pg";

import {
  AgentSchemaContractError,
  schemaContractErrorFrom,
} from "./failure.js";
import {
  assertExactCatalog,
  catalogFingerprint,
  collectAgentSchemaCatalog,
  loadExpectedCatalog,
  verifyAgentSchema,
} from "./schema-contract.js";

const schemaSqlUrl = new URL("../schema/schema.sql", import.meta.url);
const grantsSqlUrl = new URL("../schema/grants.sql", import.meta.url);

export async function initializeAgentSchema(database: Pool): Promise<void> {
  const client = await database.connect();
  try {
    await client.query("BEGIN");
    await client.query("SET LOCAL search_path = pg_catalog");
    await client.query("SET LOCAL lock_timeout = '2000ms'");
    await client.query("SET LOCAL statement_timeout = '30000ms'");
    await client.query("SET LOCAL idle_in_transaction_session_timeout = '30000ms'");
    await client.query(
      "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('thesistrace:agent-schema', 0))",
    );
    await assertOwnerRole(client);

    const state = await agentScopeState(client);
    if (state === "absent") {
      await client.query("CREATE SCHEMA agent AUTHORIZATION thesistrace_owner");
      await installEmptyScope(client);
    } else if (state === "empty") {
      await installEmptyScope(client);
    } else {
      await verifyAgentSchema(client);
    }

    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw schemaContractErrorFrom(error);
  } finally {
    client.release();
  }
}

async function installEmptyScope(client: PoolClient): Promise<void> {
  const [schemaSql, grantsSql, expected] = await Promise.all([
    readContractFile(schemaSqlUrl),
    readContractFile(grantsSqlUrl),
    loadExpectedCatalog(),
  ]);
  await client.query(schemaSql);
  assertExactCatalog(expected, await collectAgentSchemaCatalog(client));
  await client.query(
    `INSERT INTO agent.schema_contract (singleton, schema_fingerprint)
     VALUES (TRUE, $1)`,
    [catalogFingerprint(expected)],
  );
  await client.query(grantsSql);
  await verifyAgentSchema(client);
}

async function assertOwnerRole(client: PoolClient): Promise<void> {
  const result = await client.query<{ current_user: string }>("SELECT current_user");
  if (result.rows[0]?.current_user !== "thesistrace_owner") {
    throw new AgentSchemaContractError("SCHEMA_ROLE_CONTRACT_INVALID");
  }
}

async function agentScopeState(
  client: PoolClient,
): Promise<"absent" | "empty" | "populated"> {
  const result = await client.query<{ exists: boolean; object_count: string }>(`
    SELECT
      pg_catalog.to_regnamespace('agent') IS NOT NULL AS exists,
      (
        (SELECT count(*)
         FROM pg_catalog.pg_class AS relation
         JOIN pg_catalog.pg_namespace AS namespace
           ON namespace.oid = relation.relnamespace
         WHERE namespace.nspname = 'agent')
        +
        (SELECT count(*)
         FROM pg_catalog.pg_proc AS routine
         JOIN pg_catalog.pg_namespace AS namespace
           ON namespace.oid = routine.pronamespace
         WHERE namespace.nspname = 'agent')
        +
        (SELECT count(*)
         FROM pg_catalog.pg_type AS type_record
         JOIN pg_catalog.pg_namespace AS namespace
           ON namespace.oid = type_record.typnamespace
         WHERE namespace.nspname = 'agent'
           AND type_record.typrelid = 0
           AND type_record.typelem = 0)
      )::text AS object_count
  `);
  const row = result.rows[0];
  if (row === undefined || !row.exists) return "absent";
  return row.object_count === "0" ? "empty" : "populated";
}

async function readContractFile(url: URL): Promise<string> {
  try {
    return await readFile(url, "utf8");
  } catch (error) {
    throw new AgentSchemaContractError("SCHEMA_ARTIFACT_INVALID", error);
  }
}
