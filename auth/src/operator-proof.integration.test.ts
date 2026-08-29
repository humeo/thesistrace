import { hashPassword } from "better-auth/crypto";
import { Pool, type PoolClient } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { createAuthPool } from "./database.js";
import { OperatorAssignmentService } from "./operator-assignment.js";
import {
  OperatorPasswordInvalidError,
  OperatorProofInvalidError,
  OperatorProofService,
  type OperatorProofClaim,
} from "./operator-proof.js";
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
const operatorId = "00000000-0000-4000-8000-000000000001";
const operatorSessionId = "00000000-0000-4000-8000-000000000011";
const secondSessionId = "00000000-0000-4000-8000-000000000012";
const password = "correct-horse-battery-staple";
let now = new Date("2026-08-29T06:00:00.000Z");
let nextProofId = 100;

describe.sequential("Auth Operator Proof", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    now = new Date("2026-08-29T06:00:00.000Z");
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
    await runtimePool.end();
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("binds a 60-second opaque proof to canonical request, operation, and Login Session", async () => {
    const proofService = service();
    const confirmed = await proofService.confirm(principal(), {
      email: " Researcher@Example.COM ",
      operation: "invitation.issue",
      password,
    });

    expect(confirmed.expiresAt).toBe("2026-08-29T06:01:00.000Z");
    expect(confirmed.proof).toMatch(
      /^[0-9a-f-]{36}\.[A-Za-z0-9_-]{43}$/,
    );
    const persisted = await owner.query<{
      operation: string;
      state: string;
      token_hash: Buffer;
    }>("SELECT operation, state, token_hash FROM auth.operator_proof");
    expect(persisted.rows).toEqual([{
      operation: "invitation.issue",
      state: "available",
      token_hash: expect.any(Buffer),
    }]);
    expect(JSON.stringify(persisted.rows)).not.toContain(confirmed.proof);

    const claim = await proofService.claim(principal(), {
      email: "researcher@example.com",
      operation: "invitation.issue",
      proof: confirmed.proof,
    });
    await transaction(async (client) => {
      await expect(proofService.consumeClaim(client, claim)).resolves.toBe(true);
    });
    await expect(
      proofService.claim(principal(), {
        email: "researcher@example.com",
        operation: "invitation.issue",
        proof: confirmed.proof,
      }),
    ).rejects.toEqual(new OperatorProofInvalidError());
  });

  it("starts the lifetime after credential locking and rejects expiry reached behind a proof lock", async () => {
    const proofService = service();
    const credentialBlocker = await owner.connect();
    let credentialReleased = false;
    let confirming: Promise<Readonly<{ expiresAt: string; proof: string }>>;
    try {
      await credentialBlocker.query("BEGIN");
      await credentialBlocker.query(
        `
          SELECT id
          FROM auth."account"
          WHERE "userId" = $1 AND "providerId" = 'credential'
          FOR UPDATE
        `,
        [operatorId],
      );
      confirming = proofService.confirm(principal(), {
        email: "delayed@example.com",
        operation: "invitation.issue",
        password,
      });
      await waitForBlockedQuery("FROM auth.operator_assignment AS assignment");
      now = new Date("2026-08-29T06:00:30.000Z");
      await credentialBlocker.query("COMMIT");
      credentialReleased = true;
    } finally {
      if (!credentialReleased) {
        await credentialBlocker.query("ROLLBACK").catch(() => undefined);
      }
      credentialBlocker.release();
    }
    const confirmed = await confirming!;
    expect(confirmed.expiresAt).toBe("2026-08-29T06:01:30.000Z");

    const proofId = confirmed.proof.slice(0, confirmed.proof.indexOf("."));
    const proofBlocker = await owner.connect();
    let proofReleased = false;
    let claiming: Promise<OperatorProofClaim>;
    try {
      await proofBlocker.query("BEGIN");
      await proofBlocker.query(
        "SELECT id FROM auth.operator_proof WHERE id = $1 FOR UPDATE",
        [proofId],
      );
      claiming = proofService.claim(principal(), {
        email: "delayed@example.com",
        operation: "invitation.issue",
        proof: confirmed.proof,
      });
      await waitForBlockedQuery("FROM auth.operator_proof AS proof");
      now = new Date("2026-08-29T06:01:30.000Z");
      await proofBlocker.query("COMMIT");
      proofReleased = true;
    } finally {
      if (!proofReleased) {
        await proofBlocker.query("ROLLBACK").catch(() => undefined);
      }
      proofBlocker.release();
    }
    await expect(claiming!).rejects.toEqual(new OperatorProofInvalidError());
    expect(
      await owner.query<{ state: string }>(
        "SELECT state FROM auth.operator_proof WHERE id = $1",
        [proofId],
      ),
    ).toMatchObject({ rows: [{ state: "available" }] });
  });

  it("rejects an invalid password without creating a proof", async () => {
    await expect(
      service().confirm(principal(), {
        email: "researcher@example.com",
        operation: "invitation.issue",
        password: "wrong-password-is-long-enough",
      }),
    ).rejects.toEqual(new OperatorPasswordInvalidError());
    expect(
      await owner.query("SELECT id FROM auth.operator_proof"),
    ).toMatchObject({ rowCount: 0 });
  });

  it("fails closed for operation, request, Session, token, and expiry mismatch", async () => {
    const proofService = service();
    const confirmed = await proofService.confirm(principal(), {
      email: "bound@example.com",
      operation: "invitation.reissue",
      password,
    });
    const candidates = [
      {
        ...principal(),
        input: {
          email: "different@example.com",
          operation: "invitation.reissue" as const,
          proof: confirmed.proof,
        },
      },
      {
        ...principal(),
        input: {
          email: "bound@example.com",
          operation: "invitation.issue" as const,
          proof: confirmed.proof,
        },
      },
      {
        researcherId: operatorId,
        sessionId: secondSessionId,
        input: {
          email: "bound@example.com",
          operation: "invitation.reissue" as const,
          proof: confirmed.proof,
        },
      },
      {
        ...principal(),
        input: {
          email: "bound@example.com",
          operation: "invitation.reissue" as const,
          proof: `${confirmed.proof.slice(0, -1)}${confirmed.proof.endsWith("a") ? "b" : "a"}`,
        },
      },
    ];
    for (const candidate of candidates) {
      await expect(
        proofService.claim(
          {
            researcherId: candidate.researcherId,
            sessionId: candidate.sessionId,
          },
          candidate.input,
        ),
      ).rejects.toEqual(new OperatorProofInvalidError());
    }

    now = new Date("2026-08-29T06:01:00.000Z");
    await expect(
      proofService.claim(principal(), {
        email: "bound@example.com",
        operation: "invitation.reissue",
        proof: confirmed.proof,
      }),
    ).rejects.toEqual(new OperatorProofInvalidError());
  });

  it("admits only one concurrent claim and permits a released unexpired claim once", async () => {
    const proofService = service();
    const confirmed = await proofService.confirm(principal(), {
      email: "concurrent@example.com",
      operation: "invitation.issue",
      password,
    });
    const input = {
      email: "concurrent@example.com",
      operation: "invitation.issue" as const,
      proof: confirmed.proof,
    };

    const results = await Promise.allSettled([
      proofService.claim(principal(), input),
      proofService.claim(principal(), input),
    ]);
    const claims = results.flatMap((result) =>
      result.status === "fulfilled" ? [result.value] : []
    );
    expect(claims).toHaveLength(1);
    expect(results.filter((result) => result.status === "rejected")).toHaveLength(1);

    await proofService.release(claims[0] as OperatorProofClaim);
    const reclaimed = await proofService.claim(principal(), input);
    await transaction(async (client) => {
      await expect(proofService.consumeClaim(client, reclaimed)).resolves.toBe(true);
    });
    await expect(proofService.release(reclaimed)).resolves.toBeUndefined();
  });
});

function service(): OperatorProofService {
  return new OperatorProofService({
    clock: () => now,
    createId: () =>
      `00000000-0000-4000-8000-${String(nextProofId++).padStart(12, "0")}`,
    pool: runtimePool,
    randomBytes: () => Buffer.alloc(32, nextProofId),
  });
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

async function transaction(
  operation: (client: PoolClient) => Promise<void>,
): Promise<void> {
  const client = await runtimePool.connect();
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

async function waitForBlockedQuery(fragment: string): Promise<void> {
  const deadline = performance.now() + 2_000;
  while (true) {
    const result = await owner.query<{ waiting: boolean }>(
      `
        SELECT pg_catalog.bool_or(wait_event_type = 'Lock') AS waiting
        FROM pg_catalog.pg_stat_activity
        WHERE pid <> pg_catalog.pg_backend_pid()
          AND query ILIKE $1
      `,
      [`%${fragment}%`],
    );
    if (result.rows[0]?.waiting === true) return;
    if (performance.now() >= deadline) {
      throw new Error(`query did not block before deadline: ${fragment}`);
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  }
}

function roleDatabaseUrl(base: string, username: string, passwordValue: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = passwordValue;
  return url.toString();
}
