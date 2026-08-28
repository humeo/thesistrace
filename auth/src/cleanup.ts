import type { Pool } from "pg";

const DAY_MS = 24 * 60 * 60 * 1_000;
const TERMINAL_RETENTION_MS = 30 * DAY_MS;
const AUDIT_RETENTION_MS = 180 * DAY_MS;
const RATE_LIMIT_RETENTION_MS = DAY_MS;

export type AuthCleanupResult =
  | Readonly<{ status: "skipped" }>
  | Readonly<{
      deleted: Readonly<{
        audits: number;
        invitations: number;
        rateLimits: number;
        resets: number;
        sessions: number;
        verifications: number;
      }>;
      revoked: Readonly<{ invitations: number; resets: number }>;
      status: "completed";
    }>;

export async function runAuthCleanup(
  pool: Pool,
  clock: () => Date = () => new Date(),
): Promise<AuthCleanupResult> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
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
    const revokedInvitations = await client.query(
      `
        UPDATE auth.researcher_invitation
        SET status = 'revoked', terminal_at = $1
        WHERE status IN ('delivery_pending', 'delivered') AND expires_at <= $1
      `,
      [now],
    );
    const revokedResets = await client.query(
      `
        UPDATE auth.password_reset
        SET status = 'revoked', terminal_at = $1
        WHERE status IN ('delivery_pending', 'delivered') AND expires_at <= $1
      `,
      [now],
    );
    const audits = await client.query(
      "DELETE FROM auth.security_audit WHERE occurred_at < $1",
      [new Date(now.getTime() - AUDIT_RETENTION_MS)],
    );
    const invitations = await client.query(
      `
        DELETE FROM auth.researcher_invitation
        WHERE status IN ('delivery_failed', 'consumed', 'revoked')
          AND terminal_at < $1
      `,
      [new Date(now.getTime() - TERMINAL_RETENTION_MS)],
    );
    const resets = await client.query(
      `
        DELETE FROM auth.password_reset
        WHERE status IN ('delivery_failed', 'consumed', 'revoked')
          AND terminal_at < $1
      `,
      [new Date(now.getTime() - TERMINAL_RETENTION_MS)],
    );
    const sessions = await client.query(
      'DELETE FROM auth."session" WHERE "expiresAt" <= $1',
      [now],
    );
    const verifications = await client.query(
      'DELETE FROM auth."verification" WHERE "expiresAt" <= $1',
      [now],
    );
    const rateLimits = await client.query(
      'DELETE FROM auth."rateLimit" WHERE "lastRequest" < $1',
      [now.getTime() - RATE_LIMIT_RETENTION_MS],
    );
    await client.query("COMMIT");
    return {
      deleted: {
        audits: rowCount(audits),
        invitations: rowCount(invitations),
        rateLimits: rowCount(rateLimits),
        resets: rowCount(resets),
        sessions: rowCount(sessions),
        verifications: rowCount(verifications),
      },
      revoked: {
        invitations: rowCount(revokedInvitations),
        resets: rowCount(revokedResets),
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
