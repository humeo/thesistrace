import { readFile } from "node:fs/promises";
import { Pool } from "pg";
import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { AUTH_ZERO_VALUE_SOURCE, migrateZeroValuePeriods } from "./zero-value-periods-migration.js";
import { initializeAuthSchema } from "./schema-initialize.js";
import { assertExactCatalog, collectAuthSchemaCatalog } from "./schema-contract.js";

const pool = new Pool({ connectionString: process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL });
const researcher = "b50a37be-7865-4c6a-bd8f-e48dc08f82af";
describe.sequential("Explicit zero-value paid-period upgrade", () => {
  beforeEach(async () => {
    const source = await readFile(new URL("../schema/migrations/0004-source-schema.sql", import.meta.url), "utf8");
    const grants = await readFile(new URL("../schema/migrations/0004-source-grants.sql", import.meta.url), "utf8");
    await pool.query("DROP SCHEMA IF EXISTS auth CASCADE; DROP SCHEMA IF EXISTS thesistrace_auth_migrations CASCADE; CREATE SCHEMA auth AUTHORIZATION thesistrace_owner;" + source + grants);
    await pool.query("INSERT INTO auth.schema_contract(singleton,schema_fingerprint) VALUES(true,$1)", [AUTH_ZERO_VALUE_SOURCE]);
    await pool.query(`INSERT INTO auth."user" (id,name,email,"emailVerified",active) VALUES($1,'Retained','retained@fixture.test',true,true)`, [researcher]);
    await pool.query(`INSERT INTO auth.billing_payment(transaction_id,researcher_id,subscription_id,plan_key,starts_at,ends_at,amount,refunded_amount) VALUES
      ('txn_partial',$1,'sub_partial','pro','2026-10-01Z','2026-11-01Z',2000,500),
      ('txn_refunded',$1,'sub_refunded','max','2026-10-01Z','2026-11-01Z',10000,10000)`, [researcher]);
    await pool.query("INSERT INTO auth.billing_adjustment(transaction_id,refunded_amount) VALUES('txn_partial',500),('txn_refunded',10000)");
  });
  afterAll(async () => { await pool.end(); });

  it("preserves billing rows, backfills full refunds and repeats without rewriting data", async () => {
    const before = (await pool.query("SELECT * FROM auth.billing_payment ORDER BY transaction_id")).rows;
    expect((await migrateZeroValuePeriods(pool)).status).toBe("validated");
    expect(await migrateZeroValuePeriods(pool, true)).toMatchObject({ status: "applied", preserved_users: 1, preserved_payments: 2 });
    await initializeAuthSchema(pool);
    expect((await migrateZeroValuePeriods(pool, true)).status).toBe("already_current");
    const after = (await pool.query("SELECT * FROM auth.billing_payment ORDER BY transaction_id")).rows;
    expect(after.map(({ fully_refunded: _, ...row }) => row)).toEqual(before);
    expect(after.map(row => row.fully_refunded)).toEqual([false, true]);
    expect((await pool.query("SELECT fully_refunded FROM auth.billing_adjustment ORDER BY transaction_id")).rows).toEqual([{ fully_refunded: false }, { fully_refunded: true }]);
    await pool.query(`INSERT INTO auth.billing_payment(transaction_id,researcher_id,subscription_id,plan_key,starts_at,ends_at,amount) VALUES('txn_zero',$1,'sub_zero','pro','2026-10-01Z','2026-11-01Z',0)`, [researcher]);
    expect((await pool.query("SELECT count(*)::int AS n FROM thesistrace_auth_migrations.history WHERE id='0004_zero_value_periods'")).rows).toEqual([{ n: 1 }]);
  });

  it("rolls back constraints, columns, data and receipt after a late failure", async () => {
    const source = JSON.parse(await readFile(new URL("../schema/migrations/0004-source-catalog.json", import.meta.url), "utf8"));
    const before = (await pool.query("SELECT * FROM auth.billing_payment ORDER BY transaction_id")).rows;
    await pool.query("CREATE SCHEMA thesistrace_auth_migrations; CREATE TABLE thesistrace_auth_migrations.history(id text PRIMARY KEY CHECK(false),source_fingerprint text,target_fingerprint text,applied_at timestamptz,details jsonb)");
    await expect(migrateZeroValuePeriods(pool, true)).rejects.toThrow();
    assertExactCatalog(source, await collectAuthSchemaCatalog(pool));
    expect((await pool.query("SELECT * FROM auth.billing_payment ORDER BY transaction_id")).rows).toEqual(before);
    expect((await pool.query("SELECT schema_fingerprint FROM auth.schema_contract")).rows).toEqual([{ schema_fingerprint: AUTH_ZERO_VALUE_SOURCE }]);
    expect((await migrateZeroValuePeriods(pool)).status).toBe("validated");
  });
});
