import { revokeResearcherMcpAccess } from "./mcp-revocation.js";
import type { Pool, PoolClient } from "pg";
import { z } from "zod";

import { recordSecurityAudit, type SecurityAuditEvent } from "./audit.js";
import { lockAuthMutationShared } from "./auth-mutation-lock.js";
import type { CredentialOperationCoordinator } from "./coordination.js";
import { canonicalizeEmail } from "./identity.js";
import { lockOperatorAssignment } from "./operator-lock.js";

const researcherIdSchema = z.uuid();
const displayLabelSchema = z
  .string()
  .trim()
  .min(1)
  .max(100)
  .refine((value) => !/[\u0000-\u001f\u007f]/.test(value));

type ResearcherRow = Readonly<{
  active: boolean;
  email: string;
  id: string;
  name: string;
}>;

export type AccessMutationResult = Readonly<{
  researcherId: string;
  status: "no_change" | "updated";
}>;

export type ResearcherSessionRevocationResult = AccessMutationResult &
  Readonly<{ revokedSessionCount: number }>;

export type ResearcherAccessAuthorization = Readonly<{
  consume: (client: PoolClient) => Promise<boolean>;
}>;

export class ResearcherNotFoundError extends Error {
  readonly code = "RESEARCHER_NOT_FOUND";

  constructor() {
    super("RESEARCHER_NOT_FOUND");
    this.name = "ResearcherNotFoundError";
  }
}

class DisplayLabelInvalidError extends Error {
  readonly code = "DISPLAY_LABEL_INVALID";

  constructor() {
    super("DISPLAY_LABEL_INVALID");
    this.name = "DisplayLabelInvalidError";
  }
}

export class OperatorDeactivationRejectedError extends Error {
  readonly code = "OPERATOR_DEACTIVATION_REJECTED";

  constructor() {
    super("OPERATOR_DEACTIVATION_REJECTED");
    this.name = "OperatorDeactivationRejectedError";
  }
}

export class ResearcherAccessAuthorizationError extends Error {
  readonly code = "RESEARCHER_ACCESS_AUTHORIZATION_INVALID";

  constructor() {
    super("RESEARCHER_ACCESS_AUTHORIZATION_INVALID");
    this.name = "ResearcherAccessAuthorizationError";
  }
}

export class ResearcherSessionTargetProtectedError extends Error {
  readonly code = "RESEARCHER_SESSION_TARGET_PROTECTED";

  constructor() {
    super("RESEARCHER_SESSION_TARGET_PROTECTED");
    this.name = "ResearcherSessionTargetProtectedError";
  }
}

export type ResearcherAccessDependencies = Readonly<{
  authSecret: string;
  clock?: () => Date;
  credentialCoordinator: CredentialOperationCoordinator;
  pool: Pool;
}>;

export class ResearcherAccessService {
  readonly #authSecret: string;
  readonly #clock: () => Date;
  readonly #credentialCoordinator: CredentialOperationCoordinator;
  readonly #pool: Pool;

  constructor(dependencies: ResearcherAccessDependencies) {
    this.#authSecret = dependencies.authSecret;
    this.#clock = dependencies.clock ?? (() => new Date());
    this.#credentialCoordinator = dependencies.credentialCoordinator;
    this.#pool = dependencies.pool;
  }

  async resolveResearcherId(
    identity:
      | Readonly<{ email: string; researcherId?: never }>
      | Readonly<{ email?: never; researcherId: string }>,
  ): Promise<string> {
    const result =
      identity.researcherId === undefined
        ? await this.#pool.query<{ id: string }>(
            'SELECT id FROM auth."user" WHERE email = $1',
            [canonicalizeEmail(identity.email)],
          )
        : await this.#pool.query<{ id: string }>(
            'SELECT id FROM auth."user" WHERE id = $1',
            [parseResearcherId(identity.researcherId)],
          );
    const id = result.rows[0]?.id;
    if (id === undefined) {
      throw new ResearcherNotFoundError();
    }
    return id;
  }

  deactivate(researcherIdInput: string): Promise<AccessMutationResult> {
    const researcherId = parseResearcherId(researcherIdInput);
    return this.#mutate(researcherId, "researcher_deactivated", async (client, user, now) => {
      const assignment = await client.query(
        `
          SELECT 1
          FROM auth.operator_assignment
          WHERE singleton IS TRUE AND researcher_id = $1
        `,
        [researcherId],
      );
      if (assignment.rowCount !== 0) {
        throw new OperatorDeactivationRejectedError();
      }
      const active = await client.query(
        'UPDATE auth."user" SET active = FALSE, "updatedAt" = $2 WHERE id = $1 AND active = TRUE',
        [researcherId, now],
      );
      const sessions = await client.query(
        'DELETE FROM auth."session" WHERE "userId" = $1',
        [researcherId],
      );
      await revokeResearcherMcpAccess(client, researcherId);
      const resets = await client.query(
        `
          UPDATE auth.password_reset
          SET status = 'revoked', terminal_at = $2
          WHERE user_id = $1 AND status IN ('delivery_pending', 'delivered')
        `,
        [researcherId, now],
      );
      const verifications = await client.query(
        `
          DELETE FROM auth."verification"
          WHERE value = $1 AND identifier LIKE 'reset-password:%'
        `,
        [researcherId],
      );
      const invitations = await client.query(
        `
          UPDATE auth.researcher_invitation
          SET status = 'revoked', terminal_at = $2
          WHERE email = $1 AND status IN ('delivery_pending', 'delivered')
        `,
        [user.email, now],
      );
      return anyRowsChanged([
        active,
        sessions,
        resets,
        verifications,
        invitations,
      ]);
    });
  }

  reactivate(researcherIdInput: string): Promise<AccessMutationResult> {
    const researcherId = parseResearcherId(researcherIdInput);
    return this.#mutate(researcherId, "researcher_reactivated", async (client, _user, now) => {
      const result = await client.query(
        'UPDATE auth."user" SET active = TRUE, "updatedAt" = $2 WHERE id = $1 AND active = FALSE',
        [researcherId, now],
      );
      return (result.rowCount ?? 0) !== 0;
    });
  }

  async revokeSessions(
    researcherIdInput: string,
  ): Promise<AccessMutationResult> {
    const researcherId = parseResearcherId(researcherIdInput);
    const email = await this.#resolveResearcherEmail(researcherId);
    const result = await this.#credentialCoordinator.runForEmail(
      email,
      (client) =>
        this.#mutateWithClient(
          client,
          researcherId,
          "sessions_revoked",
          async (transactionClient) => {
            const deleted = await transactionClient.query(
              'DELETE FROM auth."session" WHERE "userId" = $1',
              [researcherId],
            );
            return (deleted.rowCount ?? 0) !== 0;
          },
        ),
    );
    return result;
  }

  async revokeSessionsAuthorized(
    actingResearcherIdInput: string,
    researcherIdInput: string,
    authorization: ResearcherAccessAuthorization,
  ): Promise<ResearcherSessionRevocationResult> {
    const actingResearcherId = parseResearcherId(actingResearcherIdInput);
    const researcherId = parseResearcherId(researcherIdInput);
    const email = await this.#resolveResearcherEmail(researcherId);
    return await this.#credentialCoordinator.runForEmail(email, (client) =>
      this.#transaction(client, async () => {
        await lockAuthMutationShared(client);
        await lockOperatorAssignment(client);
        const assignment = await client.query<{ researcher_id: string }>(
          `
            SELECT researcher_id
            FROM auth.operator_assignment
            WHERE singleton IS TRUE
            FOR UPDATE
          `,
        );
        const currentOperatorId = assignment.rows[0]?.researcher_id;
        if (currentOperatorId !== actingResearcherId) {
          throw new ResearcherAccessAuthorizationError();
        }
        if (currentOperatorId === researcherId) {
          throw new ResearcherSessionTargetProtectedError();
        }
        await client.query(
          "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
          [researcherId],
        );
        const userResult = await client.query<ResearcherRow>(
          'SELECT active, email, id, name FROM auth."user" WHERE id = $1 FOR UPDATE',
          [researcherId],
        );
        if (userResult.rows[0] === undefined) {
          throw new ResearcherNotFoundError();
        }
        if (!(await authorization.consume(client))) {
          throw new ResearcherAccessAuthorizationError();
        }
        const deleted = await client.query(
          'DELETE FROM auth."session" WHERE "userId" = $1',
          [researcherId],
        );
        const revokedSessionCount = deleted.rowCount ?? 0;
        await recordSecurityAudit(client, {
          authSecret: this.#authSecret,
          event: "sessions_revoked",
          identity: { researcherId },
          occurredAt: this.#clock(),
          outcome: revokedSessionCount === 0 ? "no_change" : "succeeded",
        });
        return {
          researcherId,
          revokedSessionCount,
          status: revokedSessionCount === 0 ? "no_change" : "updated",
        };
      }),
    );
  }

  correctDisplayLabel(
    researcherIdInput: string,
    labelInput: string,
  ): Promise<AccessMutationResult> {
    const researcherId = parseResearcherId(researcherIdInput);
    const parsedLabel = displayLabelSchema.safeParse(labelInput);
    if (!parsedLabel.success) {
      throw new DisplayLabelInvalidError();
    }
    const label = parsedLabel.data;
    return this.#mutate(
      researcherId,
      "display_label_corrected",
      async (client, user, now) => {
        if (user.name === label) {
          return false;
        }
        await client.query(
          'UPDATE auth."user" SET name = $2, "updatedAt" = $3 WHERE id = $1',
          [researcherId, label, now],
        );
        return true;
      },
    );
  }

  async #mutate(
    researcherId: string,
    event: SecurityAuditEvent,
    operation: (
      client: PoolClient,
      user: ResearcherRow,
      now: Date,
    ) => Promise<boolean>,
  ): Promise<AccessMutationResult> {
    const client = await this.#pool.connect();
    try {
      return await this.#mutateWithClient(
        client,
        researcherId,
        event,
        operation,
      );
    } finally {
      client.release();
    }
  }

  #mutateWithClient(
    client: PoolClient,
    researcherId: string,
    event: SecurityAuditEvent,
    operation: (
      client: PoolClient,
      user: ResearcherRow,
      now: Date,
    ) => Promise<boolean>,
  ): Promise<AccessMutationResult> {
    return this.#transaction(client, async () => {
      await lockAuthMutationShared(client);
      await client.query(
        "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
        [researcherId],
      );
      const userResult = await client.query<ResearcherRow>(
        'SELECT active, email, id, name FROM auth."user" WHERE id = $1 FOR UPDATE',
        [researcherId],
      );
      const user = userResult.rows[0];
      if (user === undefined) {
        throw new ResearcherNotFoundError();
      }
      const now = this.#clock();
      const changed = await operation(client, user, now);
      await recordSecurityAudit(client, {
        authSecret: this.#authSecret,
        event,
        identity: { researcherId },
        occurredAt: now,
        outcome: changed ? "succeeded" : "no_change",
      });
      return { researcherId, status: changed ? "updated" : "no_change" };
    });
  }

  async #resolveResearcherEmail(researcherId: string): Promise<string> {
    const result = await this.#pool.query<{ email: string }>(
      'SELECT email FROM auth."user" WHERE id = $1',
      [researcherId],
    );
    const email = result.rows[0]?.email;
    if (email === undefined) {
      throw new ResearcherNotFoundError();
    }
    return email;
  }

  async #transaction<T>(
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
}

function parseResearcherId(value: string): string {
  const parsed = researcherIdSchema.safeParse(value);
  if (!parsed.success) {
    throw new ResearcherNotFoundError();
  }
  return parsed.data;
}

function anyRowsChanged(
  results: ReadonlyArray<Readonly<{ rowCount: number | null }>>,
): boolean {
  return results.some((result) => (result.rowCount ?? 0) !== 0);
}
