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
        auth.password_reset,
        auth.researcher_invitation,
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
      enforceAuthSecretContract(runtimePool, firstSecret, () => fixedNow),
    ).resolves.toEqual({ status: "initialized" });
    await expect(
      enforceAuthSecretContract(runtimePool, firstSecret, () => fixedNow),
    ).resolves.toEqual({ status: "unchanged" });

    expect(
      await owner.query<{ secret_fingerprint: string }>(
        "SELECT secret_fingerprint FROM auth.auth_secret_contract",
      ),
    ).toMatchObject({
      rows: [{ secret_fingerprint: secretFingerprint(firstSecret) }],
    });
  });

  it("serializes a hard rotation and revokes every effective credential", async () => {
    await enforceAuthSecretContract(runtimePool, firstSecret, () => fixedNow);
    await insertEffectiveCredentials();

    const results = await Promise.all([
      enforceAuthSecretContract(runtimePool, rotatedSecret, () => fixedNow),
      enforceAuthSecretContract(runtimePool, rotatedSecret, () => fixedNow),
    ]);
    const persisted = await owner.query<{
      reset_status: string;
      reset_terminal_at: Date;
      secret_fingerprint: string;
      sessions: string;
      verifications: string;
    }>(`
      SELECT
        c.secret_fingerprint,
        r.status AS reset_status,
        r.terminal_at AS reset_terminal_at,
        (SELECT count(*) FROM auth."session") AS sessions,
        (
          SELECT count(*)
          FROM auth."verification"
          WHERE identifier LIKE 'reset-password:%'
        ) AS verifications
      FROM auth.auth_secret_contract c
      CROSS JOIN auth.password_reset r
    `);
    const invitations = await owner.query<{
      status: string;
      terminal_at: Date;
    }>(
      `
        SELECT status, terminal_at
        FROM auth.researcher_invitation
        ORDER BY id
      `,
    );

    expect(results).toEqual(
      expect.arrayContaining([{ status: "rotated" }, { status: "unchanged" }]),
    );
    expect(persisted.rows).toEqual([
      {
        reset_status: "revoked",
        reset_terminal_at: fixedNow,
        secret_fingerprint: secretFingerprint(rotatedSecret),
        sessions: "0",
        verifications: "0",
      },
    ]);
    expect(invitations.rows).toEqual([
      { status: "revoked", terminal_at: fixedNow },
      { status: "revoked", terminal_at: fixedNow },
    ]);
  });
});

async function insertEffectiveCredentials(): Promise<void> {
  await owner.query(
    `
      INSERT INTO auth."user" (
        id, name, email, "emailVerified", "createdAt", "updatedAt", active
      )
      VALUES ($1, 'researcher', 'researcher@example.com', TRUE, $2, $2, TRUE)
    `,
    [userId, fixedNow],
  );
  await owner.query(
    `
      INSERT INTO auth."session" (
        id, "expiresAt", token, "createdAt", "updatedAt", "userId"
      )
      VALUES (
        '00000000-0000-4000-8000-000000000002',
        $2,
        'session-token',
        $3,
        $3,
        $1
      )
    `,
    [userId, new Date("2026-09-01T07:00:00.000Z"), fixedNow],
  );
  await owner.query(
    `
      INSERT INTO auth.researcher_invitation (
        id, email, token_hash, status, expires_at, created_at, delivered_at
      )
      VALUES
        (
          '00000000-0000-4000-8000-000000000003',
          'other@example.com',
          decode(repeat('11', 32), 'hex'),
          'delivered',
          $1,
          $2,
          $2
        ),
        (
          '00000000-0000-4000-8000-000000000006',
          'replacement@example.com',
          decode(repeat('33', 32), 'hex'),
          'replacement_pending',
          $1,
          $2,
          NULL
        )
    `,
    [new Date("2026-08-30T07:00:00.000Z"), fixedNow],
  );
  await owner.query(
    `
      INSERT INTO auth.password_reset (
        id, user_id, token_hash, status, expires_at, created_at, delivered_at
      )
      VALUES (
        '00000000-0000-4000-8000-000000000004',
        $1,
        decode(repeat('22', 32), 'hex'),
        'delivered',
        $2,
        $3,
        $3
      )
    `,
    [userId, new Date("2026-08-28T07:30:00.000Z"), fixedNow],
  );
  await owner.query(
    `
      INSERT INTO auth."verification" (
        id, identifier, value, "expiresAt", "createdAt", "updatedAt"
      )
      VALUES (
        '00000000-0000-4000-8000-000000000005',
        'reset-password:' || repeat('22', 32),
        $1,
        $2,
        $3,
        $3
      )
    `,
    [userId, new Date("2026-08-28T07:30:00.000Z"), fixedNow],
  );
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
