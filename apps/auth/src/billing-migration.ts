import { readFile } from "node:fs/promises";
import type { Pool } from "pg";
import {
  assertExactCatalog,
  catalogFingerprint,
  collectAuthSchemaCatalog,
  type AuthSchemaCatalog,
} from "./schema-contract.js";

export const AUTH_BILLING_SOURCE =
  "1726410065771dea71f1f81b83deee4de87f219c08b86c649d8d0c479b7eec7e";
export const AUTH_BILLING_TARGET =
  "1b50ec71fe68647a99ccdcf76c76fc1d5fa05cd59673bda0028f6fd7c22ce386";
const migration = "0003_billing";

/** Explicit owner maintenance; startup never upgrades an existing database. */
export async function migrateBilling(pool: Pool, apply = false) {
  const source = JSON.parse(
    await readFile(
      new URL("../schema/migrations/0003-source-catalog.json", import.meta.url),
      "utf8",
    ),
  ) as AuthSchemaCatalog;
  const target = JSON.parse(
    await readFile(
      new URL("../schema/migrations/0003-target-catalog.json", import.meta.url),
      "utf8",
    ),
  ) as AuthSchemaCatalog;
  if (
    catalogFingerprint(source) !== AUTH_BILLING_SOURCE ||
    catalogFingerprint(target) !== AUTH_BILLING_TARGET
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
        "SELECT schema_fingerprint FROM auth.schema_contract WHERE singleton FOR UPDATE",
      )
    ).rows[0]?.schema_fingerprint;
    if (current !== AUTH_BILLING_SOURCE && current !== AUTH_BILLING_TARGET)
      throw new Error("Unsupported Billing migration source");
    assertExactCatalog(
      current === AUTH_BILLING_SOURCE ? source : target,
      await collectAuthSchemaCatalog(client),
    );
    const preserved = (
      await client.query('SELECT count(*)::int AS count FROM auth."user"')
    ).rows[0].count as number;
    const report = {
      migration,
      source: AUTH_BILLING_SOURCE,
      target: AUTH_BILLING_TARGET,
      preserved_users: preserved,
      status:
        current === AUTH_BILLING_TARGET
          ? "already_current"
          : apply
            ? "applied"
            : "validated",
    };
    if (current === AUTH_BILLING_SOURCE && apply) {
      await client.query(
        await readFile(
          new URL("../schema/migrations/0003-billing.sql", import.meta.url),
          "utf8",
        ),
      );
      await client.query(
        await readFile(
          new URL(
            "../schema/migrations/0003-target-grants.sql",
            import.meta.url,
          ),
          "utf8",
        ),
      );
      assertExactCatalog(target, await collectAuthSchemaCatalog(client));
      await client.query(
        "CREATE SCHEMA IF NOT EXISTS thesistrace_auth_migrations AUTHORIZATION thesistrace_owner",
      );
      await client.query(
        "REVOKE ALL ON SCHEMA thesistrace_auth_migrations FROM PUBLIC,auth_runtime,core_runtime",
      );
      await client.query(
        `CREATE TABLE IF NOT EXISTS thesistrace_auth_migrations.history(id text PRIMARY KEY,source_fingerprint text NOT NULL,target_fingerprint text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())`,
      );
      await client.query(
        "ALTER TABLE thesistrace_auth_migrations.history ADD COLUMN details jsonb",
      );
      await client.query(
        "INSERT INTO thesistrace_auth_migrations.history(id,source_fingerprint,target_fingerprint,details,applied_at) VALUES($1,$2,$3,$4,now())",
        [
          migration,
          AUTH_BILLING_SOURCE,
          AUTH_BILLING_TARGET,
          JSON.stringify({ preserved_users: preserved }),
        ],
      );
      await client.query(
        "UPDATE auth.schema_contract SET schema_fingerprint=$1 WHERE singleton",
        [AUTH_BILLING_TARGET],
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
