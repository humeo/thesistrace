import { readFile } from "node:fs/promises";
import { Pool } from "pg";
import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { initializeAuthSchema } from "./schema-initialize.js";
import { assertExactCatalog, collectAuthSchemaCatalog, verifyAuthSchema, type AuthSchemaCatalog } from "./schema-contract.js";
import { AUTH_EMAIL_ONLY_SOURCE, AUTH_EMAIL_ONLY_TARGET, migrateRetiredInvitations } from "./retire-invitations-migration.js";

const pool = new Pool({connectionString: process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL});
const userId = "00000000-0000-4000-8000-000000000001";
const sessionId = "00000000-0000-4000-8000-000000000002";
const source = JSON.parse(await readFile(new URL("../schema/migrations/0002-source-catalog.json", import.meta.url), "utf8")) as AuthSchemaCatalog;

describe.sequential("Explicit email-only identity upgrade", () => {
  beforeEach(async () => {
    await pool.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await pool.query("DROP SCHEMA IF EXISTS thesistrace_auth_migrations CASCADE");
    await pool.query("CREATE SCHEMA auth AUTHORIZATION thesistrace_owner");
    await pool.query(await readFile(new URL("../schema/migrations/0002-source-schema.sql", import.meta.url), "utf8"));
    await pool.query(await readFile(new URL("../schema/grants.sql", import.meta.url), "utf8"));
    await pool.query("GRANT SELECT, INSERT, UPDATE, DELETE ON auth.researcher_invitation, auth.password_reset TO auth_runtime");
    await pool.query("INSERT INTO auth.schema_contract(singleton,schema_fingerprint) VALUES (TRUE,$1)", [AUTH_EMAIL_ONLY_SOURCE]);
    await pool.query(`INSERT INTO auth."user" (id,name,email,"emailVerified",active) VALUES ($1,'Existing','existing@example.com',TRUE,TRUE)`, [userId]);
    await pool.query(`INSERT INTO auth."session" (id,"userId",token,"updatedAt","expiresAt") VALUES ($1,$2,'retained-session',now(),now()+interval '1 day')`, [sessionId,userId]);
    await pool.query(`INSERT INTO auth."account" (issuer,"accountId","providerId","userId",password,"updatedAt") VALUES ('local:credential',$1::text,'credential',$1::uuid,'retained-password-hash',now())`, [userId]);
    await pool.query(`INSERT INTO auth.researcher_invitation (email,token_hash,status,expires_at,delivered_at)
      VALUES ('pending@example.com',decode(repeat('11',32),'hex'),'delivered',now()+interval '1 day',now())`);
    await pool.query(`INSERT INTO auth.password_reset (user_id,token_hash,status,expires_at,delivered_at)
      VALUES ($1,decode(repeat('22',32),'hex'),'delivered',now()+interval '1 hour',now())`, [userId]);
    await pool.query(`INSERT INTO auth.operator_proof (session_id,token_hash,request_hash,operation,state,expires_at)
      VALUES ($1,decode(repeat('33',32),'hex'),decode(repeat('44',32),'hex'),'invitation.issue','available',now()+interval '1 hour')`, [sessionId]);
    await pool.query(`INSERT INTO auth.security_audit (event,outcome,researcher_id) VALUES ('invitation_issued','succeeded',$1),('sign_in_succeeded','succeeded',$1)`, [userId]);
    await pool.query(`INSERT INTO auth.verification(identifier,value,"expiresAt") VALUES ('reset-password:retained-hash',$1,now()+interval '1 hour'),('sign-in-otp-existing@example.com','retained-otp',now()+interval '5 minutes')`, [userId]);
    assertExactCatalog(source, await collectAuthSchemaCatalog(pool));
  });
  afterAll(async () => {
    await pool.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await pool.query("DROP SCHEMA IF EXISTS thesistrace_auth_migrations CASCADE");
    await pool.end();
  });
  it("preserves identities and Sessions, archives retired records, and repeats without changes", async () => {
    const preserved = await Promise.all(["user", "session", "account"].map(table => pool.query(`SELECT * FROM auth.${table}`)));
    const retired = await Promise.all(["researcher_invitation", "password_reset"].map(table => pool.query(`SELECT * FROM auth.${table}`)));
    expect((await migrateRetiredInvitations(pool)).status).toBe("validated");
    expect((await migrateRetiredInvitations(pool, true)).status).toBe("applied");
    await verifyAuthSchema(pool);
    await initializeAuthSchema(pool);
    expect((await migrateRetiredInvitations(pool, true)).status).toBe("already_current");
    for (const [index, table] of ["user", "session", "account"].entries()) {
      expect((await pool.query(`SELECT * FROM auth.${table}`)).rows).toEqual(preserved[index]!.rows);
    }
    for (const [index, table] of ["researcher_invitation", "password_reset"].entries()) {
      expect((await pool.query(`SELECT * FROM thesistrace_auth_migrations.${table}`)).rows).toEqual(retired[index]!.rows);
    }
    expect((await pool.query("SELECT event FROM auth.security_audit")).rows).toEqual([{event: "sign_in_succeeded"}]);
    expect((await pool.query("SELECT event FROM thesistrace_auth_migrations.retired_security_audit")).rows).toEqual([{event: "invitation_issued"}]);
    expect((await pool.query("SELECT operation FROM thesistrace_auth_migrations.retired_operator_proof")).rows).toEqual([{operation: "invitation.issue"}]);
    expect((await pool.query("SELECT identifier FROM auth.verification")).rows).toEqual([{identifier: "sign-in-otp-existing@example.com"}]);
    expect((await pool.query("SELECT count(*)::int AS count FROM thesistrace_auth_migrations.retired_verification")).rows).toEqual([{count: 1}]);
    expect((await pool.query("SELECT has_schema_privilege('auth_runtime','thesistrace_auth_migrations','USAGE') AS allowed")).rows).toEqual([{allowed: false}]);
    expect((await pool.query("SELECT target_fingerprint FROM thesistrace_auth_migrations.history")).rows).toEqual([{target_fingerprint: AUTH_EMAIL_ONLY_TARGET}]);
  });
  it("rolls back archive moves, rows, constraints and fingerprint on a late receipt failure", async () => {
    const before = (await pool.query("SELECT * FROM auth.researcher_invitation")).rows;
    await pool.query("CREATE SCHEMA thesistrace_auth_migrations");
    await pool.query("CREATE TABLE thesistrace_auth_migrations.history (id text PRIMARY KEY CHECK (false), source_fingerprint text, target_fingerprint text)");
    await expect(migrateRetiredInvitations(pool, true)).rejects.toThrow();
    assertExactCatalog(source, await collectAuthSchemaCatalog(pool));
    expect((await pool.query("SELECT * FROM auth.researcher_invitation")).rows).toEqual(before);
    expect((await pool.query("SELECT schema_fingerprint FROM auth.schema_contract")).rows).toEqual([{schema_fingerprint: AUTH_EMAIL_ONLY_SOURCE}]);
    expect((await migrateRetiredInvitations(pool)).status).toBe("validated");
  });
  it("rejects structural drift without changing records", async () => {
    await pool.query("ALTER TABLE auth.user ADD COLUMN drift text");
    await expect(migrateRetiredInvitations(pool, true)).rejects.toMatchObject({reason: "SCHEMA_CATALOG_DRIFT"});
    expect((await pool.query("SELECT count(*)::int AS count FROM auth.researcher_invitation")).rows).toEqual([{count: 1}]);
  });
});
