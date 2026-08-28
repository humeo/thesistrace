import type { Pool, PoolClient } from "pg";

import { recordSecurityAudit } from "./audit.js";
import { canonicalizeEmail } from "./identity.js";
import { unknownEmailHmac } from "./security.js";

type AuthDelegate = (request: Request) => Promise<Response> | Response;
type SessionReader = (headers: Headers) => Promise<unknown>;

export class AuthCoordinationUnavailableError extends Error {
  readonly operationCompleted: boolean;
  readonly operationStarted: boolean;

  constructor(
    progress: Readonly<{
      operationCompleted: boolean;
      operationStarted: boolean;
    }> = { operationCompleted: false, operationStarted: false },
  ) {
    super("AUTH_COORDINATION_UNAVAILABLE");
    this.name = "AuthCoordinationUnavailableError";
    this.operationCompleted = progress.operationCompleted;
    this.operationStarted = progress.operationStarted;
  }
}

export class AuthOperationCoordinator {
  readonly #pool: Pool;

  constructor(pool: Pool) {
    this.#pool = pool;
  }

  async run<T>(
    lockKeys: readonly string[],
    operation: (client: PoolClient) => Promise<T>,
  ): Promise<T> {
    const keys = [...new Set(lockKeys)].sort();
    if (keys.length === 0) {
      throw new Error("AUTH_COORDINATION_KEY_REQUIRED");
    }
    let client: PoolClient;
    try {
      client = await this.#pool.connect();
    } catch {
      throw new AuthCoordinationUnavailableError();
    }
    const lockedKeys: string[] = [];
    let unsafeConnection = false;
    let operationCompleted = false;
    let operationStarted = false;
    let connectionError: Error | undefined;
    let rejectConnectionFailure: (error: Error) => void = () => undefined;
    const connectionFailure = new Promise<never>((_resolve, reject) => {
      rejectConnectionFailure = reject;
    });
    void connectionFailure.catch(() => undefined);
    const onClientError = (error: Error) => {
      unsafeConnection = true;
      connectionError = error;
      rejectConnectionFailure(error);
    };
    client.on("error", onClientError);
    const guard = <T>(promise: Promise<T>): Promise<T> =>
      Promise.race([promise, connectionFailure]);
    try {
      for (const key of keys) {
        try {
          await guard(
            client.query(
              "SELECT pg_catalog.pg_advisory_lock(pg_catalog.hashtextextended($1, 0))",
              [key],
            ),
          );
        } catch (error) {
          unsafeConnection = true;
          throw error;
        }
        lockedKeys.push(key);
      }
      operationStarted = true;
      const result = await operation(client);
      operationCompleted = true;
      return result;
    } finally {
      for (const key of connectionError === undefined ? lockedKeys.reverse() : []) {
        try {
          const released = await guard(
            client.query<{ unlocked: boolean }>(
              `
                SELECT pg_catalog.pg_advisory_unlock(
                  pg_catalog.hashtextextended($1, 0)
                ) AS unlocked
              `,
              [key],
            ),
          );
          if (released.rows[0]?.unlocked !== true) {
            unsafeConnection = true;
          }
        } catch {
          unsafeConnection = true;
        }
      }
      client.off("error", onClientError);
      const failClosed = unsafeConnection;
      const coordinationError = new AuthCoordinationUnavailableError({
        operationCompleted,
        operationStarted,
      });
      client.release(failClosed ? coordinationError : undefined);
      if (failClosed) {
        throw coordinationError;
      }
    }
  }
}

export type CredentialOperationCoordinatorDependencies = Readonly<{
  authSecret: string;
  coordination: AuthOperationCoordinator;
  pool: Pool;
}>;

export type CredentialOperationOptions = Readonly<{
  additionalLockKeys?: readonly string[];
  compensateSessionUncertainty?: boolean;
}>;

export class CredentialOperationCoordinator {
  readonly #authSecret: string;
  readonly #coordination: AuthOperationCoordinator;
  readonly #pool: Pool;
  readonly #serial = new KeyedSerialExecutor();

  constructor(dependencies: CredentialOperationCoordinatorDependencies) {
    this.#authSecret = dependencies.authSecret;
    this.#coordination = dependencies.coordination;
    this.#pool = dependencies.pool;
  }

  runForEmail<T>(
    emailInput: string,
    operation: (client: PoolClient) => Promise<T>,
    options: CredentialOperationOptions = {},
  ): Promise<T> {
    const email = canonicalizeEmail(emailInput);
    const lockKey = credentialLockKey(this.#authSecret, email);
    return this.#serial.run(lockKey, async () => {
      try {
        return await this.#coordination.run(
          [lockKey, ...(options.additionalLockKeys ?? [])],
          operation,
        );
      } catch (error) {
        if (
          error instanceof AuthCoordinationUnavailableError &&
          error.operationStarted &&
          options.compensateSessionUncertainty === true
        ) {
          await this.#compensateSessionUncertainty(email);
        }
        throw error;
      }
    });
  }

  async handleAuthRequest(
    request: Request,
    delegate: AuthDelegate,
    getSession: SessionReader,
  ): Promise<Response> {
    const context = await credentialRequestContext(request, getSession);
    if (context === undefined) {
      return await delegate(request);
    }
    return await this.runForEmail(
      context.email,
      async () => await delegate(request),
      { compensateSessionUncertainty: true },
    );
  }

  async #compensateSessionUncertainty(email: string): Promise<void> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const researcher = await client.query<{ id: string }>(
        'SELECT id FROM auth."user" WHERE email = $1 FOR UPDATE',
        [email],
      );
      const researcherId = researcher.rows[0]?.id;
      if (researcherId === undefined) {
        await client.query("COMMIT");
        return;
      }
      const revoked = await client.query(
        'DELETE FROM auth."session" WHERE "userId" = $1',
        [researcherId],
      );
      await recordSecurityAudit(client, {
        authSecret: this.#authSecret,
        event: "sessions_revoked",
        identity: { researcherId },
        occurredAt: new Date(),
        outcome: revoked.rowCount === 0 ? "no_change" : "succeeded",
      });
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }
}

export class KeyedSerialExecutor {
  readonly #tails = new Map<string, Promise<void>>();

  async run<T>(key: string, operation: () => Promise<T>): Promise<T> {
    const previous = this.#tails.get(key) ?? Promise.resolve();
    let release: () => void = () => undefined;
    const current = new Promise<void>((resolve) => {
      release = resolve;
    });
    const tail = previous.catch(() => undefined).then(() => current);
    this.#tails.set(key, tail);
    await previous.catch(() => undefined);
    try {
      return await operation();
    } finally {
      release();
      if (this.#tails.get(key) === tail) {
        this.#tails.delete(key);
      }
    }
  }
}

export function credentialLockKey(authSecret: string, email: string): string {
  return `researcher-credential:${unknownEmailHmac(authSecret, email).toString("hex")}`;
}

export function invitationTokenLockKey(tokenHash: Buffer): string {
  return `researcher-invitation-token:${tokenHash.toString("hex")}`;
}

async function credentialRequestContext(
  request: Request,
  getSession: SessionReader,
): Promise<Readonly<{ email: string }> | undefined> {
  const path = new URL(request.url).pathname;
  if (path === "/api/auth/sign-in/email") {
    const body = await jsonBody(request);
    return typeof body?.email === "string" ? { email: body.email } : undefined;
  }
  if (path !== "/api/auth/change-password") {
    return undefined;
  }
  const session = await getSession(request.headers);
  const email = sessionEmail(session);
  return email === undefined ? undefined : { email };
}

async function jsonBody(
  request: Request,
): Promise<Record<string, unknown> | null> {
  try {
    const value: unknown = await request.clone().json();
    return value !== null && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function sessionEmail(session: unknown): string | undefined {
  if (
    session === null ||
    typeof session !== "object" ||
    !("user" in session) ||
    session.user === null ||
    typeof session.user !== "object" ||
    !("email" in session.user) ||
    typeof session.user.email !== "string"
  ) {
    return undefined;
  }
  return session.user.email;
}
