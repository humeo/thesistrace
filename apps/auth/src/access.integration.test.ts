import { emailSession } from "../test-fixtures/email-session.js";
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
import {
  OperatorDeactivationRejectedError,
  ResearcherAccessService,
} from "./access.js";
import { OperatorAssignmentService } from "./operator-assignment.js";
import { initializeAuthSchema } from "./schema-initialize.js";
import { enforceAuthSecretContract } from "./secret-contract.js";

const ownerDatabaseUrl = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (ownerDatabaseUrl === undefined) {
  throw new Error("THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL is required");
}

const authRuntimeDatabaseUrl = roleDatabaseUrl(
  ownerDatabaseUrl,
  "auth_runtime",
  "auth-test-password",
);
const owner = new Pool({ connectionString: ownerDatabaseUrl, max: 2 });
const runtimePool = createAuthPool(authRuntimeDatabaseUrl);
const coordinationPool = createAuthCoordinationPool(authRuntimeDatabaseUrl);
const settings = authTestSettings({ databaseUrl: authRuntimeDatabaseUrl });
const fixedNow = new Date("2026-08-28T06:00:00.000Z");
const credentialCoordinator = new CredentialOperationCoordinator({
  authSecret: settings.secret,
  coordination: new AuthOperationCoordinator(coordinationPool),
  pool: runtimePool,
});
const lifecycle: AuthLifecycleDependencies = {
  backgroundTask(promise) {
    void promise.catch(() => undefined);
  },
  async isResearcherActive(userId) {
    const result = await runtimePool.query<{ active: boolean }>(
      'SELECT active FROM auth."user" WHERE id = $1',
      [userId],
    );
    return result.rows[0]?.active === true;
  },
  recordSession() {},
};

describe.sequential("Auth operator access lifecycle", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    await owner.query(`
      TRUNCATE
        auth.auth_secret_contract,
        auth.operator_assignment,
        auth.security_audit,


        auth."rateLimit",
        auth."verification",
        auth."user"
      CASCADE
    `);
  });

  afterAll(async () => {
    await Promise.all([coordinationPool.end(), runtimePool.end()]);
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("deactivates atomically, revokes every access grant, and is idempotent", async () => {
    const researcherId = await createUser("deactivate@example.com");
    const access = service();

    await expect(access.deactivate(researcherId)).resolves.toEqual({
      researcherId,
      status: "updated",
    });
    expect(await persistedAccessState(researcherId)).toEqual({
      active: false,
      sessions: 0,
    });
    await expect(access.deactivate(researcherId)).resolves.toEqual({
      researcherId,
      status: "no_change",
    });
    const audits = await owner.query<{ event: string; outcome: string }>(`
      SELECT event, outcome
      FROM auth.security_audit
      WHERE event = 'researcher_deactivated'
    `);
    expect(audits.rows).toHaveLength(2);
    expect(audits.rows).toEqual(
      expect.arrayContaining([
        { event: "researcher_deactivated", outcome: "succeeded" },
        { event: "researcher_deactivated", outcome: "no_change" },
      ]),
    );
  });

  it("serializes deactivation before hard secret rotation", async () => {
    await enforceAuthSecretContract(runtimePool, settings.secret);
    const researcherId = await createUser("rotation-deactivate@example.com");
    const blocker = await owner.connect();
    let deactivating: Promise<unknown> | undefined;
    let rotating: Promise<unknown> | undefined;
    try {
      await blocker.query("BEGIN");
      await blocker.query(
        'SELECT id FROM auth."user" WHERE id = $1 FOR UPDATE',
        [researcherId],
      );
      deactivating = service().deactivate(researcherId);
      void deactivating.catch(() => undefined);
      await waitForCondition(() => hasBlockedRuntimeQuery('FROM auth."user"'));

      rotating = enforceAuthSecretContract(runtimePool, "abcdef0123456789abcdef0123456789");
      void rotating.catch(() => undefined);
      await waitForCondition(() =>
        hasBlockedRuntimeQuery("pg_advisory_xact_lock(")
      );

      await blocker.query("COMMIT");
      await expect(deactivating).resolves.toEqual({
        researcherId,
        status: "updated",
      });
      await expect(rotating).resolves.toEqual({ status: "rotated" });
    } finally {
      await blocker.query("ROLLBACK").catch(() => undefined);
      blocker.release();
      await Promise.allSettled(
        [deactivating, rotating].filter(
          (operation): operation is Promise<unknown> => operation !== undefined,
        ),
      );
    }

    expect(await persistedAccessState(researcherId)).toEqual({
      active: false,
      sessions: 0,
    });
  });

  it("reactivates without creating or restoring a Session", async () => {
    const researcherId = await createUser("reactivate@example.com");
    const access = service();
    await access.deactivate(researcherId);

    await expect(access.reactivate(researcherId)).resolves.toEqual({
      researcherId,
      status: "updated",
    });
    await expect(access.reactivate(researcherId)).resolves.toEqual({
      researcherId,
      status: "no_change",
    });

    expect(await persistedAccessState(researcherId)).toMatchObject({
      active: true,
      sessions: 0,
    });
  });

  it("cannot deactivate the Researcher holding the Operator Capability", async () => {
    const researcherId = await createUser("operator@example.com");
    await new OperatorAssignmentService({ pool: runtimePool }).assign({
      researcherId,
    });

    await expect(service().deactivate(researcherId)).rejects.toBeInstanceOf(
      OperatorDeactivationRejectedError,
    );
    expect(await persistedAccessState(researcherId)).toMatchObject({
      active: true,
      sessions: 1,
    });
  });

  it("cannot insert a Session after deactivation wins the sign-in race", async () => {
    const researcherId = await createUser("race@example.com");
    await owner.query('DELETE FROM auth."session" WHERE "userId" = $1', [
      researcherId,
    ]);
    let observedActive: (() => void) | undefined;
    const activeObserved = new Promise<void>((resolve) => {
      observedActive = resolve;
    });
    let continueSessionCreate: (() => void) | undefined;
    const sessionCreateReleased = new Promise<void>((resolve) => {
      continueSessionCreate = resolve;
    });
    const auth = createThesisTraceAuth(settings, runtimePool, {
      ...lifecycle,
      async isResearcherActive(userId) {
        const result = await runtimePool.query<{ active: boolean }>(
          'SELECT active FROM auth."user" WHERE id = $1',
          [userId],
        );
        const active = result.rows[0]?.active === true;
        if (active) {
          observedActive?.();
          await sessionCreateReleased;
        }
        return active;
      },
    });

    const signingIn = auth.handler(
      new Request(`${settings.publicOrigin}/api/auth/sign-in/email-otp`, {
        body: JSON.stringify({
          email: "race@example.com",
          otp: await auth.api.createVerificationOTP({ body: { email: "race@example.com", type: "sign-in" } }),
        }),
        headers: {
          "content-type": "application/json",
          origin: settings.publicOrigin,
          "x-thesistrace-client-ip": "192.0.2.30",
        },
        method: "POST",
      }),
    );
    await activeObserved;
    await service().deactivate(researcherId);
    continueSessionCreate?.();
    const response = await signingIn;

    expect(response.status).not.toBe(200);
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(await persistedAccessState(researcherId)).toMatchObject({
      active: false,
      sessions: 0,
    });
    await service().reactivate(researcherId);
    expect(await persistedAccessState(researcherId)).toMatchObject({
      active: true,
      sessions: 0,
    });
  });

  it("revokes Sessions and corrects the display label idempotently", async () => {
    const researcherId = await createUser("label@example.com");
    await signIn("label@example.com");
    const access = service();

    await expect(access.revokeSessions(researcherId)).resolves.toEqual({
      researcherId,
      status: "updated",
    });
    await expect(access.revokeSessions(researcherId)).resolves.toEqual({
      researcherId,
      status: "no_change",
    });
    await expect(
      access.correctDisplayLabel(researcherId, "Research Lead"),
    ).resolves.toEqual({ researcherId, status: "updated" });
    await expect(
      access.correctDisplayLabel(researcherId, "Research Lead"),
    ).resolves.toEqual({ researcherId, status: "no_change" });

    expect(
      await owner.query<{ email: string; name: string }>(
        'SELECT email, name FROM auth."user" WHERE id = $1',
        [researcherId],
      ),
    ).toMatchObject({
      rows: [{ email: "label@example.com", name: "Research Lead" }],
    });
    expect(await persistedAccessState(researcherId)).toMatchObject({ sessions: 0 });
  });
});

function service(): ResearcherAccessService {
  return new ResearcherAccessService({
    authSecret: settings.secret,
    clock: () => fixedNow,
    credentialCoordinator,
    pool: runtimePool,
  });
}

async function hasBlockedRuntimeQuery(fragment: string): Promise<boolean> {
  const result = await owner.query<{ waiting: boolean }>(
    `
      SELECT pg_catalog.bool_or(
        pg_catalog.cardinality(pg_catalog.pg_blocking_pids(pid)) > 0
      ) AS waiting
      FROM pg_catalog.pg_stat_activity
      WHERE application_name = 'thesistrace_auth'
        AND query ILIKE $1
    `,
    [`%${fragment}%`],
  );
  return result.rows[0]?.waiting === true;
}

async function waitForCondition(
  condition: () => Promise<boolean>,
): Promise<void> {
  const deadline = performance.now() + 1_000;
  while (performance.now() < deadline) {
    if (await condition()) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("condition was not reached before its deadline");
}

function requestHeaders(): Headers {
  return new Headers({
    origin: settings.publicOrigin,
    "x-thesistrace-client-ip": "192.0.2.30",
  });
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}

async function createUser(email: string): Promise<string> {
  const auth = createThesisTraceAuth(settings, runtimePool, lifecycle);
  expect((await emailSession(auth, email, requestHeaders())).status).toBe(200);
  return (await owner.query<{id: string}>('SELECT id FROM auth."user" WHERE email=$1', [email])).rows[0]!.id;
}
async function signIn(email: string): Promise<void> {
  const auth = createThesisTraceAuth(settings, runtimePool, lifecycle);
  expect((await emailSession(auth, email, requestHeaders())).status).toBe(200);
}

async function persistedAccessState(researcherId: string): Promise<{active: boolean; sessions: number}> {
  const result = await owner.query<{active: boolean; sessions: string}>(`SELECT u.active, (SELECT count(*) FROM auth."session" s WHERE s."userId"=u.id) AS sessions FROM auth."user" u WHERE u.id=$1`, [researcherId]);
  const row=result.rows[0]!; return {active: row.active, sessions: Number(row.sessions)};
}
