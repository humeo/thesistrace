import { readFile } from "node:fs/promises";
import { Pool } from "pg";
import { afterAll, beforeEach, expect, it } from "vitest";
import {
  AGENT_BILLING_SOURCE,
  migrateModelSettlement,
} from "./model-settlement-migration.js";
import { initializeAgentSchema } from "./schema-initialize.js";
const pool = new Pool({
  connectionString: process.env.THESISTRACE_AGENT_TEST_OWNER_DATABASE_URL,
});
beforeEach(async () => {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      "DROP SCHEMA IF EXISTS agent CASCADE;DROP SCHEMA IF EXISTS thesistrace_agent_migrations CASCADE;CREATE SCHEMA agent AUTHORIZATION thesistrace_owner",
    );
    await client.query(
      await readFile(
        new URL("../schema/migrations/0001-source-schema.sql", import.meta.url),
        "utf8",
      ),
    );
    await client.query(
      await readFile(
        new URL("../schema/migrations/0001-source-grants.sql", import.meta.url),
        "utf8",
      ),
    );
    await client.query("INSERT INTO agent.schema_contract VALUES(true,$1)", [
      AGENT_BILLING_SOURCE,
    ]);
    await client.query(
      "INSERT INTO agent.model_charge(id,researcher_id,budget_day,reserved_nanodollars,actual_nanodollars) VALUES('50f168cf-d3f4-4e19-b46e-e60c23905305','d5153c13-aaac-467b-823c-036f92a90897','2026-10-17',100,20)",
    );
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});
afterAll(() => pool.end());
it("preserves settled costs and supports verification and repeated migration", async () => {
  expect((await migrateModelSettlement(pool)).status).toBe("validated");
  expect((await migrateModelSettlement(pool, true)).preserved_charges).toBe(1);
  await initializeAgentSchema(pool);
  expect((await migrateModelSettlement(pool, true)).status).toBe(
    "already_current",
  );
  expect(
    (
      await pool.query(
        "SELECT actual_nanodollars,settlement_state FROM agent.model_charge",
      )
    ).rows,
  ).toEqual([{ actual_nanodollars: "20", settlement_state: "settled" }]);
});
it("rolls back columns and fingerprint if the durable receipt fails", async () => {
  await pool.query(
    "CREATE SCHEMA thesistrace_agent_migrations;CREATE TABLE thesistrace_agent_migrations.history(id text PRIMARY KEY CHECK(false),source_fingerprint text,target_fingerprint text,applied_at timestamptz)",
  );
  await expect(migrateModelSettlement(pool, true)).rejects.toThrow();
  expect((await migrateModelSettlement(pool)).status).toBe("validated");
  expect(
    (await pool.query("SELECT schema_fingerprint FROM agent.schema_contract"))
      .rows,
  ).toEqual([{ schema_fingerprint: AGENT_BILLING_SOURCE }]);
});
