import { randomUUID } from "node:crypto";

import { hashPassword } from "better-auth/crypto";
import type { Pool, PoolClient } from "pg";

import { recordSecurityAudit } from "./audit.js";
import { lockAuthMutationShared } from "./auth-mutation-lock.js";
import {
  type CredentialOperationCoordinator,
  KeyedSerialExecutor,
} from "./coordination.js";
import type { ResendEmail } from "./resend.js";
import { passwordResetIdentifier } from "./password-reset-token.js";
import { sha256 } from "./security.js";

const RESET_LIFETIME_MS = 30 * 60 * 1_000;

type ResetUser = Readonly<{
  email: string;
  id: string;
  name: string;
}>;

export type PasswordResetDependencies = Readonly<{
  authSecret: string;
  backgroundTask: (promise: Promise<unknown>) => void;
  clock?: () => Date;
  credentialCoordinator: CredentialOperationCoordinator;
  createId?: () => string;
  pool: Pool;
  publicOrigin: string;
  sendEmail: (email: ResendEmail) => Promise<void>;
}>;

export class PasswordResetRejectedError extends Error {
  readonly code = "PASSWORD_RESET_INVALID";

  constructor() {
    super("PASSWORD_RESET_INVALID");
    this.name = "PasswordResetRejectedError";
  }
}

export class PasswordResetLifecycle {
  readonly #authSecret: string;
  readonly #backgroundTask: (promise: Promise<unknown>) => void;
  readonly #clock: () => Date;
  readonly #credentialCoordinator: CredentialOperationCoordinator;
  readonly #createId: () => string;
  readonly #deliverySerial = new KeyedSerialExecutor();
  readonly #pool: Pool;
  readonly #publicOrigin: string;
  readonly #sendEmail: (email: ResendEmail) => Promise<void>;

  constructor(dependencies: PasswordResetDependencies) {
    this.#authSecret = dependencies.authSecret;
    this.#backgroundTask = dependencies.backgroundTask;
    this.#clock = dependencies.clock ?? (() => new Date());
    this.#credentialCoordinator = dependencies.credentialCoordinator;
    this.#createId = dependencies.createId ?? randomUUID;
    this.#pool = dependencies.pool;
    this.#publicOrigin = dependencies.publicOrigin;
    this.#sendEmail = dependencies.sendEmail;
  }

  readonly isResearcherActive = async (userId: string): Promise<boolean> => {
    const result = await this.#pool.query<{ active: boolean }>(
      'SELECT active FROM auth."user" WHERE id = $1',
      [userId],
    );
    return result.rows[0]?.active === true;
  };

  readonly sendResetPassword = async (
    data: Readonly<{ token: string; url: string; user: ResetUser }>,
  ): Promise<void> => {
    const resetId = this.#createId();
    const tokenHash = sha256(data.token);
    await this.#deliverySerial.run(data.user.email, async () => {
      const prepared = await this.#credentialCoordinator.runForEmail(
        data.user.email,
        async () =>
          await this.#transaction(async (client) => {
            const now = this.#clock();
            await advisoryLock(client, data.user.id);
            const user = await client.query<{ active: boolean; email: string }>(
              'SELECT active, email FROM auth."user" WHERE id = $1 FOR UPDATE',
              [data.user.id],
            );
            const persistedUser = user.rows[0];
            if (persistedUser === undefined || !persistedUser.active) {
              await revokeEffectiveResets(client, data.user.id, now);
              await deleteResetVerification(client, data.user.id, data.token);
              if (persistedUser !== undefined) {
                await recordSecurityAudit(client, {
                  authSecret: this.#authSecret,
                  event: "password_reset_requested",
                  identity: { researcherId: data.user.id },
                  occurredAt: now,
                  outcome: "rejected",
                });
              }
              return undefined;
            }
            if (
              !(await hasEffectiveResetVerification(
                client,
                data.user.id,
                data.token,
                now,
              ))
            ) {
              return undefined;
            }
            const pending = await client.query(
              `
                SELECT 1
                FROM auth.password_reset
                WHERE user_id = $1
                  AND status = 'delivery_pending'
                  AND expires_at > $2
                FOR UPDATE
              `,
              [data.user.id, now],
            );
            if (pending.rowCount !== 0) {
              await deleteResetVerification(client, data.user.id, data.token);
              return undefined;
            }

            await revokeEffectiveResets(client, data.user.id, now);
            await client.query(
              `
                DELETE FROM auth."verification"
                WHERE value = $1
                  AND identifier LIKE 'reset-password:%'
                  AND identifier <> $2
              `,
              [data.user.id, passwordResetIdentifier(data.token)],
            );
            await client.query(
              `
                INSERT INTO auth.password_reset (
                  id,
                  user_id,
                  token_hash,
                  status,
                  expires_at,
                  created_at
                )
                VALUES ($1, $2, $3, 'delivery_pending', $4, $5)
              `,
              [
                resetId,
                data.user.id,
                tokenHash,
                new Date(now.getTime() + RESET_LIFETIME_MS),
                now,
              ],
            );
            return { email: persistedUser.email, userId: data.user.id };
          }),
      );
      if (prepared === undefined) {
        return;
      }

      let delivered = true;
      try {
        await this.#sendEmail(
          passwordResetEmail(
            this.#publicOrigin,
            prepared.email,
            data.token,
          ),
        );
      } catch {
        delivered = false;
      }

      await this.#credentialCoordinator.runForEmail(
        prepared.email,
        async () =>
          await this.#transaction(async (client) => {
            const now = this.#clock();
            await advisoryLock(client, prepared.userId);
            const pending = await client.query<{ id: string }>(
              `
                SELECT id
                FROM auth.password_reset
                WHERE id = $1
                  AND user_id = $2
                  AND token_hash = $3
                  AND status = 'delivery_pending'
                FOR UPDATE
              `,
              [resetId, prepared.userId, tokenHash],
            );
            if (pending.rowCount !== 1) {
              return;
            }
            if (!delivered) {
              await client.query(
                `
                  UPDATE auth.password_reset
                  SET status = 'delivery_failed', terminal_at = $2
                  WHERE id = $1 AND status = 'delivery_pending'
                `,
                [resetId, now],
              );
              await deleteResetVerification(
                client,
                prepared.userId,
                data.token,
              );
              await recordSecurityAudit(client, {
                authSecret: this.#authSecret,
                event: "password_reset_requested",
                identity: { researcherId: prepared.userId },
                occurredAt: now,
                outcome: "failed",
              });
              return;
            }
            await client.query(
              `
                UPDATE auth.password_reset
                SET status = 'delivered', delivered_at = $2
                WHERE id = $1 AND status = 'delivery_pending'
              `,
              [resetId, now],
            );
            await recordSecurityAudit(client, {
              authSecret: this.#authSecret,
              event: "password_reset_requested",
              identity: { researcherId: prepared.userId },
              occurredAt: now,
              outcome: "succeeded",
            });
          }),
      );
    });
  };

  readonly completeReset = async (
    token: string,
    newPassword: string,
  ): Promise<void> => {
    try {
      const candidate = await this.#pool.query<{ email: string }>(
        `
          SELECT researcher.email
          FROM auth."verification" AS verification
          JOIN auth."user" AS researcher
            ON researcher.id::text = verification.value
           AND researcher.active = TRUE
          WHERE verification.identifier = $1
            AND verification."expiresAt" > $2
        `,
        [passwordResetIdentifier(token), this.#clock()],
      );
      const email = candidate.rows[0]?.email;
      if (email === undefined) {
        throw new PasswordResetRejectedError();
      }
      await this.#credentialCoordinator.runForEmail(email, async () => {
        const passwordHash = await hashPassword(newPassword);
        await this.#transaction(async (client) => {
          const now = this.#clock();
          const identifier = passwordResetIdentifier(token);
          const hinted = await client.query<{ value: string }>(
            `
              SELECT value
              FROM auth."verification"
              WHERE identifier = $1
            `,
            [identifier],
          );
          const userId = hinted.rows[0]?.value;
          if (userId === undefined) {
            throw new PasswordResetRejectedError();
          }
          await advisoryLock(client, userId);
          const verification = await client.query<{ id: string }>(
            `
              SELECT id
              FROM auth."verification"
              WHERE identifier = $1
                AND value = $2
                AND "expiresAt" > $3
              FOR UPDATE
            `,
            [identifier, userId, now],
          );
          const verificationId = verification.rows[0]?.id;
          if (verificationId === undefined) {
            throw new PasswordResetRejectedError();
          }
          const user = await client.query<{ active: boolean }>(
            'SELECT active FROM auth."user" WHERE id = $1 FOR UPDATE',
            [userId],
          );
          if (user.rows[0]?.active !== true) {
            throw new PasswordResetRejectedError();
          }
          const reset = await client.query<{ id: string }>(
            `
              SELECT id
              FROM auth.password_reset
              WHERE user_id = $1
                AND token_hash = $2
                AND status = 'delivered'
                AND expires_at > $3
              FOR UPDATE
            `,
            [userId, sha256(token), now],
          );
          const resetId = reset.rows[0]?.id;
          if (resetId === undefined) {
            throw new PasswordResetRejectedError();
          }
          const credential = await client.query(
            `
              UPDATE auth."account"
              SET password = $2, "updatedAt" = $3
              WHERE "userId" = $1
                AND "providerId" = 'credential'
                AND password IS NOT NULL
            `,
            [userId, passwordHash, now],
          );
          if (credential.rowCount !== 1) {
            throw new Error("PASSWORD_RESET_CREDENTIAL_INVALID");
          }
          await client.query(
            'DELETE FROM auth."session" WHERE "userId" = $1',
            [userId],
          );
          const deletedVerification = await client.query(
            'DELETE FROM auth."verification" WHERE id = $1',
            [verificationId],
          );
          if (deletedVerification.rowCount !== 1) {
            throw new Error("PASSWORD_RESET_VERIFICATION_INVALID");
          }
          const consumed = await client.query(
            `
              UPDATE auth.password_reset
              SET status = 'consumed', terminal_at = $3
              WHERE id = $1 AND user_id = $2 AND status = 'delivered'
            `,
            [resetId, userId, now],
          );
          if (consumed.rowCount !== 1) {
            throw new Error("PASSWORD_RESET_LIFECYCLE_INVALID");
          }
          await recordSecurityAudit(client, {
            authSecret: this.#authSecret,
            event: "password_reset_succeeded",
            identity: { researcherId: userId },
            occurredAt: now,
            outcome: "succeeded",
          });
        });
      });
    } catch (error) {
      if (error instanceof PasswordResetRejectedError) {
        this.#backgroundTask(this.#recordRejectedReset(token));
      }
      throw error;
    }
  };

  async #recordRejectedReset(token: string): Promise<void> {
    await this.#transaction(async (client) => {
      const reset = await client.query<{ user_id: string }>(
        `
          SELECT user_id
          FROM auth.password_reset
          WHERE token_hash = $1
        `,
        [sha256(token)],
      );
      const userId = reset.rows[0]?.user_id;
      if (userId === undefined) {
        return;
      }
      await recordSecurityAudit(client, {
        authSecret: this.#authSecret,
        event: "password_reset_failed",
        identity: { researcherId: userId },
        occurredAt: this.#clock(),
        outcome: "failed",
      });
    });
  }

  async #transaction<T>(
    operation: (client: PoolClient) => Promise<T>,
  ): Promise<T> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      await lockAuthMutationShared(client);
      const result = await operation(client);
      await client.query("COMMIT");
      return result;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }
}

async function advisoryLock(client: PoolClient, userId: string): Promise<void> {
  await client.query(
    "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
    [userId],
  );
}

async function revokeEffectiveResets(
  client: PoolClient,
  userId: string,
  now: Date,
): Promise<void> {
  await client.query(
    `
      UPDATE auth.password_reset
      SET status = 'revoked', terminal_at = $2
      WHERE user_id = $1 AND status IN ('delivery_pending', 'delivered')
    `,
    [userId, now],
  );
}

async function deleteResetVerification(
  client: PoolClient,
  userId: string,
  token: string,
): Promise<void> {
  await client.query(
    `
      DELETE FROM auth."verification"
      WHERE identifier = $1 AND value = $2
    `,
    [passwordResetIdentifier(token), userId],
  );
}

async function hasEffectiveResetVerification(
  client: PoolClient,
  userId: string,
  token: string,
  now: Date,
): Promise<boolean> {
  const result = await client.query(
    `
      SELECT 1
      FROM auth."verification"
      WHERE identifier = $1
        AND value = $2
        AND "expiresAt" > $3
      FOR UPDATE
    `,
    [passwordResetIdentifier(token), userId, now],
  );
  return result.rowCount === 1;
}

function passwordResetEmail(
  publicOrigin: string,
  email: string,
  token: string,
): ResendEmail {
  const link = `${publicOrigin}/reset-password#token=${encodeURIComponent(token)}`;
  return {
    html: `<p>Reset your ThesisTrace password.</p><p><a href="${link}">Reset password</a></p>`,
    subject: "Reset your ThesisTrace password",
    text: `Reset your ThesisTrace password: ${link}`,
    to: email,
  };
}
