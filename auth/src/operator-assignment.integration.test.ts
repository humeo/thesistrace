import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { createAuthPool } from "./database.js";
import {
  OperatorAssignmentConflictError,
  OperatorAssignmentMissingError,
  OperatorAssignmentService,
  OperatorTargetInvalidError,
} from "./operator-assignment.js";
import { initializeAuthSchema } from "./schema-initialize.js";

const ownerDatabaseUrl = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (ownerDatabaseUrl === undefined) {
  throw new Error("THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL is required");
}

const runtimeDatabaseUrl = roleDatabaseUrl(
  ownerDatabaseUrl,
  "auth_runtime",
  "auth-test-password",
);
const owner = new Pool({ connectionString: ownerDatabaseUrl, max: 3 });
const runtimePool = createAuthPool(runtimeDatabaseUrl);
const firstResearcherId = "00000000-0000-4000-8000-000000000001";
const secondResearcherId = "00000000-0000-4000-8000-000000000002";
const inactiveResearcherId = "00000000-0000-4000-8000-000000000003";
const fixedNow = new Date("2026-08-29T06:00:00.000Z");

describe.sequential("Auth Operator Assignment", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    await owner.query(`
      TRUNCATE
        auth.operator_assignment,
        auth.security_audit,
        auth.password_reset,
        auth.researcher_invitation,
        auth."rateLimit",
        auth."verification",
        auth."user"
      CASCADE
    `);
    await insertResearcher(
      firstResearcherId,
      "first-operator@example.com",
      true,
    );
    await insertResearcher(
      secondResearcherId,
      "second-operator@example.com",
      true,
    );
    await insertResearcher(
      inactiveResearcherId,
      "inactive-operator@example.com",
      false,
    );
  });

  afterAll(async () => {
    await runtimePool.end();
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("assigns only one existing active Researcher and preserves it on conflict", async () => {
    const assignment = service();

    await expect(
      assignment.assign({ email: " First-Operator@Example.COM " }),
    ).resolves.toEqual({
      operatorResearcherId: firstResearcherId,
      status: "assigned",
    });
    await expect(
      assignment.assign({ researcherId: secondResearcherId }),
    ).rejects.toBeInstanceOf(OperatorAssignmentConflictError);
    expect(await persistedAssignment()).toEqual({
      assigned_at: fixedNow,
      researcher_id: firstResearcherId,
    });
  });

  it("serializes concurrent first assignment without exposing two Operators", async () => {
    const assignment = service();
    const outcomes = await Promise.allSettled([
      assignment.assign({ researcherId: firstResearcherId }),
      assignment.assign({ researcherId: secondResearcherId }),
    ]);

    expect(outcomes.filter((outcome) => outcome.status === "fulfilled")).toHaveLength(1);
    const rejection = outcomes.find((outcome) => outcome.status === "rejected");
    expect(rejection).toMatchObject({
      status: "rejected",
      reason: expect.any(OperatorAssignmentConflictError),
    });
    const rows = await owner.query<{ researcher_id: string }>(
      "SELECT researcher_id FROM auth.operator_assignment",
    );
    expect(rows.rows).toHaveLength(1);
    expect([firstResearcherId, secondResearcherId]).toContain(
      rows.rows[0]?.researcher_id,
    );
  });

  it("rejects inactive, missing, and pre-establishment transfer targets", async () => {
    const assignment = service();

    await expect(
      assignment.assign({ researcherId: inactiveResearcherId }),
    ).rejects.toBeInstanceOf(OperatorTargetInvalidError);
    await expect(
      assignment.assign({ researcherId: "00000000-0000-4000-8000-000000000099" }),
    ).rejects.toBeInstanceOf(OperatorTargetInvalidError);
    await expect(
      assignment.transfer({ researcherId: firstResearcherId }),
    ).rejects.toBeInstanceOf(OperatorAssignmentMissingError);
    expect(await persistedAssignment()).toBeNull();
  });

  it("transfers atomically and revokes only the former Operator Login Sessions", async () => {
    const assignment = service();
    await assignment.assign({ researcherId: firstResearcherId });
    await insertSession(
      "00000000-0000-4000-8000-000000000011",
      "first-session-one",
      firstResearcherId,
    );
    await insertSession(
      "00000000-0000-4000-8000-000000000012",
      "first-session-two",
      firstResearcherId,
    );
    await insertSession(
      "00000000-0000-4000-8000-000000000013",
      "second-session",
      secondResearcherId,
    );
    const blocker = await owner.connect();
    try {
      await blocker.query("BEGIN");
      await blocker.query(
        'SELECT id FROM auth."session" WHERE "userId" = $1 FOR UPDATE',
        [firstResearcherId],
      );
      const transferring = assignment.transfer({ researcherId: secondResearcherId });
      await waitForBlockedSessionDelete();

      expect(await persistedAssignment()).toEqual({
        assigned_at: fixedNow,
        researcher_id: firstResearcherId,
      });
      expect(await sessionCounts()).toEqual({ first: 2, second: 1 });

      await blocker.query("COMMIT");
      await expect(transferring).resolves.toEqual({
        formerOperatorResearcherId: firstResearcherId,
        operatorResearcherId: secondResearcherId,
        status: "transferred",
      });
    } finally {
      await blocker.query("ROLLBACK").catch(() => undefined);
      blocker.release();
    }

    expect(await persistedAssignment()).toEqual({
      assigned_at: fixedNow,
      researcher_id: secondResearcherId,
    });
    expect(await sessionCounts()).toEqual({ first: 0, second: 1 });
  });

  it("treats transfer to the current Operator as a no-change without revocation", async () => {
    const assignment = service();
    await assignment.assign({ researcherId: firstResearcherId });
    await insertSession(
      "00000000-0000-4000-8000-000000000021",
      "current-operator-session",
      firstResearcherId,
    );

    await expect(
      assignment.transfer({ researcherId: firstResearcherId }),
    ).resolves.toEqual({
      formerOperatorResearcherId: firstResearcherId,
      operatorResearcherId: firstResearcherId,
      status: "no_change",
    });
    expect(await sessionCounts()).toEqual({ first: 1, second: 0 });
  });
});

function service(): OperatorAssignmentService {
  return new OperatorAssignmentService({
    clock: () => fixedNow,
    pool: runtimePool,
  });
}

async function insertResearcher(
  id: string,
  email: string,
  active: boolean,
): Promise<void> {
  await owner.query(
    `
      INSERT INTO auth."user" (
        id, name, email, "emailVerified", "createdAt", "updatedAt", active
      )
      VALUES ($1, $2, $3, TRUE, $4, $4, $5)
    `,
    [id, email.slice(0, email.indexOf("@")), email, fixedNow, active],
  );
}

async function insertSession(id: string, token: string, researcherId: string): Promise<void> {
  await owner.query(
    `
      INSERT INTO auth."session" (
        id, "expiresAt", token, "createdAt", "updatedAt", "userId"
      )
      VALUES ($1, $2, $3, $4, $4, $5)
    `,
    [id, new Date("2026-08-30T06:00:00.000Z"), token, fixedNow, researcherId],
  );
}

async function persistedAssignment(): Promise<Readonly<{
  assigned_at: Date;
  researcher_id: string;
}> | null> {
  const result = await owner.query<{
    assigned_at: Date;
    researcher_id: string;
  }>("SELECT assigned_at, researcher_id FROM auth.operator_assignment");
  return result.rows[0] ?? null;
}

async function sessionCounts(): Promise<Readonly<{ first: number; second: number }>> {
  const result = await owner.query<{ first: string; second: string }>(
    `
      SELECT
        count(*) FILTER (WHERE "userId" = $1) AS first,
        count(*) FILTER (WHERE "userId" = $2) AS second
      FROM auth."session"
    `,
    [firstResearcherId, secondResearcherId],
  );
  const row = result.rows[0];
  if (row === undefined) throw new Error("expected Login Session counts");
  return { first: Number(row.first), second: Number(row.second) };
}

async function waitForBlockedSessionDelete(): Promise<void> {
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    const result = await owner.query<{ blocked: boolean }>(`
      SELECT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_stat_activity AS activity
        WHERE activity.usename = 'auth_runtime'
          AND activity.query LIKE 'DELETE FROM auth."session"%'
          AND pg_catalog.cardinality(
            pg_catalog.pg_blocking_pids(activity.pid)
          ) > 0
      ) AS blocked
    `);
    if (result.rows[0]?.blocked === true) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("Operator transfer did not reach the blocked Session revocation");
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
