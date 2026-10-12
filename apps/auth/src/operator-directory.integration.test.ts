import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { createAuthPool } from "./database.js";
import { OperatorAssignmentService } from "./operator-assignment.js";
import {
  OperatorAccessNotFoundError,
  OperatorCursorInvalidError,
  OperatorDirectoryService,
} from "./operator-directory.js";
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
const ordinaryId = "00000000-0000-4000-8000-000000000002";
const targetId = "00000000-0000-4000-8000-000000000003";
const operatorSessionId = "00000000-0000-4000-8000-000000000011";
const ordinarySessionId = "00000000-0000-4000-8000-000000000012";
const fixedNow = new Date("2026-08-29T06:00:00.000Z");
const authSecret = "0123456789abcdef0123456789abcdef";

describe.sequential("Auth Operator directory", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    await owner.query(`
      TRUNCATE
        auth.operator_assignment,
        auth.security_audit,


        auth."rateLimit",
        auth."verification",
        auth."user"
      CASCADE
    `);
    await insertResearcher(operatorId, "operator@example.com", "Operator", fixedNow);
    await insertResearcher(ordinaryId, "ordinary@example.com", "Ordinary", fixedNow);
    await insertSession(operatorSessionId, "operator-session", operatorId, 24);
    await insertSession(ordinarySessionId, "ordinary-session", ordinaryId, 24);
    await new OperatorAssignmentService({ clock: () => fixedNow, pool: runtimePool })
      .assign({ researcherId: operatorId });
  });

  afterAll(async () => {
    await runtimePool.end();
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("authorizes only the current active Operator Login Session", async () => {
    const directory = service();
    await expect(directory.isOperator(operatorId)).resolves.toBe(true);
    await expect(directory.isOperator(ordinaryId)).resolves.toBe(false);

    await expect(directory.hasCapability(operatorPrincipal())).resolves.toBe(true);
    await expect(directory.hasCapability({
      researcherId: ordinaryId,
      sessionId: ordinarySessionId,
    })).resolves.toBe(false);
    await owner.query(
      'UPDATE auth."session" SET "expiresAt" = $2 WHERE id = $1',
      [operatorSessionId, new Date("2026-08-29T05:59:59.000Z")],
    );
    await expect(directory.hasCapability(operatorPrincipal())).resolves.toBe(false);
    await expect(
      directory.listResearchers(operatorPrincipal(), { cursor: null, search: null }),
    ).rejects.toBeInstanceOf(OperatorAccessNotFoundError);
  });

  it("projects bounded Researcher fields with literal search", async () => {
    await insertResearcher(
      targetId,
      "target@example.com",
      "Alpha % Lead",
      new Date("2026-08-28T06:00:00.000Z"),
    );
    await insertSession(
      "00000000-0000-4000-8000-000000000021",
      "target-current-session",
      targetId,
      2,
    );
    await insertSession(
      "00000000-0000-4000-8000-000000000022",
      "target-expired-session",
      targetId,
      -2,
    );
    await insertSuccessfulLogin(
      "00000000-0000-4000-8000-000000000031",
      targetId,
      new Date("2026-08-28T08:00:00.000Z"),
      "succeeded",
    );
    await insertSuccessfulLogin(
      "00000000-0000-4000-8000-000000000032",
      targetId,
      new Date("2026-08-28T09:00:00.000Z"),
      "succeeded",
    );
    await insertSuccessfulLogin(
      "00000000-0000-4000-8000-000000000033",
      targetId,
      new Date("2026-08-28T10:00:00.000Z"),
      "failed",
    );

    const directory = service();
    const byEmail = await directory.listResearchers(operatorPrincipal(), {
      cursor: null,
      search: " TARGET@EXAMPLE ",
    });
    const byLiteralLabel = await directory.listResearchers(operatorPrincipal(), {
      cursor: null,
      search: "%",
    });

    expect(byEmail).toEqual(byLiteralLabel);
    expect(byEmail.nextCursor).toBeNull();
    expect(byEmail.items).toHaveLength(1);
    expect(byEmail.items[0]).toEqual({
      active: true,
      createdAt: "2026-08-28T06:00:00.000Z",
      currentSessionCount: 1,
      displayLabel: "Alpha % Lead",
      email: "target@example.com",
      id: targetId,
      latestSuccessfulLoginAt: "2026-08-28T09:00:00.000Z",
    });
    expect(Object.keys(byEmail.items[0] ?? {})).not.toEqual(
      expect.arrayContaining(["ipAddress", "userAgent", "securityHistory"]),
    );
  });

  it("paginates Researchers in stable 50-row pages and binds the cursor to search", async () => {
    for (let index = 1; index <= 55; index += 1) {
      await insertResearcher(
        numberedId(index),
        `page-${String(index).padStart(2, "0")}@example.com`,
        `Page ${index}`,
        new Date("2026-08-28T00:00:00.000Z"),
      );
    }
    const directory = service();
    const first = await directory.listResearchers(operatorPrincipal(), {
      cursor: null,
      search: "page-",
    });
    expect(first.items).toHaveLength(50);
    expect(first.nextCursor).not.toBeNull();
    if (first.nextCursor === null) throw new Error("expected Researcher cursor");

    const second = await directory.listResearchers(operatorPrincipal(), {
      cursor: first.nextCursor,
      search: "page-",
    });
    expect(second.items).toHaveLength(5);
    expect(second.nextCursor).toBeNull();
    expect(new Set([...first.items, ...second.items].map((item) => item.id)).size).toBe(55);
    await expect(
      directory.listResearchers(operatorPrincipal(), {
        cursor: first.nextCursor,
        search: "different",
      }),
    ).rejects.toBeInstanceOf(OperatorCursorInvalidError);
  });
});

function service(): OperatorDirectoryService {
  return new OperatorDirectoryService({
    authSecret,
    clock: () => fixedNow,
    pool: runtimePool,
    randomBytes: (size) => Buffer.alloc(size, 7),
  });
}

function operatorPrincipal(): Readonly<{ researcherId: string; sessionId: string }> {
  return { researcherId: operatorId, sessionId: operatorSessionId };
}

async function insertResearcher(
  id: string,
  email: string,
  name: string,
  createdAt: Date,
): Promise<void> {
  await owner.query(
    `
      INSERT INTO auth."user" (
        id, name, email, "emailVerified", "createdAt", "updatedAt", active
      )
      VALUES ($1, $2, $3, TRUE, $4, $4, TRUE)
    `,
    [id, name, email, createdAt],
  );
}

async function insertSession(
  id: string,
  token: string,
  researcherId: string,
  expiresInHours: number,
): Promise<void> {
  await owner.query(
    `
      INSERT INTO auth."session" (
        id, "expiresAt", token, "createdAt", "updatedAt", "userId"
      )
      VALUES ($1, $2, $3, $4, $4, $5)
    `,
    [
      id,
      new Date(fixedNow.getTime() + expiresInHours * 60 * 60 * 1_000),
      token,
      fixedNow,
      researcherId,
    ],
  );
}

async function insertSuccessfulLogin(
  id: string,
  researcherId: string,
  occurredAt: Date,
  outcome: "failed" | "succeeded",
): Promise<void> {
  await owner.query(
    `
      INSERT INTO auth.security_audit (
        id, occurred_at, event, outcome, researcher_id
      )
      VALUES ($1, $2, 'sign_in_succeeded', $3, $4)
    `,
    [id, occurredAt, outcome, researcherId],
  );
}

function tokenHash(id: string): Buffer {
  return Buffer.from(id.replaceAll("-", "").padEnd(64, "0").slice(0, 64), "hex");
}

function numberedId(index: number): string {
  return `00000000-0000-4000-8001-${String(index).padStart(12, "0")}`;
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
