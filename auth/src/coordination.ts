import { AsyncLocalStorage } from "node:async_hooks";

import type { Pool, PoolClient } from "pg";

import { recordSecurityAudit } from "./audit.js";
import {
  lockAuthMutationShared,
  lockAuthMutationSharedSession,
  unlockAuthMutationSharedSession,
} from "./auth-mutation-lock.js";
import { canonicalizeEmail } from "./identity.js";
import { sha256 } from "./security.js";

type AuthDelegate = (request: Request) => Promise<Response> | Response;
type SessionReader = (headers: Headers) => Promise<unknown>;

class AuthCoordinationUnavailableError extends Error {
  readonly operationCompleted: boolean;
  readonly operationStarted: boolean;

  constructor(
    progress: Readonly<{
      operationCompleted: boolean;
      operationStarted: boolean;
    }> = { operationCompleted: false, operationStarted: false },
    options?: ErrorOptions,
  ) {
    super("AUTH_COORDINATION_UNAVAILABLE", options);
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
    let mutationLockHeld = false;
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
      try {
        await guard(lockAuthMutationSharedSession(client));
        mutationLockHeld = true;
      } catch (error) {
        unsafeConnection = true;
        throw error;
      }
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
      if (connectionError === undefined && mutationLockHeld) {
        try {
          if (!(await guard(unlockAuthMutationSharedSession(client)))) {
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
  compensateUncertainty?: "reset-credentials" | "sessions";
  existingSession?: Readonly<{ researcherId: string; token: string }>;
}>;

type CredentialMutationArtifacts = {
  cancelled: boolean;
  readonly passwordResets: Map<
    string,
    Readonly<{ researcherId: string; tokenHash: Buffer }>
  >;
  readonly researcherIds: Set<string>;
  readonly sessions: Map<string, string>;
};

export class CredentialOperationCoordinator {
  readonly #authSecret: string;
  readonly #artifacts = new AsyncLocalStorage<CredentialMutationArtifacts>();
  readonly #coordination: AuthOperationCoordinator;
  readonly #pool: Pool;
  readonly #serial = new KeyedSerialExecutor();

  constructor(dependencies: CredentialOperationCoordinatorDependencies) {
    this.#authSecret = dependencies.authSecret;
    this.#coordination = dependencies.coordination;
    this.#pool = dependencies.pool;
  }

  readonly recordPasswordResetCredential = (input: Readonly<{
    identifier: string;
    researcherId: string;
    tokenHash: Buffer;
  }>): void => {
    const artifacts = this.#artifacts.getStore();
    if (artifacts === undefined) return;
    artifacts.passwordResets.set(input.identifier, {
      researcherId: input.researcherId,
      tokenHash: Buffer.from(input.tokenHash),
    });
    artifacts.researcherIds.add(input.researcherId);
  };

  readonly recordSession = (input: Readonly<{
    researcherId: string;
    token: string;
  }>): void => {
    const artifacts = this.#artifacts.getStore();
    if (artifacts === undefined) return;
    artifacts.sessions.set(input.token, input.researcherId);
    artifacts.researcherIds.add(input.researcherId);
  };

  async runForEmail<T>(
    emailInput: string,
    operation: (client: PoolClient) => Promise<T>,
    options: CredentialOperationOptions = {},
  ): Promise<T> {
    const email = canonicalizeEmail(emailInput);
    const lockKey = credentialLockKey(email);
    const compensation = options.compensateUncertainty;
    const inheritedArtifacts = this.#artifacts.getStore();
    const artifacts = createCredentialMutationArtifacts(options.existingSession);
    const coordinated = async (): Promise<T> => {
      try {
        return await this.#coordination.run(
          [lockKey, ...(options.additionalLockKeys ?? [])],
          operation,
        );
      } catch (error) {
        if (
          error instanceof AuthCoordinationUnavailableError
          && error.operationStarted
          && compensation !== undefined
        ) {
          artifacts.cancelled = true;
          try {
            await this.#compensateCredentialUncertainty(artifacts, compensation);
          } catch (cause) {
            throw new AuthCoordinationUnavailableError(
              {
                operationCompleted: error.operationCompleted,
                operationStarted: error.operationStarted,
              },
              { cause },
            );
          }
        }
        throw error;
      }
    };
    return await this.#serial.run(
      lockKey,
      () => {
        if (inheritedArtifacts?.cancelled === true) {
          throw new AuthCoordinationUnavailableError();
        }
        return compensation === undefined
          ? coordinated()
          : this.#artifacts.run(artifacts, coordinated);
      },
    );
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
      {
        compensateUncertainty: context.compensation,
        existingSession: context.existingSession,
      },
    );
  }

  async #compensateCredentialUncertainty(
    artifacts: CredentialMutationArtifacts,
    compensation: "reset-credentials" | "sessions",
  ): Promise<void> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      await lockAuthMutationShared(client);
      const researcherIds = [...artifacts.researcherIds].sort();
      for (const researcherId of researcherIds) {
        await client.query(
          "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
          [researcherId],
        );
      }
      const revoked = await client.query<{ researcher_id: string }>(
        `
          DELETE FROM auth."session"
          WHERE token = ANY($1::text[])
          RETURNING "userId" AS researcher_id
        `,
        [[...artifacts.sessions.keys()]],
      );
      const occurredAt = new Date();
      if (compensation === "reset-credentials") {
        for (const [identifier, reset] of artifacts.passwordResets) {
          await client.query(
            `
              UPDATE auth.password_reset
              SET status = 'revoked', terminal_at = $3
              WHERE user_id = $1
                AND token_hash = $2
                AND status IN ('delivery_pending', 'delivered')
            `,
            [reset.researcherId, reset.tokenHash, occurredAt],
          );
          await client.query(
            `
              DELETE FROM auth."verification"
              WHERE value = $1 AND identifier = $2
            `,
            [reset.researcherId, identifier],
          );
        }
      }
      const revokedResearcherIds = new Set(
        revoked.rows.map((row) => row.researcher_id),
      );
      for (const researcherId of researcherIds) {
        await recordSecurityAudit(client, {
          authSecret: this.#authSecret,
          event: "sessions_revoked",
          identity: { researcherId },
          occurredAt,
          outcome: revokedResearcherIds.has(researcherId)
            ? "succeeded"
            : "no_change",
        });
      }
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

export function credentialLockKey(emailInput: string): string {
  const email = canonicalizeEmail(emailInput);
  return `researcher-credential:${sha256(`thesistrace:credential:${email}`).toString("hex")}`;
}

export function invitationTokenLockKey(tokenHash: Buffer): string {
  return `researcher-invitation-token:${tokenHash.toString("hex")}`;
}

async function credentialRequestContext(
  request: Request,
  getSession: SessionReader,
): Promise<Readonly<{
  compensation: "reset-credentials" | "sessions";
  email: string;
  existingSession?: Readonly<{ researcherId: string; token: string }>;
}> | undefined> {
  const path = new URL(request.url).pathname;
  if (
    path === "/api/auth/sign-in/email"
    || path === "/api/auth/request-password-reset"
  ) {
    const body = await jsonBody(request);
    if (typeof body?.email !== "string") return undefined;
    return {
      compensation:
        path === "/api/auth/request-password-reset"
          ? "reset-credentials"
          : "sessions",
      email: body.email,
    };
  }
  if (path !== "/api/auth/change-password" && path !== "/api/auth/sign-out") {
    return undefined;
  }
  const session = sessionCredential(await getSession(request.headers));
  return session === undefined
    ? undefined
    : {
        compensation: "sessions",
        email: session.email,
        existingSession: {
          researcherId: session.researcherId,
          token: session.sessionToken,
        },
      };
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

function sessionCredential(session: unknown): Readonly<{
  email: string;
  researcherId: string;
  sessionToken: string;
}> | undefined {
  if (
    session === null ||
    typeof session !== "object" ||
    !("session" in session) ||
    session.session === null ||
    typeof session.session !== "object" ||
    !("token" in session.session) ||
    typeof session.session.token !== "string" ||
    !("user" in session) ||
    session.user === null ||
    typeof session.user !== "object" ||
    !("id" in session.user) ||
    typeof session.user.id !== "string" ||
    !("email" in session.user) ||
    typeof session.user.email !== "string"
  ) {
    return undefined;
  }
  return {
    email: session.user.email,
    researcherId: session.user.id,
    sessionToken: session.session.token,
  };
}

function createCredentialMutationArtifacts(
  existingSession: Readonly<{ researcherId: string; token: string }> | undefined,
): CredentialMutationArtifacts {
  const artifacts: CredentialMutationArtifacts = {
    cancelled: false,
    passwordResets: new Map(),
    researcherIds: new Set(),
    sessions: new Map(),
  };
  if (existingSession !== undefined) {
    artifacts.sessions.set(existingSession.token, existingSession.researcherId);
    artifacts.researcherIds.add(existingSession.researcherId);
  }
  return artifacts;
}
