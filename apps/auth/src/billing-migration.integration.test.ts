import { readFile } from "node:fs/promises";
import { Pool } from "pg";
import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { AUTH_BILLING_SOURCE, migrateBilling } from "./billing-migration.js";
import { initializeAuthSchema } from "./schema-initialize.js";

const pool = new Pool({
  connectionString: process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL,
});
describe.sequential("Explicit paid-entitlement schema upgrade", () => {
  beforeEach(async () => {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const source = await readFile(
        new URL("../schema/migrations/0003-source-schema.sql", import.meta.url),
        "utf8",
      );
      const grants = await readFile(
        new URL("../schema/migrations/0003-source-grants.sql", import.meta.url),
        "utf8",
      );
      await client.query(
        "DROP SCHEMA IF EXISTS auth CASCADE; DROP SCHEMA IF EXISTS thesistrace_auth_migrations CASCADE; CREATE SCHEMA auth AUTHORIZATION thesistrace_owner;" +
          source +
          grants,
      );
      await client.query(
        "INSERT INTO auth.schema_contract(singleton,schema_fingerprint) VALUES(true,$1)",
        [AUTH_BILLING_SOURCE],
      );
      await client.query(
        `INSERT INTO auth."user" (name,email,"emailVerified",active) VALUES('Retained','retained@fixture.test',true,true)`,
      );
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  });
  afterAll(async () => {
    await pool.end();
  });
  it("preserves identities, records the upgrade and validates repeated execution", async () => {
    const before = (await pool.query('SELECT * FROM auth."user"')).rows;
    expect((await migrateBilling(pool)).status).toBe("validated");
    expect((await migrateBilling(pool, true)).status).toBe("applied");
    await initializeAuthSchema(pool);
    expect((await migrateBilling(pool, true)).status).toBe("already_current");
    expect((await pool.query('SELECT * FROM auth."user"')).rows).toEqual(
      before,
    );
    expect(
      (
        await pool.query(
          "SELECT details->>'preserved_users' AS count FROM thesistrace_auth_migrations.history WHERE id='0003_billing'",
        )
      ).rows,
    ).toEqual([{ count: "1" }]);
  });
  it("rolls back added tables, rights and fingerprint if the receipt cannot commit", async () => {
    await pool.query("CREATE SCHEMA thesistrace_auth_migrations");
    await pool.query(
      "CREATE TABLE thesistrace_auth_migrations.history(id text PRIMARY KEY CHECK(false),source_fingerprint text,target_fingerprint text,applied_at timestamptz)",
    );
    await expect(migrateBilling(pool, true)).rejects.toThrow();
    expect(
      (await pool.query("SELECT to_regclass('auth.billing_payment') AS added"))
        .rows,
    ).toEqual([{ added: null }]);
    expect(
      (await pool.query("SELECT schema_fingerprint FROM auth.schema_contract"))
        .rows,
    ).toEqual([{ schema_fingerprint: AUTH_BILLING_SOURCE }]);
    expect((await migrateBilling(pool)).status).toBe("validated");
  });
});
