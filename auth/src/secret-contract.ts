import type { Pool } from "pg";

import { lockAuthMutationExclusive } from "./auth-mutation-lock.js";

import { secretFingerprint } from "./security.js";

export type AuthSecretContractResult = Readonly<{
  status: "initialized" | "rotated" | "unchanged";
}>;

export async function enforceAuthSecretContract(
  pool: Pool,
  secret: string,
  clock: () => Date = () => new Date(),
): Promise<AuthSecretContractResult> {
  const fingerprint = secretFingerprint(secret);
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await lockAuthMutationExclusive(client);
    await client.query(
      "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('thesistrace-auth-secret-contract', 0))",
    );
    const existing = await client.query<{ secret_fingerprint: string }>(
      `
        SELECT secret_fingerprint
        FROM auth.auth_secret_contract
        WHERE singleton = TRUE
        FOR UPDATE
      `,
    );
    const stored = existing.rows[0]?.secret_fingerprint;
    if (stored === undefined) {
      await client.query(
        `
          INSERT INTO auth.auth_secret_contract (singleton, secret_fingerprint)
          VALUES (TRUE, $1)
        `,
        [fingerprint],
      );
      await client.query("COMMIT");
      return { status: "initialized" };
    }
    if (stored === fingerprint) {
      await client.query("COMMIT");
      return { status: "unchanged" };
    }

    const now = clock();
    await client.query(
      `
        UPDATE auth.researcher_invitation
        SET status = 'revoked', terminal_at = $1
        WHERE status IN (
          'delivery_pending', 'replacement_pending', 'delivered'
        )
      `,
      [now],
    );
    await client.query(
      `
        UPDATE auth.password_reset
        SET status = 'revoked', terminal_at = $1
        WHERE status IN ('delivery_pending', 'delivered')
      `,
      [now],
    );
    await client.query(
      `
        DELETE FROM auth."verification"
        WHERE identifier LIKE 'reset-password:%'
      `,
    );
    await client.query('DELETE FROM auth."session"');
    await client.query(
      `
        UPDATE auth.auth_secret_contract
        SET secret_fingerprint = $1
        WHERE singleton = TRUE
      `,
      [fingerprint],
    );
    await client.query("COMMIT");
    return { status: "rotated" };
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}
