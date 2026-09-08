import { hashPassword } from "better-auth/crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import {
  createThesisTraceAuth,
  type AuthLifecycleDependencies,
} from "./auth.js";
import { authTestSettings } from "../test-fixtures/auth-settings.js";
import {
  AuthOperationCoordinator,
  CredentialOperationCoordinator,
} from "./coordination.js";
import { createAuthCoordinationPool, createAuthPool } from "./database.js";
import { InvitationAdmission } from "./invitation-admission.js";
import {
  InvitationDeliveryError,
  ResearcherInvitationService,
} from "./invitation.js";
import { OperatorAssignmentService } from "./operator-assignment.js";
import { OperatorInvitationService } from "./operator-invitation.js";
import {
  OperatorProofInvalidError,
  OperatorProofService,
} from "./operator-proof.js";
import type { ResendEmail } from "./resend.js";
import { initializeAuthSchema } from "./schema-initialize.js";
import { enforceAuthSecretContract } from "./secret-contract.js";

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
const operatorId = "00000000-0000-4000-8000-000000000001";
const operatorSessionId = "00000000-0000-4000-8000-000000000011";
const secondSessionId = "00000000-0000-4000-8000-000000000012";
const replacementOperatorId = "00000000-0000-4000-8000-000000000002";
const password = "correct-horse-battery-staple";
let now = new Date("2026-08-29T06:00:00.000Z");

const settings = authTestSettings({
  databaseUrl: runtimeDatabaseUrl,
  secret: authSecret,
});
const invitationAdmission = new InvitationAdmission();
const lifecycle: AuthLifecycleDependencies = {
  backgroundTask(task) {
    void task.catch(() => undefined);
  },
  invitationAdmission,
  async isResearcherActive(researcherId) {
    const result = await runtimePool.query<{ active: boolean }>(
      'SELECT active FROM auth."user" WHERE id = $1',
      [researcherId],
    );
    return result.rows[0]?.active === true;
  },
  recordPasswordResetCredential() {},
  recordSession() {},
  async sendResetPassword() {},
};
const credentialCoordinator = new CredentialOperationCoordinator({
  authSecret,
  coordination: new AuthOperationCoordinator(coordinationPool),
  pool: runtimePool,
});

describe.sequential("Operator Invitation authorization", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    now = new Date("2026-08-29T06:00:00.000Z");
    await owner.query(`
      TRUNCATE
        auth.auth_secret_contract,
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
    await owner.query(
      `
        INSERT INTO auth."user" (
          id, name, email, "emailVerified", "createdAt", "updatedAt", active
        )
        VALUES ($1, 'Operator', 'operator@example.com', TRUE, $2, $2, TRUE)
      `,
      [operatorId, now],
    );
    await owner.query(
      `
        INSERT INTO auth."account" (
          id, issuer, "accountId", "providerId", "userId", password,
          "createdAt", "updatedAt"
        )
        VALUES (
          '00000000-0000-4000-8000-000000000021',
          'credential', $1, 'credential', $2, $3, $4, $4
        )
      `,
      [operatorId, operatorId, await hashPassword(password), now],
    );
    await insertSession(operatorSessionId);
    await insertSession(secondSessionId);
    await new OperatorAssignmentService({ clock: () => now, pool: runtimePool })
      .assign({ researcherId: operatorId });
  });

  afterAll(async () => {
    await coordinationPool.end();
    await runtimePool.end();
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("atomically consumes one proof for one concurrent issue and rejects replay", async () => {
    const harness = createHarness();
    const confirmed = await harness.proofs.confirm(principal(), {
      email: "concurrent@example.com",
      operation: "invitation.issue",
      otp: "123456",
    });

    const attempts = await Promise.allSettled([
      harness.operatorInvitations.issue(principal(), {
        email: "concurrent@example.com",
        proof: confirmed.proof,
      }),
      harness.operatorInvitations.issue(principal(), {
        email: "concurrent@example.com",
        proof: confirmed.proof,
      }),
    ]);
    expect(attempts.filter((attempt) => attempt.status === "fulfilled"))
      .toHaveLength(1);
    const rejection = attempts.find((attempt) => attempt.status === "rejected");
    expect(rejection).toMatchObject({ reason: new OperatorProofInvalidError() });
    expect(harness.sent).toHaveLength(1);
    expect(await lifecycleRows()).toEqual({
      invitations: ["delivered"],
      proofs: ["consumed"],
    });

    await expect(
      harness.operatorInvitations.issue(principal(), {
        email: "concurrent@example.com",
        proof: confirmed.proof,
      }),
    ).rejects.toEqual(new OperatorProofInvalidError());
    expect(harness.sent).toHaveLength(1);

    const replacementProof = await harness.proofs.confirm(principal(), {
      email: "concurrent@example.com",
      operation: "invitation.reissue",
      otp: "123456",
    });
    await expect(
      harness.operatorInvitations.reissue(principal(), {
        email: "concurrent@example.com",
        proof: replacementProof.proof,
      }),
    ).resolves.toMatchObject({ status: "delivered" });
    expect(harness.sent).toHaveLength(2);
    expect(await lifecycleRows()).toEqual({
      invitations: ["revoked", "delivered"],
      proofs: ["consumed", "consumed"],
    });
  });

  it("releases an unexpired proof after failed replacement delivery", async () => {
    let failDelivery = false;
    const harness = createHarness(async () => {
      if (failDelivery) throw new Error("delivery failed");
    });
    await harness.invitations.issue("preserved@example.com");
    const confirmed = await harness.proofs.confirm(principal(), {
      email: "preserved@example.com",
      operation: "invitation.reissue",
      otp: "123456",
    });

    failDelivery = true;
    await expect(
      harness.operatorInvitations.reissue(principal(), {
        email: "preserved@example.com",
        proof: confirmed.proof,
      }),
    ).rejects.toEqual(new InvitationDeliveryError());
    expect(await lifecycleRows()).toEqual({
      invitations: ["delivered", "delivery_failed"],
      proofs: ["available"],
    });

    failDelivery = false;
    await expect(
      harness.operatorInvitations.reissue(principal(), {
        email: "preserved@example.com",
        proof: confirmed.proof,
      }),
    ).resolves.toMatchObject({ status: "delivered" });
    expect(await lifecycleRows()).toEqual({
      invitations: ["revoked", "delivery_failed", "delivered"],
      proofs: ["consumed"],
    });
  });

  it("rejects request, operation, Session, and expiry mismatch before delivery", async () => {
    const harness = createHarness();
    const confirmed = await harness.proofs.confirm(principal(), {
      email: "bound@example.com",
      operation: "invitation.issue",
      otp: "123456",
    });
    for (const attempt of [
      () => harness.operatorInvitations.issue(principal(), {
        email: "different@example.com",
        proof: confirmed.proof,
      }),
      () => harness.operatorInvitations.reissue(principal(), {
        email: "bound@example.com",
        proof: confirmed.proof,
      }),
      () => harness.operatorInvitations.issue(
        { researcherId: operatorId, sessionId: secondSessionId },
        { email: "bound@example.com", proof: confirmed.proof },
      ),
    ]) {
      await expect(attempt()).rejects.toEqual(new OperatorProofInvalidError());
    }
    now = new Date("2026-08-29T06:01:00.000Z");
    await expect(
      harness.operatorInvitations.issue(principal(), {
        email: "bound@example.com",
        proof: confirmed.proof,
      }),
    ).rejects.toEqual(new OperatorProofInvalidError());
    expect(harness.sent).toHaveLength(0);
    expect(await lifecycleRows()).toEqual({
      invitations: [],
      proofs: ["available"],
    });
  });

  it.each([
    ["Login Session is revoked", "session", []],
    ["Operator is transferred", "operator", []],
    ["proof expires", "expiry", ["claimed"]],
  ] as const)(
    "rechecks final authorization after delivery when the %s",
    async (_label, invalidation, expectedProofs) => {
      let pauseDelivery = false;
      let markDeliveryStarted: () => void = () => undefined;
      let releaseDelivery: () => void = () => undefined;
      const deliveryStarted = new Promise<void>((resolve) => {
        markDeliveryStarted = resolve;
      });
      const deliveryReleased = new Promise<void>((resolve) => {
        releaseDelivery = resolve;
      });
      const email = `${invalidation}-invalidated@example.com`;
      const harness = createHarness(async () => {
        if (!pauseDelivery) return;
        markDeliveryStarted();
        await deliveryReleased;
      });
      await harness.invitations.issue(email);
      const confirmed = await harness.proofs.confirm(principal(), {
        email,
        operation: "invitation.reissue",
        otp: "123456",
      });

      pauseDelivery = true;
      const replacing = harness.operatorInvitations.reissue(principal(), {
        email,
        proof: confirmed.proof,
      });
      await deliveryStarted;
      expect(await lifecycleRows()).toEqual({
        invitations: ["delivered", "replacement_pending"],
        proofs: ["claimed"],
      });

      if (invalidation === "session") {
        await owner.query('DELETE FROM auth."session" WHERE id = $1', [
          operatorSessionId,
        ]);
      } else if (invalidation === "operator") {
        await insertReplacementOperator();
        await new OperatorAssignmentService({ clock: () => now, pool: runtimePool })
          .transfer({ researcherId: replacementOperatorId });
      } else {
        now = new Date(now.getTime() + 60_000);
      }
      releaseDelivery();

      await expect(replacing).rejects.toEqual(new OperatorProofInvalidError());
      expect(await lifecycleRows()).toEqual({
        invitations: ["delivered", "delivery_failed"],
        proofs: [...expectedProofs],
      });
      expect(await effectiveInvitationStatuses(email)).toEqual(["delivered"]);
    },
  );

  it("serializes production Operator transfer with invitation finalization", async () => {
    let pauseDelivery = false;
    let markDeliveryStarted: () => void = () => undefined;
    let releaseDelivery: () => void = () => undefined;
    const deliveryStarted = new Promise<void>((resolve) => {
      markDeliveryStarted = resolve;
    });
    const deliveryReleased = new Promise<void>((resolve) => {
      releaseDelivery = resolve;
    });
    const email = "transfer-overlap@example.com";
    const harness = createHarness(async () => {
      if (!pauseDelivery) return;
      markDeliveryStarted();
      await deliveryReleased;
    });
    await harness.invitations.issue(email);
    const confirmed = await harness.proofs.confirm(principal(), {
      email,
      operation: "invitation.reissue",
      otp: "123456",
    });
    await insertReplacementOperator();
    const blocker = await owner.connect();
    let replacing: Promise<unknown> | undefined;
    let transferring: Promise<unknown> | undefined;
    try {
      await blocker.query("BEGIN");
      await blocker.query(
        'SELECT id FROM auth."session" WHERE "userId" = $1 FOR UPDATE',
        [operatorId],
      );
      pauseDelivery = true;
      replacing = harness.operatorInvitations.reissue(principal(), {
        email,
        proof: confirmed.proof,
      });
      void replacing.catch(() => undefined);
      await deliveryStarted;

      transferring = new OperatorAssignmentService({
        clock: () => now,
        pool: runtimePool,
      }).transfer({ researcherId: replacementOperatorId });
      void transferring.catch(() => undefined);
      await waitForBlockedRuntimeQuery('DELETE FROM auth."session"');
      releaseDelivery();
      await waitForBlockedRuntimeQuery("pg_advisory_xact_lock(");

      await blocker.query("COMMIT");
      await expect(transferring).resolves.toMatchObject({
        formerOperatorResearcherId: operatorId,
        operatorResearcherId: replacementOperatorId,
        status: "transferred",
      });
      await expect(replacing).rejects.toEqual(new OperatorProofInvalidError());
    } finally {
      releaseDelivery();
      await blocker.query("ROLLBACK").catch(() => undefined);
      blocker.release();
      await Promise.allSettled(
        [replacing, transferring].filter(
          (operation): operation is Promise<unknown> => operation !== undefined,
        ),
      );
    }

    expect(await lifecycleRows()).toEqual({
      invitations: ["delivered", "delivery_failed"],
      proofs: [],
    });
    expect(await effectiveInvitationStatuses(email)).toEqual(["delivered"]);
  });

  it("serializes hard rotation before Session revocation during finalization", async () => {
    await enforceAuthSecretContract(runtimePool, authSecret, () => now);
    let pauseDelivery = false;
    let markDeliveryStarted: () => void = () => undefined;
    let releaseDelivery: () => void = () => undefined;
    const deliveryStarted = new Promise<void>((resolve) => {
      markDeliveryStarted = resolve;
    });
    const deliveryReleased = new Promise<void>((resolve) => {
      releaseDelivery = resolve;
    });
    const email = "rotation-overlap@example.com";
    const harness = createHarness(async () => {
      if (!pauseDelivery) return;
      markDeliveryStarted();
      await deliveryReleased;
    });
    await harness.invitations.issue(email);
    const confirmed = await harness.proofs.confirm(principal(), {
      email,
      operation: "invitation.reissue",
      otp: "123456",
    });
    const blocker = await owner.connect();
    let replacing: Promise<unknown> | undefined;
    let rotating: Promise<unknown> | undefined;
    try {
      await blocker.query("BEGIN");
      await blocker.query(
        'SELECT id FROM auth."session" WHERE id = $1 FOR UPDATE',
        [operatorSessionId],
      );
      pauseDelivery = true;
      replacing = harness.operatorInvitations.reissue(principal(), {
        email,
        proof: confirmed.proof,
      });
      await deliveryStarted;

      rotating = enforceAuthSecretContract(
        runtimePool,
        "abcdef0123456789abcdef0123456789",
        () => now,
      );
      void rotating.catch(() => undefined);
      await waitForBlockedRuntimeQuery('DELETE FROM auth."session"');
      releaseDelivery();
      await waitForBlockedRuntimeQuery("pg_advisory_lock_shared");

      await blocker.query("COMMIT");
      await expect(rotating).resolves.toEqual({ status: "rotated" });
      await expect(replacing).rejects.toEqual(new InvitationDeliveryError());
    } finally {
      releaseDelivery();
      await blocker.query("ROLLBACK").catch(() => undefined);
      blocker.release();
      await Promise.allSettled(
        [replacing, rotating].filter(
          (operation): operation is Promise<unknown> => operation !== undefined,
        ),
      );
    }

    expect(await lifecycleRows()).toEqual({
      invitations: ["revoked", "revoked"],
      proofs: [],
    });
  });
});

function createHarness(
  delivery: (email: ResendEmail) => Promise<void> = async () => undefined,
) {
  let nextInvitationId = 100;
  let nextProofId = 200;
  const sent: ResendEmail[] = [];
  const auth = createThesisTraceAuth(settings, runtimePool, lifecycle);
  const invitations = new ResearcherInvitationService({
    auth,
    authSecret,
    clock: () => now,
    createId: () => nextId(nextInvitationId++),
    credentialCoordinator,
    invitationAdmission,
    pool: runtimePool,
    publicOrigin: settings.publicOrigin,
    randomBytes: () => Buffer.alloc(32, nextInvitationId),
    async sendEmail(email) {
      sent.push(email);
      await delivery(email);
    },
  });
  const proofs = new OperatorProofService({
    verifyCode: async (_principal, otp) => { if (otp !== "123456") throw new Error("invalid-test-code"); },
    clock: () => now,
    createId: () => nextId(nextProofId++),
    pool: runtimePool,
    randomBytes: () => Buffer.alloc(32, nextProofId),
  });
  return {
    invitations,
    operatorInvitations: new OperatorInvitationService({ invitations, proofs }),
    proofs,
    sent,
  };
}

async function lifecycleRows(): Promise<Readonly<{
  invitations: string[];
  proofs: string[];
}>> {
  const invitations = await owner.query<{ status: string }>(
    "SELECT status FROM auth.researcher_invitation ORDER BY created_at, id",
  );
  const proofs = await owner.query<{ state: string }>(
    "SELECT state FROM auth.operator_proof ORDER BY created_at, id",
  );
  return {
    invitations: invitations.rows.map((row) => row.status),
    proofs: proofs.rows.map((row) => row.state),
  };
}

async function effectiveInvitationStatuses(email: string): Promise<string[]> {
  const result = await owner.query<{ status: string }>(
    `
      SELECT status
      FROM auth.researcher_invitation
      WHERE email = $1
        AND status IN ('delivery_pending', 'delivered')
        AND expires_at > $2
      ORDER BY created_at, id
    `,
    [email, now],
  );
  return result.rows.map((row) => row.status);
}

function principal(): Readonly<{ researcherId: string; sessionId: string }> {
  return { researcherId: operatorId, sessionId: operatorSessionId };
}

async function insertSession(id: string): Promise<void> {
  await owner.query(
    `
      INSERT INTO auth."session" (
        id, "expiresAt", token, "createdAt", "updatedAt", "userId"
      )
      VALUES ($1::uuid, $2, $1::uuid::text, $3, $3, $4)
    `,
    [id, new Date(now.getTime() + 24 * 60 * 60 * 1_000), now, operatorId],
  );
}

async function insertReplacementOperator(): Promise<void> {
  await owner.query(
    `
      INSERT INTO auth."user" (
        id, name, email, "emailVerified", "createdAt", "updatedAt", active
      )
      VALUES ($1, 'Replacement Operator', 'replacement-operator@example.com', TRUE, $2, $2, TRUE)
    `,
    [replacementOperatorId, now],
  );
}

async function waitForBlockedRuntimeQuery(fragment: string): Promise<void> {
  const deadline = performance.now() + 1_000;
  while (performance.now() < deadline) {
    const result = await owner.query<{ blocked: boolean }>(
      `
        SELECT pg_catalog.bool_or(
          pg_catalog.cardinality(pg_catalog.pg_blocking_pids(pid)) > 0
        ) AS blocked
        FROM pg_catalog.pg_stat_activity
        WHERE usename = 'auth_runtime'
          AND query ILIKE $1
      `,
      [`%${fragment}%`],
    );
    if (result.rows[0]?.blocked === true) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`runtime query did not block before deadline: ${fragment}`);
}

function nextId(value: number): string {
  return `00000000-0000-4000-8000-${String(value).padStart(12, "0")}`;
}

function roleDatabaseUrl(base: string, username: string, passwordValue: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = passwordValue;
  return url.toString();
}
