import { readFile } from "node:fs/promises";
import type { Pool } from "pg";
import {
  assertExactCatalog, catalogFingerprint, collectAuthSchemaCatalog,
  loadExpectedCatalog, type AuthSchemaCatalog,
} from "./schema-contract.js";

export const AUTH_REFRESH_SOURCE = "479089ee38d20700e10a0f955ee153eb2644e6925d4cb671009a728a161b1d5e";
export const AUTH_REFRESH_TARGET = "d64b69665b7454cd602a81295df4deb99b5f336a6df58a6cb66dc3b35aa3a4eb";
const migration = "0001_dataset_refresh_proofs";

/** Explicit maintenance command; never called by application initialization. */
export async function migrateUnifiedRefreshProofs(pool: Pool, apply = false) {
  const source = JSON.parse(await readFile(new URL("../schema/migrations/0001-source-catalog.json", import.meta.url), "utf8")) as AuthSchemaCatalog;
  const target = await loadExpectedCatalog();
  if (catalogFingerprint(source) !== AUTH_REFRESH_SOURCE || catalogFingerprint(target) !== AUTH_REFRESH_TARGET) {
    throw new Error("Migration assets do not match the declared release");
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query("SET LOCAL lock_timeout='5s'");
    await client.query("SET LOCAL statement_timeout='60s'");
    await client.query("SELECT pg_advisory_xact_lock(hashtextextended('thesistrace:auth-schema',0))");
    const current = (await client.query<{ schema_fingerprint: string }>(
      "SELECT schema_fingerprint FROM auth.schema_contract WHERE singleton FOR UPDATE",
    )).rows[0]?.schema_fingerprint;
    if (current !== AUTH_REFRESH_SOURCE && current !== AUTH_REFRESH_TARGET) throw new Error("Unsupported Auth migration source");
    assertExactCatalog(current === AUTH_REFRESH_SOURCE ? source : target, await collectAuthSchemaCatalog(client));
    const report = { migration, source: AUTH_REFRESH_SOURCE, target: AUTH_REFRESH_TARGET,
      status: current === AUTH_REFRESH_TARGET ? "already_current" : apply ? "applied" : "validated" };
    if (current === AUTH_REFRESH_SOURCE && apply) {
      const constraint = target.constraints.find(item => item.name === "operator_proof_operation_check")!;
      await client.query("ALTER TABLE auth.operator_proof DROP CONSTRAINT operator_proof_operation_check");
      await client.query(`ALTER TABLE auth.operator_proof ADD CONSTRAINT operator_proof_operation_check ${constraint.definition}`);
      assertExactCatalog(target, await collectAuthSchemaCatalog(client));
      await client.query("CREATE SCHEMA IF NOT EXISTS thesistrace_auth_migrations");
      await client.query(`CREATE TABLE IF NOT EXISTS thesistrace_auth_migrations.history (
        id text PRIMARY KEY, source_fingerprint text NOT NULL, target_fingerprint text NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now())`);
      await client.query("INSERT INTO thesistrace_auth_migrations.history(id,source_fingerprint,target_fingerprint) VALUES ($1,$2,$3)",
        [migration, AUTH_REFRESH_SOURCE, AUTH_REFRESH_TARGET]);
      await client.query("UPDATE auth.schema_contract SET schema_fingerprint=$1 WHERE singleton", [AUTH_REFRESH_TARGET]);
    }
    await client.query("COMMIT");
    return report;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally { client.release(); }
}
