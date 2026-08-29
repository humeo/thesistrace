import type { Pool, PoolClient } from "pg";
import { z } from "zod";

import { canonicalizeEmail, InvalidEmailError } from "./identity.js";

const researcherIdSchema = z.uuid();
const assignmentLockKey = "thesistrace:operator-assignment";

export type OperatorIdentity =
  | Readonly<{ email: string; researcherId?: never }>
  | Readonly<{ email?: never; researcherId: string }>;

export type OperatorAssignmentResult = Readonly<{
  operatorResearcherId: string;
  status: "assigned";
}>;

export type OperatorTransferResult = Readonly<{
  formerOperatorResearcherId: string;
  operatorResearcherId: string;
  status: "no_change" | "transferred";
}>;

export class OperatorAssignmentConflictError extends Error {
  readonly code = "OPERATOR_ALREADY_ASSIGNED";

  constructor() {
    super("OPERATOR_ALREADY_ASSIGNED");
    this.name = "OperatorAssignmentConflictError";
  }
}

export class OperatorAssignmentMissingError extends Error {
  readonly code = "OPERATOR_ASSIGNMENT_MISSING";

  constructor() {
    super("OPERATOR_ASSIGNMENT_MISSING");
    this.name = "OperatorAssignmentMissingError";
  }
}

export class OperatorTargetInvalidError extends Error {
  readonly code = "OPERATOR_TARGET_INVALID";

  constructor() {
    super("OPERATOR_TARGET_INVALID");
    this.name = "OperatorTargetInvalidError";
  }
}

export type OperatorAssignmentDependencies = Readonly<{
  clock?: () => Date;
  pool: Pool;
}>;

export class OperatorAssignmentService {
  readonly #clock: () => Date;
  readonly #pool: Pool;

  constructor(dependencies: OperatorAssignmentDependencies) {
    this.#clock = dependencies.clock ?? (() => new Date());
    this.#pool = dependencies.pool;
  }

  assign(identity: OperatorIdentity): Promise<OperatorAssignmentResult> {
    return this.#transaction(async (client) => {
      await lockAssignment(client);
      const target = await resolveActiveResearcher(client, identity);
      const current = await currentAssignment(client);
      if (current !== undefined) {
        throw new OperatorAssignmentConflictError();
      }
      await client.query(
        `
          INSERT INTO auth.operator_assignment (
            singleton, researcher_id, assigned_at
          )
          VALUES (TRUE, $1, $2)
        `,
        [target.id, this.#clock()],
      );
      return { operatorResearcherId: target.id, status: "assigned" };
    });
  }

  transfer(identity: OperatorIdentity): Promise<OperatorTransferResult> {
    return this.#transaction(async (client) => {
      await lockAssignment(client);
      const current = await currentAssignment(client);
      if (current === undefined) {
        throw new OperatorAssignmentMissingError();
      }
      const target = await resolveActiveResearcher(client, identity);
      if (current.researcher_id === target.id) {
        return {
          formerOperatorResearcherId: current.researcher_id,
          operatorResearcherId: target.id,
          status: "no_change",
        };
      }
      await client.query(
        `
          UPDATE auth.operator_assignment
          SET researcher_id = $1, assigned_at = $2
          WHERE singleton IS TRUE
        `,
        [target.id, this.#clock()],
      );
      await client.query(
        'DELETE FROM auth."session" WHERE "userId" = $1',
        [current.researcher_id],
      );
      return {
        formerOperatorResearcherId: current.researcher_id,
        operatorResearcherId: target.id,
        status: "transferred",
      };
    });
  }

  async #transaction<T>(operation: (client: PoolClient) => Promise<T>): Promise<T> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
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

async function lockAssignment(client: PoolClient): Promise<void> {
  await client.query(
    "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
    [assignmentLockKey],
  );
}

async function currentAssignment(
  client: PoolClient,
): Promise<Readonly<{ researcher_id: string }> | undefined> {
  const result = await client.query<{ researcher_id: string }>(
    `
      SELECT researcher_id
      FROM auth.operator_assignment
      WHERE singleton IS TRUE
      FOR UPDATE
    `,
  );
  return result.rows[0];
}

async function resolveActiveResearcher(
  client: PoolClient,
  identity: OperatorIdentity,
): Promise<Readonly<{ id: string }>> {
  let value: string;
  let field: "email" | "id";
  if (identity.researcherId !== undefined) {
    const parsed = researcherIdSchema.safeParse(identity.researcherId);
    if (!parsed.success) throw new OperatorTargetInvalidError();
    value = parsed.data;
    field = "id";
  } else {
    try {
      value = canonicalizeEmail(identity.email);
    } catch (error) {
      if (error instanceof InvalidEmailError) {
        throw new OperatorTargetInvalidError();
      }
      throw error;
    }
    field = "email";
  }
  const result = await client.query<{ id: string }>(
    `
      SELECT id
      FROM auth."user"
      WHERE ${field === "id" ? "id" : "email"} = $1
        AND active IS TRUE
      FOR UPDATE
    `,
    [value],
  );
  const target = result.rows[0];
  if (target === undefined) throw new OperatorTargetInvalidError();
  return target;
}
