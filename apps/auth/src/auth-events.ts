import type { Pool, PoolClient } from "pg";

import { recordSecurityAudit, type SecurityAuditEvent } from "./audit.js";

type AuthDelegate = (request: Request) => Promise<Response> | Response;
type SessionReader = (headers: Headers) => Promise<unknown>;

type RequestSnapshot = Readonly<{
  email?: string;
  path: string;
  researcherId?: string;
}>;

export type AuthEventRecorderDependencies = Readonly<{
  authSecret: string;
  backgroundTask: (promise: Promise<unknown>) => void;
  clock?: () => Date;
  pool: Pool;
}>;

export class AuthEventRecorder {
  readonly #authSecret: string;
  readonly #backgroundTask: (promise: Promise<unknown>) => void;
  readonly #clock: () => Date;
  readonly #pool: Pool;

  constructor(dependencies: AuthEventRecorderDependencies) {
    this.#authSecret = dependencies.authSecret;
    this.#backgroundTask = dependencies.backgroundTask;
    this.#clock = dependencies.clock ?? (() => new Date());
    this.#pool = dependencies.pool;
  }

  async handle(
    request: Request,
    delegate: AuthDelegate,
    getSession: SessionReader,
  ): Promise<Response> {
    const snapshot = await requestSnapshot(request, getSession);
    const response = await delegate(request);
    this.#backgroundTask(this.#record(snapshot, response.ok));
    return response;
  }

  async #record(snapshot: RequestSnapshot, succeeded: boolean): Promise<void> {
    if (snapshot.path === "/api/auth/sign-in/email-otp" && snapshot.email !== undefined) {
      await this.#recordEmailIdentity(
        snapshot.email,
        succeeded ? "sign_in_succeeded" : "sign_in_failed",
        succeeded ? "succeeded" : "failed",
      );
      return;
    }
    if (
      snapshot.path === "/api/auth/request-password-reset" &&
      snapshot.email !== undefined
    ) {
      await this.#recordUnknownResetRequest(snapshot.email);
      return;
    }
    if (
      snapshot.path === "/api/auth/change-password" &&
      snapshot.researcherId !== undefined
    ) {
      await this.#recordKnownEvents(snapshot.researcherId, [
        ["password_changed", succeeded ? "succeeded" : "failed"],
        ...(succeeded
          ? ([
              ["sessions_revoked", "succeeded"],
            ] as const)
          : []),
      ]);
      return;
    }
    if (
      snapshot.path === "/api/auth/sign-out" &&
      snapshot.researcherId !== undefined &&
      succeeded
    ) {
      await this.#recordKnownEvents(snapshot.researcherId, [
        ["sessions_revoked", "succeeded"],
      ]);
      return;
    }
  }

  async #recordEmailIdentity(
    email: string,
    event: "sign_in_failed" | "sign_in_succeeded",
    outcome: "failed" | "succeeded",
  ): Promise<void> {
    await this.#transaction(async (client) => {
      const user = await client.query<{ id: string }>(
        'SELECT id FROM auth."user" WHERE email = $1',
        [email],
      );
      const researcherId = user.rows[0]?.id;
      await recordSecurityAudit(client, {
        authSecret: this.#authSecret,
        event,
        identity:
          researcherId === undefined ? { email } : { researcherId },
        occurredAt: this.#clock(),
        outcome,
      });
    });
  }

  async #recordUnknownResetRequest(email: string): Promise<void> {
    await this.#transaction(async (client) => {
      const user = await client.query<{ id: string }>(
        'SELECT id FROM auth."user" WHERE email = $1',
        [email],
      );
      if (user.rowCount !== 0) {
        return;
      }
      await recordSecurityAudit(client, {
        authSecret: this.#authSecret,
        event: "password_reset_requested",
        identity: { email },
        occurredAt: this.#clock(),
        outcome: "no_change",
      });
    });
  }

  async #recordKnownEvents(
    researcherId: string,
    events: ReadonlyArray<
      readonly [SecurityAuditEvent, "failed" | "succeeded"]
    >,
  ): Promise<void> {
    await this.#transaction(async (client) => {
      const occurredAt = this.#clock();
      for (const [event, outcome] of events) {
        await recordSecurityAudit(client, {
          authSecret: this.#authSecret,
          event,
          identity: { researcherId },
          occurredAt,
          outcome,
        });
      }
    });
  }

  async #transaction(operation: (client: PoolClient) => Promise<void>): Promise<void> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      await operation(client);
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }
}

async function requestSnapshot(
  request: Request,
  getSession: SessionReader,
): Promise<RequestSnapshot> {
  const path = new URL(request.url).pathname;
  if (
    path === "/api/auth/sign-in/email-otp" ||
    path === "/api/auth/request-password-reset"
  ) {
    const body = await jsonBody(request);
    return {
      email: typeof body?.email === "string" ? body.email : undefined,
      path,
    };
  }
  if (path === "/api/auth/change-password" || path === "/api/auth/sign-out") {
    let session: unknown;
    try {
      session = await getSession(request.headers);
    } catch {
      session = null;
    }
    return { path, researcherId: sessionResearcherId(session) };
  }
  return { path };
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

function sessionResearcherId(session: unknown): string | undefined {
  if (
    session === null ||
    typeof session !== "object" ||
    !("user" in session) ||
    session.user === null ||
    typeof session.user !== "object" ||
    !("id" in session.user) ||
    typeof session.user.id !== "string"
  ) {
    return undefined;
  }
  return session.user.id;
}
