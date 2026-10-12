import { readFile } from "node:fs/promises";
import type { Pool } from "pg";
import {
  assertExactCatalog, catalogFingerprint, collectAuthSchemaCatalog,
  loadExpectedCatalog, type AuthSchemaCatalog,
} from "./schema-contract.js";

export const AUTH_EMAIL_ONLY_SOURCE = "d64b69665b7454cd602a81295df4deb99b5f336a6df58a6cb66dc3b35aa3a4eb";
export const AUTH_EMAIL_ONLY_TARGET = "1726410065771dea71f1f81b83deee4de87f219c08b86c649d8d0c479b7eec7e";
const migration = "0002_retire_invitation_credentials";

/** Explicit owner maintenance only. Application startup never upgrades a populated schema. */
export async function migrateRetiredInvitations(pool: Pool, apply = false) {
  const source = JSON.parse(await readFile(new URL("../schema/migrations/0002-source-catalog.json", import.meta.url), "utf8")) as AuthSchemaCatalog;
  const target = await loadExpectedCatalog();
  if (catalogFingerprint(source) !== AUTH_EMAIL_ONLY_SOURCE || catalogFingerprint(target) !== AUTH_EMAIL_ONLY_TARGET) {
    throw new Error("Migration assets do not match the declared release");
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query("SET LOCAL lock_timeout='5s'");
    await client.query("SET LOCAL statement_timeout='60s'");
    await client.query("SELECT pg_advisory_xact_lock(hashtextextended('thesistrace:auth-schema',0))");
    if ((await client.query("SELECT current_user")).rows[0]?.current_user !== "thesistrace_owner") {
      throw new Error("Auth migration requires the database owner");
    }
    const current = (await client.query<{ schema_fingerprint: string }>(
      "SELECT schema_fingerprint FROM auth.schema_contract WHERE singleton FOR UPDATE",
    )).rows[0]?.schema_fingerprint;
    if (current !== AUTH_EMAIL_ONLY_SOURCE && current !== AUTH_EMAIL_ONLY_TARGET) throw new Error("Unsupported Auth migration source");
    assertExactCatalog(current === AUTH_EMAIL_ONLY_SOURCE ? source : target, await collectAuthSchemaCatalog(client));
    const report = { migration, source: AUTH_EMAIL_ONLY_SOURCE, target: AUTH_EMAIL_ONLY_TARGET,
      status: current === AUTH_EMAIL_ONLY_TARGET ? "already_current" : apply ? "applied" : "validated" };
    if (current === AUTH_EMAIL_ONLY_SOURCE && apply) {
      await client.query("CREATE SCHEMA IF NOT EXISTS thesistrace_auth_migrations AUTHORIZATION thesistrace_owner");
      await client.query("REVOKE ALL ON SCHEMA thesistrace_auth_migrations FROM PUBLIC, auth_runtime, core_runtime");
      // Moving the full tables retains every row, timestamp and token hash. Detached
      // foreign keys prevent future identity/session cleanup from deleting history.
      for (const table of ["researcher_invitation", "password_reset"]) {
        await client.query(`LOCK TABLE auth.${table} IN ACCESS EXCLUSIVE MODE`);
        await client.query(`ALTER TABLE auth.${table} SET SCHEMA thesistrace_auth_migrations`);
        await client.query(`ALTER TABLE thesistrace_auth_migrations.${table} DROP CONSTRAINT ${table}_user_id_fkey`);
        await client.query(`REVOKE ALL ON TABLE thesistrace_auth_migrations.${table} FROM PUBLIC, auth_runtime, core_runtime`);
      }
      for (const [table, predicate] of [
        ["operator_proof", "operation IN ('invitation.issue', 'invitation.reissue')"],
        ["security_audit", "event IN ('invitation_issued', 'invitation_revoked', 'invitation_accepted', 'password_changed', 'password_reset_requested', 'password_reset_succeeded', 'password_reset_failed')"],
        ["verification", "identifier LIKE 'reset-password:%'"],
      ]) {
        await client.query(`LOCK TABLE auth.${table} IN ACCESS EXCLUSIVE MODE`);
        await client.query(`CREATE TABLE thesistrace_auth_migrations.retired_${table} AS SELECT * FROM auth.${table} WHERE ${predicate}`);
        await client.query(`DELETE FROM auth.${table} WHERE ${predicate}`);
        await client.query(`REVOKE ALL ON TABLE thesistrace_auth_migrations.retired_${table} FROM PUBLIC, auth_runtime, core_runtime`);
      }
      for (const name of ["operator_proof_operation_check", "security_audit_event_check"]) {
        const constraint = target.constraints.find(item => item.name === name)!;
        await client.query(`ALTER TABLE auth.${constraint.relation} DROP CONSTRAINT ${name}`);
        await client.query(`ALTER TABLE auth.${constraint.relation} ADD CONSTRAINT ${name} ${constraint.definition}`);
      }
      assertExactCatalog(target, await collectAuthSchemaCatalog(client));
      await client.query(`CREATE TABLE IF NOT EXISTS thesistrace_auth_migrations.history (
        id text PRIMARY KEY, source_fingerprint text NOT NULL, target_fingerprint text NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now())`);
      await client.query("INSERT INTO thesistrace_auth_migrations.history(id,source_fingerprint,target_fingerprint) VALUES ($1,$2,$3)",
        [migration, AUTH_EMAIL_ONLY_SOURCE, AUTH_EMAIL_ONLY_TARGET]);
      await client.query("UPDATE auth.schema_contract SET schema_fingerprint=$1 WHERE singleton", [AUTH_EMAIL_ONLY_TARGET]);
    }
    await client.query("COMMIT");
    return report;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally { client.release(); }
}
