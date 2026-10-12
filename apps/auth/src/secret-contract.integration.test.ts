import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { createAuthPool } from "./database.js";
import { initializeAuthSchema } from "./schema-initialize.js";
import { enforceAuthSecretContract } from "./secret-contract.js";
import { secretFingerprint } from "./security.js";

const ownerDatabaseUrl = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (ownerDatabaseUrl === undefined) {
  throw new Error("THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL is required");
}
const authRuntimeDatabaseUrl = roleDatabaseUrl(
  ownerDatabaseUrl,
  "auth_runtime",
  "auth-test-password",
);
const owner = new Pool({ connectionString: ownerDatabaseUrl, max: 2 });
const runtimePool = createAuthPool(authRuntimeDatabaseUrl);
const firstSecret = "0123456789abcdef0123456789abcdef";
const rotatedSecret = "abcdef0123456789abcdef0123456789";
const fixedNow = new Date("2026-08-28T07:00:00.000Z");
const userId = "00000000-0000-4000-8000-000000000001";

describe.sequential("Auth secret fingerprint contract", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    await owner.query(`
      TRUNCATE
        auth.auth_secret_contract,
        auth.security_audit,


        auth."rateLimit",
        auth."verification",
        auth."user"
      CASCADE
    `);
  });

  afterAll(async () => {
    await runtimePool.end();
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("initializes once and treats the same secret as no change", async () => {
    await expect(
      enforceAuthSecretContract(runtimePool, firstSecret),
    ).resolves.toEqual({ status: "initialized" });
    await expect(
      enforceAuthSecretContract(runtimePool, firstSecret),
    ).resolves.toEqual({ status: "unchanged" });

    expect(
      await owner.query<{ secret_fingerprint: string }>(
        "SELECT secret_fingerprint FROM auth.auth_secret_contract",
      ),
    ).toMatchObject({
      rows: [{ secret_fingerprint: secretFingerprint(firstSecret) }],
    });
  });

  it("serializes hard rotation and revokes Sessions and email codes while retaining identity", async () => {
    await enforceAuthSecretContract(runtimePool, firstSecret);
    await insertEffectiveCredentials();
    const results=await Promise.all([enforceAuthSecretContract(runtimePool,rotatedSecret),enforceAuthSecretContract(runtimePool,rotatedSecret)]);
    expect(results).toEqual(expect.arrayContaining([{status:"rotated"},{status:"unchanged"}]));
    expect((await owner.query("SELECT secret_fingerprint FROM auth.auth_secret_contract")).rows).toEqual([{secret_fingerprint:secretFingerprint(rotatedSecret)}]);
    expect((await owner.query('SELECT count(*)::int AS count FROM auth."session"')).rows).toEqual([{count:0}]);
    expect((await owner.query('SELECT count(*)::int AS count FROM auth."verification"')).rows).toEqual([{count:0}]);
    expect((await owner.query('SELECT id,active FROM auth."user"')).rows).toEqual([{id:userId,active:true}]);
  });
});

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}

async function insertEffectiveCredentials(): Promise<void> {
  await owner.query(`INSERT INTO auth."user" (id,name,email,"emailVerified",active) VALUES ($1,'researcher','researcher@example.com',TRUE,TRUE)`,[userId]);
  await owner.query(`INSERT INTO auth."session" ("userId",token,"updatedAt","expiresAt") VALUES ($1,'test-session',now(),now()+interval '1 day')`,[userId]);
  await owner.query(`INSERT INTO auth."verification" (identifier,value,"expiresAt") VALUES ('sign-in-otp-researcher@example.com','hashed-login-code',now()+interval '5 minutes'),('email-verification-otp-researcher@example.com','hashed-operator-code',now()+interval '5 minutes')`);
}
