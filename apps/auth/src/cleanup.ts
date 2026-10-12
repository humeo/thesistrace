import type { Pool } from "pg";

import { lockAuthMutationShared } from "./auth-mutation-lock.js";

const DAY_MS = 24 * 60 * 60 * 1_000;
const AUDIT_RETENTION_MS = 180 * DAY_MS;
const RATE_LIMIT_RETENTION_MS = DAY_MS;

export type AuthCleanupResult =
  | Readonly<{ status: "skipped" }>
  | Readonly<{
      deleted: Readonly<{
        audits: number;
        proofs: number;
        oauthAccessTokens: number;
        oauthRefreshTokens: number;
        oauthAssertions: number;
        rateLimits: number;
        sessions: number;
        verifications: number;
      }>;
      status: "completed";
    }>;

export async function runAuthCleanup(
  pool: Pool,
  clock: () => Date = () => new Date(),
): Promise<AuthCleanupResult> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await lockAuthMutationShared(client);
    const lock = await client.query<{ acquired: boolean }>(
      `
        SELECT pg_catalog.pg_try_advisory_xact_lock(
          pg_catalog.hashtextextended('thesistrace-auth-daily-cleanup', 0)
        ) AS acquired
      `,
    );
    if (lock.rows[0]?.acquired !== true) {
      await client.query("COMMIT");
      return { status: "skipped" };
    }

    const now = clock();
    const audits = await client.query(
      "DELETE FROM auth.security_audit WHERE occurred_at < $1",
      [new Date(now.getTime() - AUDIT_RETENTION_MS)],
    );
    const proofs = await client.query(
      "DELETE FROM auth.operator_proof WHERE expires_at <= $1",
      [now],
    );
    const sessions = await client.query(
      'DELETE FROM auth."session" WHERE "expiresAt" <= $1',
      [now],
    );
    const verifications = await client.query(
      'DELETE FROM auth."verification" WHERE "expiresAt" <= $1',
      [now],
    );
    const oauthAccessTokens = await client.query('DELETE FROM auth."oauthAccessToken" WHERE "expiresAt" <= $1 OR revoked IS NOT NULL', [now]);
    const oauthRefreshTokens = await client.query('DELETE FROM auth."oauthRefreshToken" WHERE "expiresAt" <= $1', [now]);
    const oauthAssertions = await client.query('DELETE FROM auth."oauthClientAssertion" WHERE "expiresAt" <= $1', [now]);
    const rateLimits = await client.query(
      'DELETE FROM auth."rateLimit" WHERE "lastRequest" < $1',
      [now.getTime() - RATE_LIMIT_RETENTION_MS],
    );
    await client.query("COMMIT");
    return {
      deleted: {
        audits: rowCount(audits),
        proofs: rowCount(proofs),
        oauthAccessTokens: rowCount(oauthAccessTokens),
        oauthRefreshTokens: rowCount(oauthRefreshTokens),
        oauthAssertions: rowCount(oauthAssertions),
        rateLimits: rowCount(rateLimits),
        sessions: rowCount(sessions),
        verifications: rowCount(verifications),
      },
      status: "completed",
    };
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

function rowCount(result: Readonly<{ rowCount: number | null }>): number {
  return result.rowCount ?? 0;
}
