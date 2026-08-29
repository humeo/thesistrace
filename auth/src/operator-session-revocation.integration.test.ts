import { hashPassword } from "better-auth/crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { ResearcherAccessService } from "./access.js";
import {
  AuthOperationCoordinator,
  CredentialOperationCoordinator,
  credentialLockKey,
} from "./coordination.js";
import { createAuthCoordinationPool, createAuthPool } from "./database.js";
import { OperatorAssignmentService } from "./operator-assignment.js";
import { OperatorProofInvalidError, OperatorProofService } from "./operator-proof.js";
import {
  OperatorSessionRevocationService,
  OperatorSessionTargetProtectedError,
} from "./operator-session-revocation.js";
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
const owner = new Pool({ connectionString: ownerDatabaseUrl, max: 2 });
const runtimePool = createAuthPool(runtimeDatabaseUrl);
const coordinationPool = createAuthCoordinationPool(runtimeDatabaseUrl);
const authSecret = "0123456789abcdef0123456789abcdef";
const password = "correct-horse-battery-staple";
const fixedNow = new Date("2026-08-29T06:00:00.000Z");
const operatorId = "00000000-0000-4000-8000-000000000001";
const targetId = "00000000-0000-4000-8000-000000000002";
const otherId = "00000000-0000-4000-8000-000000000003";
const operatorSessionId = "00000000-0000-4000-8000-000000000011";
const targetSessionId = "00000000-0000-4000-8000-000000000012";
const targetSecondSessionId = "00000000-0000-4000-8000-000000000013";
const otherSessionId = "00000000-0000-4000-8000-000000000014";
const targetEmail = "target@example.com";
const coordination = new AuthOperationCoordinator(coordinationPool);
const credentialCoordinator = new CredentialOperationCoordinator({
  authSecret,
  coordination,
  pool: runtimePool,
});
let nextProofId = 100;

describe.sequential("Operator Researcher Session revocation", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    nextProofId = 100;
    await owner.query(`
      TRUNCATE
        auth.operator_proof,
        auth.operator_assignment,
        auth.security_audit,
        auth.password_reset,
        auth.researcher_invitation,
        auth."rateLimit",
        auth."verification",
        auth."user"
      CASCADE
    `);
    await insertResearcher(operatorId, "operator@example.com", "Operator");
    await insertResearcher(targetId, targetEmail, "Target");
    await insertResearcher(otherId, "other@example.com", "Other");
    await insertCredential(operatorId);
    await insertSession(operatorSessionId, operatorId, "operator-session");
    await insertSession(targetSessionId, targetId, "target-session");
    await insertSession(
      targetSecondSessionId,
      targetId,
      "target-second-session",
    );
    await insertSession(otherSessionId, otherId, "other-session");
    await new OperatorAssignmentService({ clock: () => fixedNow, pool: runtimePool })
      .assign({ researcherId: operatorId });
  });

  afterAll(async () => {
    await coordinationPool.end();
    await runtimePool.end();
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("consumes one exact proof and revokes every target Session only", async () => {
    const harness = service();
    const proof = await confirmProof(harness.proofs, targetId);

    await expect(
      harness.revocations.revoke(principal(), { proof, researcherId: targetId }),
    ).resolves.toEqual({
      researcherId: targetId,
      revokedSessionCount: 2,
      status: "updated",
    });

    expect(await sessionCounts()).toEqual({ operator: 1, other: 1, target: 0 });
    expect(
      await owner.query<{ active: boolean }>(
        'SELECT active FROM auth."user" WHERE id = $1',
        [targetId],
      ),
    ).toMatchObject({ rows: [{ active: true }] });
    expect(
      await owner.query<{ event: string; outcome: string; researcher_id: string }>(
        `
          SELECT event, outcome, researcher_id
          FROM auth.security_audit
          WHERE event = 'sessions_revoked'
        `,
      ),
    ).toMatchObject({
      rows: [{
        event: "sessions_revoked",
        outcome: "succeeded",
        researcher_id: targetId,
      }],
    });
    expect(await proofStates()).toEqual(["consumed"]);
  });

  it("rejects self-targeting and releases the still-valid proof", async () => {
    const harness = service();
    const proof = await confirmProof(harness.proofs, operatorId);

    await expect(
      harness.revocations.revoke(principal(), {
        proof,
        researcherId: operatorId,
      }),
    ).rejects.toBeInstanceOf(OperatorSessionTargetProtectedError);

    expect(await sessionCounts()).toEqual({ operator: 1, other: 1, target: 2 });
    expect(await proofStates()).toEqual(["available"]);
  });

  it("rejects target mismatch and admits only one concurrent proof consumption", async () => {
    const mismatchHarness = service();
    const mismatchedProof = await confirmProof(mismatchHarness.proofs, targetId);
    await expect(
      mismatchHarness.revocations.revoke(principal(), {
        proof: mismatchedProof,
        researcherId: otherId,
      }),
    ).rejects.toEqual(new OperatorProofInvalidError());
    expect(await sessionCounts()).toEqual({ operator: 1, other: 1, target: 2 });

    const harness = service();
    const proof = await confirmProof(harness.proofs, targetId);
    const results = await Promise.allSettled([
      harness.revocations.revoke(principal(), { proof, researcherId: targetId }),
      harness.revocations.revoke(principal(), { proof, researcherId: targetId }),
    ]);
    expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
    expect(results.filter((result) => result.status === "rejected")).toHaveLength(1);
    expect(await sessionCounts()).toEqual({ operator: 1, other: 1, target: 0 });
    expect(await proofStates()).toEqual(["available", "consumed"]);
  });

  it("preserves target Sessions when Operator authority transfers after claim", async () => {
    const harness = service();
    const proof = await confirmProof(harness.proofs, targetId);
    const blocker = await owner.connect();
    let revoking: Promise<unknown> | undefined;
    try {
      await blocker.query(
        "SELECT pg_catalog.pg_advisory_lock(pg_catalog.hashtextextended($1, 0))",
        [credentialLockKey(targetEmail)],
      );
      revoking = harness.revocations.revoke(principal(), {
        proof,
        researcherId: targetId,
      });
      void revoking.catch(() => undefined);
      await waitForProofState("claimed");

      await new OperatorAssignmentService({ clock: () => fixedNow, pool: runtimePool })
        .transfer({ researcherId: otherId });
      await blocker.query(
        "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended($1, 0))",
        [credentialLockKey(targetEmail)],
      );
      await expect(revoking!).rejects.toEqual(new OperatorProofInvalidError());
    } finally {
      await blocker
        .query(
          "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended($1, 0))",
          [credentialLockKey(targetEmail)],
        )
        .catch(() => undefined);
      blocker.release();
      await revoking?.catch(() => undefined);
    }

    expect(await sessionCounts()).toEqual({ operator: 0, other: 1, target: 2 });
  });

});

function service(): Readonly<{
  proofs: OperatorProofService;
  revocations: OperatorSessionRevocationService;
}> {
  const proofs = new OperatorProofService({
    clock: () => fixedNow,
    createId: () =>
      `00000000-0000-4000-8000-${String(nextProofId++).padStart(12, "0")}`,
    pool: runtimePool,
    randomBytes: () => Buffer.alloc(32, nextProofId),
  });
  const access = new ResearcherAccessService({
    authSecret,
    clock: () => fixedNow,
    credentialCoordinator,
    pool: runtimePool,
  });
  return {
    proofs,
    revocations: new OperatorSessionRevocationService({ access, proofs }),
  };
}

async function confirmProof(
  proofs: OperatorProofService,
  researcherId: string,
): Promise<string> {
  return (
    await proofs.confirm(principal(), {
      operation: "researcher.sessions.revoke",
      password,
      researcherId,
    })
  ).proof;
}

function principal(): Readonly<{ researcherId: string; sessionId: string }> {
  return { researcherId: operatorId, sessionId: operatorSessionId };
}

async function insertResearcher(
  id: string,
  email: string,
  name: string,
): Promise<void> {
  await owner.query(
    `
      INSERT INTO auth."user" (
        id, name, email, "emailVerified", "createdAt", "updatedAt", active
      )
      VALUES ($1, $2, $3, TRUE, $4, $4, TRUE)
    `,
    [id, name, email, fixedNow],
  );
}

async function insertCredential(researcherId: string): Promise<void> {
  await owner.query(
    `
      INSERT INTO auth."account" (
        id, issuer, "accountId", "providerId", "userId", password,
        "createdAt", "updatedAt"
      )
      VALUES (
        '00000000-0000-4000-8000-000000000021',
        'credential',
        $1,
        'credential',
        $2,
        $3,
        $4,
        $4
      )
    `,
    [researcherId, researcherId, await hashPassword(password), fixedNow],
  );
}

async function insertSession(
  id: string,
  researcherId: string,
  token: string,
): Promise<void> {
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

async function sessionCounts(): Promise<Readonly<{
  operator: number;
  other: number;
  target: number;
}>> {
  const result = await owner.query<{
    operator_count: string;
    other_count: string;
    target_count: string;
  }>(
    `
      SELECT
        count(*) FILTER (WHERE "userId" = $1) AS operator_count,
        count(*) FILTER (WHERE "userId" = $2) AS target_count,
        count(*) FILTER (WHERE "userId" = $3) AS other_count
      FROM auth."session"
    `,
    [operatorId, targetId, otherId],
  );
  const row = result.rows[0];
  if (row === undefined) throw new Error("expected Session counts");
  return {
    operator: Number(row.operator_count),
    other: Number(row.other_count),
    target: Number(row.target_count),
  };
}

async function proofStates(): Promise<string[]> {
  const result = await owner.query<{ state: string }>(
    "SELECT state FROM auth.operator_proof ORDER BY created_at, id",
  );
  return result.rows.map((row) => row.state);
}

async function waitForProofState(state: string): Promise<void> {
  const deadline = performance.now() + 2_000;
  while (performance.now() < deadline) {
    const result = await owner.query<{ state: string }>(
      "SELECT state FROM auth.operator_proof",
    );
    if (result.rows[0]?.state === state) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`Proof did not reach ${state}`);
}

function roleDatabaseUrl(base: string, username: string, passwordValue: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = passwordValue;
  return url.toString();
}
