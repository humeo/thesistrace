import { hashPassword } from "better-auth/crypto";
import type { Pool } from "pg";
import type { DevelopmentAccountSettings } from "./config.js";

/** Seed only a new Development identity; restarts preserve password and authority changes. */
export async function initializeDevelopmentAccount(
  pool: Pool, settings: DevelopmentAccountSettings,
): Promise<void> {
  const password = await hashPassword(settings.password);
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const created = await client.query<{ id: string }>(
      `INSERT INTO auth."user" (name, email, "emailVerified", active)
       VALUES ($1, $2, TRUE, TRUE)
       ON CONFLICT (email) DO NOTHING RETURNING id`,
      [settings.name, settings.email],
    );
    const user = created.rows[0];
    if (user !== undefined) {
      await client.query(
        `INSERT INTO auth."account"
           (issuer, "accountId", "providerId", "userId", password, "updatedAt")
         VALUES ('local:credential', $1::text, 'credential', $1::uuid, $2, CURRENT_TIMESTAMP)`,
        [user.id, password],
      );
      await client.query(
        `INSERT INTO auth.operator_assignment (singleton, researcher_id)
         VALUES (TRUE, $1) ON CONFLICT (singleton) DO NOTHING`,
        [user.id],
      );
    }
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}
