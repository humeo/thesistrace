import { randomBytes, randomUUID } from "node:crypto";

import type { Pool, PoolClient } from "pg";

import type { ThesisTraceAuth } from "./auth.js";
import { recordSecurityAudit } from "./audit.js";
import {
  type CredentialOperationCoordinator,
  invitationTokenLockKey,
  KeyedSerialExecutor,
} from "./coordination.js";
import { canonicalizeEmail } from "./identity.js";
import type { InvitationAdmission } from "./invitation-admission.js";
import type { ResendEmail } from "./resend.js";
import {
  createOpaqueToken,
  parseOpaqueToken,
  tokenHashMatches,
} from "./security.js";

const INVITATION_LIFETIME_MS = 48 * 60 * 60 * 1_000;
const PASSWORD_MIN_LENGTH = 12;
const PASSWORD_MAX_LENGTH = 128;

type InvitationStatus =
  | "consumed"
  | "delivered"
  | "delivery_failed"
  | "delivery_pending"
  | "revoked";

type InvitationRow = Readonly<{
  email: string;
  expires_at: Date;
  id: string;
  status: InvitationStatus;
  token_hash: Buffer;
  user_id: string | null;
}>;

type UserRow = Readonly<{
  active: boolean;
  id: string;
}>;

type AccountState = Readonly<{
  accountCount: number;
  credential: boolean;
  sessionCount: number;
}>;

export class InvitationRejectedError extends Error {
  readonly code = "INVITATION_INVALID";

  constructor() {
    super("INVITATION_INVALID");
    this.name = "InvitationRejectedError";
  }
}

export class InvitationServiceUnavailableError extends Error {
  readonly code = "AUTH_SERVICE_UNAVAILABLE";

  constructor() {
    super("AUTH_SERVICE_UNAVAILABLE");
    this.name = "InvitationServiceUnavailableError";
  }
}

export class InvitationDeliveryError extends Error {
  readonly code = "INVITATION_DELIVERY_FAILED";

  constructor() {
    super("INVITATION_DELIVERY_FAILED");
    this.name = "InvitationDeliveryError";
  }
}

export class InvitationConflictError extends Error {
  readonly code = "INVITATION_CONFLICT";

  constructor() {
    super("INVITATION_CONFLICT");
    this.name = "InvitationConflictError";
  }
}

export type InvitationIssueResult = Readonly<{
  email: string;
  invitationId: string;
  status: "delivered";
}>;

export type InvitationAcceptance = Readonly<{
  setCookies: string[];
}>;

export type ResearcherInvitationDependencies = Readonly<{
  auth: ThesisTraceAuth;
  authSecret: string;
  clock?: () => Date;
  credentialCoordinator: CredentialOperationCoordinator;
  createId?: () => string;
  invitationAdmission: InvitationAdmission;
  pool: Pool;
  publicOrigin: string;
  randomBytes?: (size: number) => Buffer;
  sendEmail: (email: ResendEmail) => Promise<void>;
}>;

export class ResearcherInvitationService {
  readonly #auth: ThesisTraceAuth;
  readonly #authSecret: string;
  readonly #clock: () => Date;
  readonly #credentialCoordinator: CredentialOperationCoordinator;
  readonly #createId: () => string;
  readonly #deliverySerial = new KeyedSerialExecutor();
  readonly #invitationAdmission: InvitationAdmission;
  readonly #pool: Pool;
  readonly #publicOrigin: string;
  readonly #randomBytes: (size: number) => Buffer;
  readonly #sendEmail: (email: ResendEmail) => Promise<void>;

  constructor(dependencies: ResearcherInvitationDependencies) {
    this.#auth = dependencies.auth;
    this.#authSecret = dependencies.authSecret;
    this.#clock = dependencies.clock ?? (() => new Date());
    this.#credentialCoordinator = dependencies.credentialCoordinator;
    this.#createId = dependencies.createId ?? randomUUID;
    this.#invitationAdmission = dependencies.invitationAdmission;
    this.#pool = dependencies.pool;
    this.#publicOrigin = dependencies.publicOrigin;
    this.#randomBytes = dependencies.randomBytes ?? randomBytes;
    this.#sendEmail = dependencies.sendEmail;
  }

  issue(emailInput: string): Promise<InvitationIssueResult> {
    return this.#issue(emailInput, false);
  }

  reissue(emailInput: string): Promise<InvitationIssueResult> {
    return this.#issue(emailInput, true);
  }

  async inspect(token: string): Promise<Readonly<{ email: string }>> {
    const parsedToken = parseOpaqueToken(token);
    if (parsedToken === null) {
      throw new InvitationRejectedError();
    }
    const result = await this.#pool.query<InvitationRow>(
      `
        SELECT email, expires_at, id, status, token_hash, user_id
        FROM auth.researcher_invitation
        WHERE id = $1
      `,
      [parsedToken.id],
    );
    const invitation = result.rows[0];
    if (!this.#isUsable(invitation, parsedToken.hash, this.#clock())) {
      throw new InvitationRejectedError();
    }
    return { email: invitation.email };
  }

  async accept(
    token: string,
    password: string,
    requestHeaders: Headers,
  ): Promise<InvitationAcceptance> {
    if (
      password.length < PASSWORD_MIN_LENGTH ||
      password.length > PASSWORD_MAX_LENGTH
    ) {
      throw new InvitationRejectedError();
    }
    const parsedToken = parseOpaqueToken(token);
    if (parsedToken === null) {
      throw new InvitationRejectedError();
    }

    try {
      const hint = await this.#pool.query<{ email: string }>(
        "SELECT email FROM auth.researcher_invitation WHERE id = $1",
        [parsedToken.id],
      );
      const email = hint.rows[0]?.email;
      if (email === undefined) {
        throw new InvitationRejectedError();
      }
      return await this.#credentialCoordinator.runForEmail(
        email,
        async (client) => {
          const prepared = await inTransaction(client, async () => {
            const result = await client.query<InvitationRow>(
              `
                SELECT email, expires_at, id, status, token_hash, user_id
                FROM auth.researcher_invitation
                WHERE id = $1
                FOR UPDATE
              `,
              [parsedToken.id],
            );
            const invitation = result.rows[0];
            const now = this.#clock();
            if (!this.#isUsable(invitation, parsedToken.hash, now)) {
              if (invitation !== undefined) {
                await this.#auditInvitationAttempt(
                  client,
                  invitation,
                  now,
                  "rejected",
                );
              }
              return { invitation: undefined, rejected: true as const };
            }

            let user = await findUserByEmail(client, invitation.email);
            if (user !== undefined && !user.active) {
              await this.#auditInvitationAttempt(
                client,
                invitation,
                now,
                "rejected",
                user,
              );
              return { invitation: undefined, rejected: true as const };
            }
            if (user !== undefined) {
              const state = await accountState(client, user.id);
              if (!state.credential) {
                if (state.accountCount !== 0 || state.sessionCount !== 0) {
                  throw new InvitationServiceUnavailableError();
                }
                const deleted = await client.query(
                  `
                    DELETE FROM auth."user"
                    WHERE id = $1
                      AND NOT EXISTS (
                        SELECT 1 FROM auth."account" WHERE "userId" = $1
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM auth."session" WHERE "userId" = $1
                      )
                  `,
                  [user.id],
                );
                if (deleted.rowCount !== 1) {
                  throw new InvitationServiceUnavailableError();
                }
                user = undefined;
              }
            }
            return { invitation, rejected: false as const, user };
          });

          if (prepared.rejected || prepared.invitation === undefined) {
            throw new InvitationRejectedError();
          }
          const response =
            prepared.user === undefined
              ? await this.#provisionAndReconcile(
                  client,
                  prepared.invitation,
                  password,
                  requestHeaders,
                )
              : await this.#signInExisting(
                  client,
                  prepared.invitation,
                  prepared.user,
                  password,
                  requestHeaders,
                );
          const setCookies = responseSetCookies(response);
          if (setCookies.length === 0) {
            await this.#recordFailedAttempt(client, prepared.invitation);
            throw new InvitationServiceUnavailableError();
          }
          await this.#finalizeAcceptance(
            client,
            prepared.invitation,
            parsedToken.hash,
          );
          return { setCookies };
        },
        {
          additionalLockKeys: [invitationTokenLockKey(parsedToken.hash)],
          compensateSessionUncertainty: true,
        },
      );
    } catch (error) {
      if (
        error instanceof InvitationRejectedError ||
        error instanceof InvitationServiceUnavailableError
      ) {
        throw error;
      }
      throw new InvitationServiceUnavailableError();
    }
  }

  async #signInExisting(
    client: PoolClient,
    invitation: InvitationRow,
    user: UserRow,
    password: string,
    requestHeaders: Headers,
  ): Promise<Response> {
    let response: Response;
    try {
      response = await this.#signIn(invitation.email, password, requestHeaders);
    } catch {
      await this.#recordFailedAttempt(client, invitation, user);
      throw new InvitationServiceUnavailableError();
    }
    if (response.ok) {
      return response;
    }
    if (response.status >= 500) {
      await this.#recordFailedAttempt(client, invitation, user);
      throw new InvitationServiceUnavailableError();
    }
    await inTransaction(client, () =>
      this.#auditInvitationAttempt(
        client,
        invitation,
        this.#clock(),
        "rejected",
        user,
      ),
    );
    throw new InvitationRejectedError();
  }

  async #provisionAndReconcile(
    client: PoolClient,
    invitation: InvitationRow,
    password: string,
    requestHeaders: Headers,
  ): Promise<Response> {
    let signUpResponse: Response | undefined;
    try {
      signUpResponse = await this.#invitationAdmission.run(
        invitation.email,
        () =>
          this.#auth.api.signUpEmail({
            asResponse: true,
            body: {
              email: invitation.email,
              name: invitation.email.slice(0, invitation.email.lastIndexOf("@")),
              password,
            },
            headers: authRequestHeaders(this.#publicOrigin, requestHeaders),
          }),
      );
    } catch {
      signUpResponse = undefined;
    }
    if (signUpResponse?.ok) {
      return signUpResponse;
    }

    const recovered = await this.#recoverProvisioning(client, invitation.email);
    if (recovered === undefined || !recovered.active) {
      await this.#recordFailedAttempt(client, invitation, recovered);
      throw new InvitationServiceUnavailableError();
    }
    try {
      const signInResponse = await this.#signIn(
        invitation.email,
        password,
        requestHeaders,
      );
      if (signInResponse.ok) {
        return signInResponse;
      }
    } catch {
      // The fixed failure record below is the only observable error detail.
    }
    await this.#recordFailedAttempt(client, invitation, recovered);
    throw new InvitationServiceUnavailableError();
  }

  async #recoverProvisioning(
    client: PoolClient,
    email: string,
  ): Promise<UserRow | undefined> {
    return inTransaction(client, async () => {
      const user = await findUserByEmail(client, email, true);
      if (user === undefined) {
        return undefined;
      }
      const state = await accountState(client, user.id);
      if (state.credential) {
        return user;
      }
      if (state.accountCount !== 0 || state.sessionCount !== 0) {
        throw new InvitationServiceUnavailableError();
      }
      const deleted = await client.query(
        `
          DELETE FROM auth."user"
          WHERE id = $1
            AND NOT EXISTS (
              SELECT 1 FROM auth."account" WHERE "userId" = $1
            )
            AND NOT EXISTS (
              SELECT 1 FROM auth."session" WHERE "userId" = $1
            )
        `,
        [user.id],
      );
      if (deleted.rowCount !== 1) {
        throw new InvitationServiceUnavailableError();
      }
      return undefined;
    });
  }

  async #finalizeAcceptance(
    client: PoolClient,
    expected: InvitationRow,
    candidateHash: Buffer,
  ): Promise<void> {
    await inTransaction(client, async () => {
      const now = this.#clock();
      const result = await client.query<InvitationRow>(
        `
          SELECT email, expires_at, id, status, token_hash, user_id
          FROM auth.researcher_invitation
          WHERE id = $1
          FOR UPDATE
        `,
        [expected.id],
      );
      const invitation = result.rows[0];
      if (!this.#isUsable(invitation, candidateHash, now)) {
        throw new InvitationServiceUnavailableError();
      }
      const user = await findUserByEmail(client, invitation.email, true);
      if (user === undefined || !user.active) {
        throw new InvitationRejectedError();
      }
      const state = await accountState(client, user.id);
      if (!state.credential) {
        throw new InvitationServiceUnavailableError();
      }
      if (invitation.status === "delivered") {
        const consumed = await client.query(
          `
            UPDATE auth.researcher_invitation
            SET status = 'consumed', terminal_at = $2, user_id = $3
            WHERE id = $1 AND status = 'delivered'
          `,
          [invitation.id, now, user.id],
        );
        if (consumed.rowCount !== 1) {
          throw new InvitationServiceUnavailableError();
        }
      } else if (invitation.user_id !== user.id) {
        throw new InvitationServiceUnavailableError();
      }
      await recordSecurityAudit(client, {
        authSecret: this.#authSecret,
        event: "invitation_accepted",
        identity: { researcherId: user.id },
        occurredAt: now,
        outcome: "succeeded",
      });
    });
  }

  async #recordFailedAttempt(
    client: PoolClient,
    invitation: InvitationRow,
    user?: UserRow,
  ): Promise<void> {
    await inTransaction(client, async () => {
      await recordSecurityAudit(client, {
        authSecret: this.#authSecret,
        event: "invitation_accepted",
        identity:
          user === undefined
            ? { email: invitation.email }
            : { researcherId: user.id },
        occurredAt: this.#clock(),
        outcome: "failed",
      });
    });
  }

  #signIn(
    email: string,
    password: string,
    requestHeaders: Headers,
  ): Promise<Response> {
    return this.#auth.api.signInEmail({
      asResponse: true,
      body: { email, password },
      headers: authRequestHeaders(this.#publicOrigin, requestHeaders),
    });
  }

  async #issue(
    emailInput: string,
    replaceExisting: boolean,
  ): Promise<InvitationIssueResult> {
    const email = canonicalizeEmail(emailInput);
    return await this.#deliverySerial.run(email, async () => {
      const invitationId = this.#createId();
      const token = createOpaqueToken(invitationId, this.#randomBytes);
      const parsedToken = parseOpaqueToken(token);
      if (parsedToken === null) {
        throw new Error("INVITATION_TOKEN_GENERATION_FAILED");
      }
      await this.#credentialCoordinator.runForEmail(email, (client) =>
        inTransaction(client, async () => {
          const now = this.#clock();
          if ((await findUserByEmail(client, email, true)) !== undefined) {
            throw new InvitationConflictError();
          }
          const effective = await client.query<{ id: string }>(
            `
              SELECT id
              FROM auth.researcher_invitation
              WHERE email = $1 AND status IN ('delivery_pending', 'delivered')
              FOR UPDATE
            `,
            [email],
          );
          if (effective.rowCount !== 0 && !replaceExisting) {
            throw new InvitationConflictError();
          }
          if (effective.rowCount !== 0) {
            await client.query(
              `
                UPDATE auth.researcher_invitation
                SET status = 'revoked', terminal_at = $2
                WHERE email = $1 AND status IN ('delivery_pending', 'delivered')
              `,
              [email, now],
            );
            await recordSecurityAudit(client, {
              authSecret: this.#authSecret,
              event: "invitation_revoked",
              identity: { email },
              occurredAt: now,
              outcome: "succeeded",
            });
          }
          await client.query(
            `
              INSERT INTO auth.researcher_invitation (
                id,
                email,
                token_hash,
                status,
                expires_at,
                created_at
              )
              VALUES ($1, $2, $3, 'delivery_pending', $4, $5)
            `,
            [
              invitationId,
              email,
              parsedToken.hash,
              new Date(now.getTime() + INVITATION_LIFETIME_MS),
              now,
            ],
          );
        }),
      );

      let delivered = true;
      try {
        await this.#sendEmail(
          invitationEmail(this.#publicOrigin, email, token),
        );
      } catch {
        delivered = false;
      }

      const finalized = await this.#credentialCoordinator.runForEmail(
        email,
        (client) =>
          inTransaction(client, async () => {
            const now = this.#clock();
            const pending = await client.query<{ id: string }>(
              `
                SELECT id
                FROM auth.researcher_invitation
                WHERE id = $1
                  AND email = $2
                  AND token_hash = $3
                  AND status = 'delivery_pending'
                FOR UPDATE
              `,
              [invitationId, email, parsedToken.hash],
            );
            if (pending.rowCount !== 1) {
              return false;
            }
            await client.query(
              delivered
                ? `
                    UPDATE auth.researcher_invitation
                    SET status = 'delivered', delivered_at = $2
                    WHERE id = $1 AND status = 'delivery_pending'
                  `
                : `
                    UPDATE auth.researcher_invitation
                    SET status = 'delivery_failed', terminal_at = $2
                    WHERE id = $1 AND status = 'delivery_pending'
                  `,
              [invitationId, now],
            );
            await recordSecurityAudit(client, {
              authSecret: this.#authSecret,
              event: "invitation_issued",
              identity: { email },
              occurredAt: now,
              outcome: delivered ? "succeeded" : "failed",
            });
            return delivered;
          }),
      );
      if (!finalized) {
        throw new InvitationDeliveryError();
      }
      return { email, invitationId, status: "delivered" };
    });
  }

  async #auditInvitationAttempt(
    client: PoolClient,
    invitation: InvitationRow,
    occurredAt: Date,
    outcome: "rejected",
    user?: UserRow,
  ): Promise<void> {
    await recordSecurityAudit(client, {
      authSecret: this.#authSecret,
      event: "invitation_accepted",
      identity:
        user === undefined
          ? { email: invitation.email }
          : { researcherId: user.id },
      occurredAt,
      outcome,
    });
  }

  #isUsable(
    invitation: InvitationRow | undefined,
    candidateHash: Buffer,
    now: Date,
  ): invitation is InvitationRow {
    return (
      invitation !== undefined &&
      tokenHashMatches(invitation.token_hash, candidateHash) &&
      (invitation.status === "delivered" || invitation.status === "consumed") &&
      invitation.expires_at.getTime() > now.getTime()
    );
  }
}

async function inTransaction<T>(
  client: PoolClient,
  operation: () => Promise<T>,
): Promise<T> {
  try {
    await client.query("BEGIN");
    const result = await operation();
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  }
}

async function findUserByEmail(
  client: PoolClient,
  email: string,
  forUpdate = false,
): Promise<UserRow | undefined> {
  const result = await client.query<UserRow>(
    `
      SELECT active, id
      FROM auth."user"
      WHERE email = $1
      ${forUpdate ? "FOR UPDATE" : ""}
    `,
    [email],
  );
  return result.rows[0];
}

async function accountState(
  client: PoolClient,
  userId: string,
): Promise<AccountState> {
  const result = await client.query<{
    account_count: string;
    credential: boolean;
    session_count: string;
  }>(
    `
      SELECT
        (SELECT count(*) FROM auth."account" WHERE "userId" = $1)
          AS account_count,
        EXISTS (
          SELECT 1
          FROM auth."account"
          WHERE "userId" = $1
            AND "providerId" = 'credential'
            AND password IS NOT NULL
        ) AS credential,
        (SELECT count(*) FROM auth."session" WHERE "userId" = $1)
          AS session_count
    `,
    [userId],
  );
  const state = result.rows[0];
  if (state === undefined) {
    throw new InvitationServiceUnavailableError();
  }
  return {
    accountCount: Number(state.account_count),
    credential: state.credential,
    sessionCount: Number(state.session_count),
  };
}

function authRequestHeaders(publicOrigin: string, input: Headers): Headers {
  const headers = new Headers({ origin: publicOrigin });
  for (const name of ["user-agent", "x-thesistrace-client-ip"]) {
    const value = input.get(name);
    if (value !== null) {
      headers.set(name, value);
    }
  }
  return headers;
}

function invitationEmail(
  publicOrigin: string,
  email: string,
  token: string,
): ResendEmail {
  const link = `${publicOrigin}/accept-invitation#token=${encodeURIComponent(token)}`;
  return {
    html: `<p>You have been invited to ThesisTrace.</p><p><a href="${link}">Accept invitation</a></p>`,
    subject: "Your ThesisTrace invitation",
    text: `You have been invited to ThesisTrace. Accept the invitation: ${link}`,
    to: email,
  };
}

function responseSetCookies(response: Response): string[] {
  const cookies = response.headers.getSetCookie();
  if (cookies.length !== 0) {
    return cookies;
  }
  const cookie = response.headers.get("set-cookie");
  return cookie === null ? [] : [cookie];
}
