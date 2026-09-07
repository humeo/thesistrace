import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { runAuthCleanup } from "./cleanup.js";
import { createAuthPool } from "./database.js";
import { initializeAuthSchema } from "./schema-initialize.js";

const DAY_MS = 24 * 60 * 60 * 1_000;
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
const fixedNow = new Date("2026-08-28T08:00:00.000Z");

describe.sequential("daily Auth cleanup", () => {
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

  it("retains current state, terminalizes expired grants, and deletes expired retention state", async () => {
    await insertCleanupFixture();

    await expect(runAuthCleanup(runtimePool, () => fixedNow)).resolves.toEqual({
      deleted: {
        audits: 1,
        invitations: 1,
        proofs: 1,
        oauthAccessTokens: 0,
        oauthRefreshTokens: 0,
        oauthAssertions: 0,
        rateLimits: 1,
        resets: 1,
        sessions: 1,
        verifications: 1,
      },
      revoked: { invitations: 1, resets: 1 },
      status: "completed",
    });

    expect(await retainedState()).toEqual({
      audits: 1,
      invitationStatuses: ["delivered", "revoked"],
      proofs: 1,
      rateLimits: 1,
      resetStatuses: ["delivered", "revoked"],
      sessions: 1,
      verifications: 1,
    });
    expect(
      await owner.query<{ terminal_at: Date }>(`
        SELECT terminal_at
        FROM auth.researcher_invitation
        WHERE status = 'revoked'
        UNION ALL
        SELECT terminal_at
        FROM auth.password_reset
        WHERE status = 'revoked'
      `),
    ).toMatchObject({ rows: [{ terminal_at: fixedNow }, { terminal_at: fixedNow }] });
  });

  it("skips immediately while another Auth process owns the cleanup lock", async () => {
    const lockOwner = await owner.connect();
    try {
      await lockOwner.query("BEGIN");
      await lockOwner.query(
        "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('thesistrace-auth-daily-cleanup', 0))",
      );

      await expect(runAuthCleanup(runtimePool, () => fixedNow)).resolves.toEqual({
        status: "skipped",
      });
    } finally {
      await lockOwner.query("ROLLBACK").catch(() => undefined);
      lockOwner.release();
    }
  });
});

async function insertCleanupFixture(): Promise<void> {
  const oldAudit = new Date(fixedNow.getTime() - 181 * DAY_MS);
  const currentAudit = new Date(fixedNow.getTime() - 179 * DAY_MS);
  const oldTerminal = new Date(fixedNow.getTime() - 31 * DAY_MS);
  const expired = new Date(fixedNow.getTime() - 1);
  const current = new Date(fixedNow.getTime() + DAY_MS);
  await owner.query(
    `
      INSERT INTO auth."user" (
        id, name, email, "emailVerified", "createdAt", "updatedAt", active
      )
      VALUES
        ('00000000-0000-4000-8000-000000000001', 'one', 'one@example.com', TRUE, $1, $1, TRUE),
        ('00000000-0000-4000-8000-000000000002', 'two', 'two@example.com', TRUE, $1, $1, TRUE)
    `,
    [fixedNow],
  );
  await owner.query(
    `
      INSERT INTO auth.security_audit (
        id, occurred_at, event, outcome, researcher_id
      )
      VALUES
        ('00000000-0000-4000-8000-000000000011', $1, 'sign_in_succeeded', 'succeeded', '00000000-0000-4000-8000-000000000001'),
        ('00000000-0000-4000-8000-000000000012', $2, 'sign_in_succeeded', 'succeeded', '00000000-0000-4000-8000-000000000001')
    `,
    [oldAudit, currentAudit],
  );
  await owner.query(
    `
      INSERT INTO auth.researcher_invitation (
        id, email, token_hash, status, expires_at, created_at, delivered_at, terminal_at
      )
      VALUES
        ('00000000-0000-4000-8000-000000000021', 'old@example.com', decode(repeat('11', 32), 'hex'), 'revoked', $1, $2, NULL, $2),
        ('00000000-0000-4000-8000-000000000022', 'expired@example.com', decode(repeat('22', 32), 'hex'), 'delivered', $3, $2, $2, NULL),
        ('00000000-0000-4000-8000-000000000023', 'current@example.com', decode(repeat('33', 32), 'hex'), 'delivered', $4, $2, $2, NULL)
    `,
    [expired, oldTerminal, expired, current],
  );
  await owner.query(
    `
      INSERT INTO auth.password_reset (
        id, user_id, token_hash, status, expires_at, created_at, delivered_at, terminal_at
      )
      VALUES
        ('00000000-0000-4000-8000-000000000031', '00000000-0000-4000-8000-000000000001', decode(repeat('44', 32), 'hex'), 'revoked', $1, $2, NULL, $2),
        ('00000000-0000-4000-8000-000000000032', '00000000-0000-4000-8000-000000000001', decode(repeat('55', 32), 'hex'), 'delivered', $3, $2, $2, NULL),
        ('00000000-0000-4000-8000-000000000033', '00000000-0000-4000-8000-000000000002', decode(repeat('66', 32), 'hex'), 'delivered', $4, $2, $2, NULL)
    `,
    [expired, oldTerminal, expired, current],
  );
  await owner.query(
    `
      INSERT INTO auth."session" (
        id, "expiresAt", token, "createdAt", "updatedAt", "userId"
      )
      VALUES
        ('00000000-0000-4000-8000-000000000041', $1, 'expired-session', $2, $2, '00000000-0000-4000-8000-000000000001'),
        ('00000000-0000-4000-8000-000000000042', $3, 'current-session', $2, $2, '00000000-0000-4000-8000-000000000001')
    `,
    [expired, fixedNow, current],
  );
  await owner.query(
    `
      INSERT INTO auth.operator_proof (
        id, token_hash, session_id, operation, request_hash, state,
        expires_at, created_at
      )
      VALUES
        ('00000000-0000-4000-8000-000000000071', decode(repeat('77', 32), 'hex'), '00000000-0000-4000-8000-000000000042', 'invitation.issue', decode(repeat('78', 32), 'hex'), 'available', $1, $2),
        ('00000000-0000-4000-8000-000000000072', decode(repeat('88', 32), 'hex'), '00000000-0000-4000-8000-000000000042', 'invitation.reissue', decode(repeat('89', 32), 'hex'), 'available', $3, $2)
    `,
    [expired, new Date(fixedNow.getTime() - DAY_MS), current],
  );
  await owner.query(
    `
      INSERT INTO auth."verification" (
        id, identifier, value, "expiresAt", "createdAt", "updatedAt"
      )
      VALUES
        ('00000000-0000-4000-8000-000000000051', 'other:expired', 'expired', $1, $2, $2),
        ('00000000-0000-4000-8000-000000000052', 'other:current', 'current', $3, $2, $2)
    `,
    [expired, fixedNow, current],
  );
  await owner.query(
    `
      INSERT INTO auth."rateLimit" (id, key, count, "lastRequest")
      VALUES
        ('00000000-0000-4000-8000-000000000061', 'expired', 1, $1),
        ('00000000-0000-4000-8000-000000000062', 'current', 1, $2)
    `,
    [fixedNow.getTime() - DAY_MS - 1, fixedNow.getTime()],
  );
}

async function retainedState(): Promise<{
  audits: number;
  invitationStatuses: string[];
  proofs: number;
  rateLimits: number;
  resetStatuses: string[];
  sessions: number;
  verifications: number;
}> {
  const result = await owner.query<{
    audits: string;
    invitation_statuses: string[];
    proofs: string;
    rate_limits: string;
    reset_statuses: string[];
    sessions: string;
    verifications: string;
  }>(`
    SELECT
      (SELECT count(*) FROM auth.security_audit) AS audits,
      (SELECT array_agg(status ORDER BY status) FROM auth.researcher_invitation) AS invitation_statuses,
      (SELECT count(*) FROM auth.operator_proof) AS proofs,
      (SELECT count(*) FROM auth."rateLimit") AS rate_limits,
      (SELECT array_agg(status ORDER BY status) FROM auth.password_reset) AS reset_statuses,
      (SELECT count(*) FROM auth."session") AS sessions,
      (SELECT count(*) FROM auth."verification") AS verifications
  `);
  const row = result.rows[0];
  if (row === undefined) {
    throw new Error("expected cleanup state");
  }
  return {
    audits: Number(row.audits),
    invitationStatuses: row.invitation_statuses,
    proofs: Number(row.proofs),
    rateLimits: Number(row.rate_limits),
    resetStatuses: row.reset_statuses,
    sessions: Number(row.sessions),
    verifications: Number(row.verifications),
  };
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
