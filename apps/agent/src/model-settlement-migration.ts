import { readFile } from "node:fs/promises";
import type { Pool } from "pg";
import {
  assertExactCatalog,
  catalogFingerprint,
  collectAgentSchemaCatalog,
  type AgentSchemaCatalog,
} from "./schema-contract.js";

export const AGENT_BILLING_SOURCE =
  "0f28e823f7a7128e7e4eba004584ca58475d9df737006a1899965f97b358099e";
export const AGENT_BILLING_TARGET =
  "639450f161abbaba6c0314465024effbb9b9ddf3eb1d0cf24a91569145149577";
const migration = "0001_model_settlement";

/** Explicit owner maintenance; startup never upgrades an existing database. */
export async function migrateModelSettlement(pool: Pool, apply = false) {
  const source = JSON.parse(
    await readFile(
      new URL(
        "../schema/migrations/0001-source-catalog-contract.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ) as AgentSchemaCatalog;
  const target = JSON.parse(
    await readFile(
      new URL("../schema/migrations/0001-target-catalog.json", import.meta.url),
      "utf8",
    ),
  ) as AgentSchemaCatalog;
  if (
    catalogFingerprint(source) !== AGENT_BILLING_SOURCE ||
    catalogFingerprint(target) !== AGENT_BILLING_TARGET
  )
    throw new Error("Billing migration release assets do not match");
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query("SET LOCAL search_path=pg_catalog");
    await client.query("SET LOCAL lock_timeout='5s'");
    await client.query("SET LOCAL statement_timeout='60s'");
    await client.query(
      "SELECT pg_advisory_xact_lock(hashtextextended('thesistrace:auth-schema',0))",
    );
    if (
      (await client.query("SELECT current_user")).rows[0]?.current_user !==
      "thesistrace_owner"
    )
      throw new Error("Billing migration requires the database owner");
    const current = (
      await client.query(
        "SELECT schema_fingerprint FROM agent.schema_contract WHERE singleton FOR UPDATE",
      )
    ).rows[0]?.schema_fingerprint;
    if (current !== AGENT_BILLING_SOURCE && current !== AGENT_BILLING_TARGET)
      throw new Error("Unsupported Billing migration source");
    assertExactCatalog(
      current === AGENT_BILLING_SOURCE ? source : target,
      await collectAgentSchemaCatalog(client),
    );
    const preserved = (
      await client.query(
        "SELECT count(*)::int AS count FROM agent.model_charge",
      )
    ).rows[0].count as number;
    const report = {
      migration,
      source: AGENT_BILLING_SOURCE,
      target: AGENT_BILLING_TARGET,
      preserved_charges: preserved,
      status:
        current === AGENT_BILLING_TARGET
          ? "already_current"
          : apply
            ? "applied"
            : "validated",
    };
    if (current === AGENT_BILLING_SOURCE && apply) {
      await client.query(
        await readFile(
          new URL(
            "../schema/migrations/0001-model-settlement.sql",
            import.meta.url,
          ),
          "utf8",
        ),
      );
      await client.query(
        await readFile(
          new URL(
            "../schema/migrations/0001-target-grants.sql",
            import.meta.url,
          ),
          "utf8",
        ),
      );
      assertExactCatalog(target, await collectAgentSchemaCatalog(client));
      await client.query(
        "CREATE SCHEMA IF NOT EXISTS thesistrace_agent_migrations AUTHORIZATION thesistrace_owner",
      );
      await client.query(
        "REVOKE ALL ON SCHEMA thesistrace_agent_migrations FROM PUBLIC,auth_runtime,core_runtime,agent_runtime",
      );
      await client.query(
        `CREATE TABLE IF NOT EXISTS thesistrace_agent_migrations.history(id text PRIMARY KEY,source_fingerprint text NOT NULL,target_fingerprint text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())`,
      );
      await client.query(
        "ALTER TABLE thesistrace_agent_migrations.history ADD COLUMN details jsonb",
      );
      await client.query(
        "INSERT INTO thesistrace_agent_migrations.history(id,source_fingerprint,target_fingerprint,details,applied_at) VALUES($1,$2,$3,$4,now())",
        [
          migration,
          AGENT_BILLING_SOURCE,
          AGENT_BILLING_TARGET,
          JSON.stringify({ preserved_charges: preserved }),
        ],
      );
      await client.query(
        "UPDATE agent.schema_contract SET schema_fingerprint=$1 WHERE singleton",
        [AGENT_BILLING_TARGET],
      );
    }
    await client.query("COMMIT");
    return report;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}
