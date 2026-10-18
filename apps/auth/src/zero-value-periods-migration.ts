import { readFile } from "node:fs/promises";
import type { Pool, PoolClient } from "pg";
import {
  assertExactCatalog,
  catalogFingerprint,
  collectAuthSchemaCatalog,
  type AuthSchemaCatalog,
} from "./schema-contract.js";

export const AUTH_ZERO_VALUE_SOURCE =
  "1b50ec71fe68647a99ccdcf76c76fc1d5fa05cd59673bda0028f6fd7c22ce386";
export const AUTH_ZERO_VALUE_TARGET =
  "78bdfd071c325493a48f7ab947cfc846c9e65d1adb207d1aeba1fa94fe7d4e2e";
const migration = "0004_zero_value_periods";

/** Explicit owner maintenance; startup never upgrades an existing database. */
export async function migrateZeroValuePeriods(pool: Pool, apply = false) {
  const source = JSON.parse(
    await readFile(
      new URL("../schema/migrations/0004-source-catalog.json", import.meta.url),
      "utf8",
    ),
  ) as AuthSchemaCatalog;
  const target = JSON.parse(
    await readFile(
      new URL("../schema/migrations/0004-target-catalog.json", import.meta.url),
      "utf8",
    ),
  ) as AuthSchemaCatalog;
  if (
    catalogFingerprint(source) !== AUTH_ZERO_VALUE_SOURCE ||
    catalogFingerprint(target) !== AUTH_ZERO_VALUE_TARGET
  )
    throw new Error("Zero-value period migration release assets do not match");
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
      throw new Error("Zero-value period migration requires the database owner");
    const current = (
      await client.query(
        "SELECT schema_fingerprint FROM auth.schema_contract WHERE singleton FOR UPDATE",
      )
    ).rows[0]?.schema_fingerprint;
    if (current !== AUTH_ZERO_VALUE_SOURCE && current !== AUTH_ZERO_VALUE_TARGET)
      throw new Error("Unsupported Zero-value period migration source");
    assertExactCatalog(
      current === AUTH_ZERO_VALUE_SOURCE ? source : target,
      await collectAuthSchemaCatalog(client),
    );
    const preserved = (
      await client.query('SELECT count(*)::int AS count FROM auth."user"')
    ).rows[0].count as number;
    const retained = await billingRows(client);
    const report = {
      migration,
      source: AUTH_ZERO_VALUE_SOURCE,
      target: AUTH_ZERO_VALUE_TARGET,
      preserved_users: preserved,
      ...retained,
      status:
        current === AUTH_ZERO_VALUE_TARGET
          ? "already_current"
          : apply
            ? "applied"
            : "validated",
    };
    if (current === AUTH_ZERO_VALUE_SOURCE && apply) {
      await client.query(
        await readFile(
          new URL("../schema/migrations/0004-zero-value-periods.sql", import.meta.url),
          "utf8",
        ),
      );
      assertExactCatalog(target, await collectAuthSchemaCatalog(client));
      if (JSON.stringify(await billingRows(client)) !== JSON.stringify(retained))
        throw new Error("Zero-value period migration changed existing billing data");
      await client.query(
        "CREATE SCHEMA IF NOT EXISTS thesistrace_auth_migrations AUTHORIZATION thesistrace_owner",
      );
      await client.query(
        "REVOKE ALL ON SCHEMA thesistrace_auth_migrations FROM PUBLIC,auth_runtime,core_runtime",
      );
      await client.query(
        `CREATE TABLE IF NOT EXISTS thesistrace_auth_migrations.history(id text PRIMARY KEY,source_fingerprint text NOT NULL,target_fingerprint text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now(),details jsonb)`,
      );
      await client.query(
        "INSERT INTO thesistrace_auth_migrations.history(id,source_fingerprint,target_fingerprint,details,applied_at) VALUES($1,$2,$3,$4,now())",
        [
          migration,
          AUTH_ZERO_VALUE_SOURCE,
          AUTH_ZERO_VALUE_TARGET,
          JSON.stringify({ preserved_users: preserved, ...retained }),
        ],
      );
      await client.query(
        "UPDATE auth.schema_contract SET schema_fingerprint=$1 WHERE singleton",
        [AUTH_ZERO_VALUE_TARGET],
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

async function billingRows(client: PoolClient) {
  return (await client.query(`SELECT
    (SELECT count(*)::int FROM auth.billing_payment) AS preserved_payments,
    (SELECT md5(COALESCE(jsonb_agg(to_jsonb(p) - 'fully_refunded' ORDER BY transaction_id)::text, '[]')) FROM auth.billing_payment p) AS payments_checksum,
    (SELECT md5(COALESCE(jsonb_agg(to_jsonb(a) - 'fully_refunded' ORDER BY transaction_id)::text, '[]')) FROM auth.billing_adjustment a) AS adjustments_checksum
  `)).rows[0];
}
