import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import {
  createThesisTraceAuth,
  type AuthLifecycleDependencies,
} from "./auth.js";
import { createAuthApp } from "./app.js";
import { AuthEndpointRateLimiter } from "./auth-rate-limit.js";
import { authTestSettings } from "../test-fixtures/auth-settings.js";
import {
  AuthOperationCoordinator,
  CredentialOperationCoordinator,
  credentialLockKey,
} from "./coordination.js";
import { createAuthCoordinationPool, createAuthPool } from "./database.js";
import { InvitationAdmission } from "./invitation-admission.js";
import {
  InvitationConflictError,
  InvitationDeliveryError,
  InvitationRejectedError,
  InvitationServiceUnavailableError,
  ResearcherInvitationService,
} from "./invitation.js";
import type { ResendEmail } from "./resend.js";
import { initializeAuthSchema } from "./schema-initialize.js";
import { enforceAuthSecretContract } from "./secret-contract.js";
import { sha256, unknownEmailHmac } from "./security.js";

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
const settingsSecret = "0123456789abcdef0123456789abcdef";
const coordination = new AuthOperationCoordinator(coordinationPool);
const credentialCoordinator = new CredentialOperationCoordinator({
  authSecret: settingsSecret,
  coordination,
  pool: runtimePool,
});
const settings = authTestSettings({
  databaseUrl: authRuntimeDatabaseUrl,
  secret: settingsSecret,
});
const fixedNow = new Date("2026-08-28T01:02:03.000Z");
const invitationAdmission = new InvitationAdmission();
const lifecycle: AuthLifecycleDependencies = {
  backgroundTask(promise) {
    void promise.catch(() => undefined);
  },
  invitationAdmission,
  async isResearcherActive(userId) {
    const result = await runtimePool.query<{ active: boolean }>(
      'SELECT active FROM auth."user" WHERE id = $1',
      [userId],
    );
    return result.rows[0]?.active === true;
  },
  recordPasswordResetCredential:
    credentialCoordinator.recordPasswordResetCredential,
  recordSession: credentialCoordinator.recordSession,
  async sendResetPassword() {},
};

describe.sequential("Researcher Invitation lifecycle", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    await owner.query(`
      TRUNCATE
        auth.auth_secret_contract,
        auth.security_audit,
        auth.password_reset,
        auth.researcher_invitation,
        auth."rateLimit",
        auth."user"
      CASCADE
    `);
  });

  afterAll(async () => {
    await coordinationPool.end();
    await runtimePool.end();
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("delivers a 48-hour canonical single-email Invitation without persisting its token", async () => {
    const harness = serviceHarness();

    const result = await harness.service.issue("  Researcher.Label@Example.COM  ");
    const email = harness.sent[0];
    const token = email === undefined ? "" : invitationToken(email);
    const stored = await owner.query<{
      delivered_at: Date;
      email: string;
      expires_at: Date;
      status: string;
      token_hash: Buffer;
    }>(`
      SELECT delivered_at, email, expires_at, status, token_hash
      FROM auth.researcher_invitation
    `);
    const audit = await owner.query<{
      event: string;
      outcome: string;
      researcher_id: string | null;
      unknown_email_hmac: Buffer;
    }>(`
      SELECT event, outcome, researcher_id, unknown_email_hmac
      FROM auth.security_audit
    `);

    expect(result).toEqual({
      email: "researcher.label@example.com",
      invitationId: "00000000-0000-4000-8000-000000000001",
      status: "delivered",
    });
    expect(JSON.stringify(result)).not.toContain(token);
    expect(harness.sent).toHaveLength(1);
    expect(email?.to).toBe("researcher.label@example.com");
    expect(email?.html).toContain("/accept-invitation#token=");
    expect(token).not.toContain("researcher.label@example.com");
    expect(stored.rows).toEqual([
      {
        delivered_at: fixedNow,
        email: "researcher.label@example.com",
        expires_at: new Date("2026-08-30T01:02:03.000Z"),
        status: "delivered",
        token_hash: sha256(token),
      },
    ]);
    expect(audit.rows).toEqual([
      {
        event: "invitation_issued",
        outcome: "succeeded",
        researcher_id: null,
        unknown_email_hmac: unknownEmailHmac(
          settings.secret,
          "researcher.label@example.com",
        ),
      },
    ]);
    await expect(harness.service.inspect(token)).resolves.toEqual({
      email: "researcher.label@example.com",
    });
  });

  it("creates exactly one verified User and Session, then reconciles replay", async () => {
    const harness = serviceHarness();
    await harness.service.issue("researcher@example.com");
    const token = invitationToken(harness.sent[0]);

    const accepted = await harness.service.accept(
      token,
      "correct-horse-battery-staple",
      requestHeaders(),
    );
    const firstCounts = await accountCounts();
    const user = await owner.query<{
      active: boolean;
      email: string;
      emailVerified: boolean;
      name: string;
    }>('SELECT active, email, "emailVerified", name FROM auth."user"');
    const invitation = await owner.query<{
      status: string;
      terminal_at: Date;
      user_id: string;
    }>(
      "SELECT status, terminal_at, user_id FROM auth.researcher_invitation",
    );

    expect(accepted).toEqual({ setCookies: [expect.stringContaining("session_token=")] });
    expect(JSON.stringify(accepted)).not.toContain("correct-horse-battery-staple");
    expect(firstCounts).toEqual({ accounts: 1, sessions: 1, users: 1 });
    expect(user.rows).toEqual([
      {
        active: true,
        email: "researcher@example.com",
        emailVerified: true,
        name: "researcher",
      },
    ]);
    expect(invitation.rows).toEqual([
      {
        status: "consumed",
        terminal_at: fixedNow,
        user_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
      },
    ]);

    await expect(
      harness.service.accept(
        token,
        "correct-horse-battery-staple",
        requestHeaders(),
      ),
    ).resolves.toEqual({ setCookies: [expect.stringContaining("session_token=")] });
    await expect(
      harness.service.accept(token, "wrong-password-still-long", requestHeaders()),
    ).rejects.toEqual(new InvitationRejectedError());
    expect(await accountCounts()).toEqual({ accounts: 1, sessions: 2, users: 1 });
  });

  it("serializes two accepting tabs into one User and consumed Invitation", async () => {
    const harness = serviceHarness();
    await harness.service.issue("concurrent@example.com");
    const token = invitationToken(harness.sent[0]);

    const attempts = await Promise.all([
      harness.service.accept(
        token,
        "correct-horse-battery-staple",
        requestHeaders(),
      ),
      harness.service.accept(
        token,
        "correct-horse-battery-staple",
        requestHeaders(),
      ),
    ]);

    expect(attempts).toHaveLength(2);
    expect(await accountCounts()).toEqual({ accounts: 1, sessions: 2, users: 1 });
    expect(
      await owner.query<{ status: string }>(
        "SELECT status FROM auth.researcher_invitation",
      ),
    ).toMatchObject({ rows: [{ status: "consumed" }] });
  });

  it("returns one HTTP 429 for six concurrent password attempts", async () => {
    const harness = serviceHarness();
    await harness.service.issue("limited@example.com");
    const token = invitationToken(harness.sent[0]);
    await harness.service.accept(
      token,
      "correct-horse-battery-staple",
      requestHeaders(),
    );
    const limiter = new AuthEndpointRateLimiter({
      authSecret: settings.secret,
      clock: () => fixedNow,
      pool: runtimePool,
      scope: "researcher-invitation",
    });
    const app = createAuthApp({
      acceptInvitation: (candidate, password, headers) =>
        harness.service.accept(candidate, password, headers),
      authHandler: (request) => harness.auth.handler(request),
      async confirmOperatorProof() {
        throw new Error("OPERATOR_PROOF_UNAVAILABLE_IN_INVITATION_HARNESS");
      },
      async consumeOperatorProof() {
        throw new Error("OPERATOR_PROOF_UNAVAILABLE_IN_INVITATION_HARNESS");
      },
      consumeInvitationRateLimit: (candidate, headers) =>
        limiter.consume(candidate, headers),
      async consumeOperatorProofRateLimit() {
        return { allowed: true, retryAfterSeconds: 0 };
      },

      getSession: (input) => harness.auth.api.getSession(input),
      async hasOperatorCapability() {
        return false;
      },
      inspectInvitation: (candidate) => harness.service.inspect(candidate),
      async issueOperatorInvitation() {
        throw new Error("OPERATOR_MUTATION_UNAVAILABLE_IN_INVITATION_HARNESS");
      },
      async listOperatorInvitations() {
        throw new Error("OPERATOR_DIRECTORY_UNAVAILABLE_IN_INVITATION_HARNESS");
      },
      async listOperatorResearchers() {
        throw new Error("OPERATOR_DIRECTORY_UNAVAILABLE_IN_INVITATION_HARNESS");
      },
      async issueMcpAccessToken() {
        throw new Error("MCP_TOKEN_NOT_USED_IN_INVITATION_TEST");
      },
      publicOrigin: settings.publicOrigin,
      readiness: async () => true,
      async reissueOperatorInvitation() {
        throw new Error("OPERATOR_MUTATION_UNAVAILABLE_IN_INVITATION_HARNESS");
      },
      async revokeOperatorResearcherSessions() {
        throw new Error("OPERATOR_MUTATION_UNAVAILABLE_IN_INVITATION_HARNESS");
      },

    });

    const responses = await Promise.all(
      Array.from({ length: 6 }, () =>
        app.request(
          `${settings.publicOrigin}/api/auth/researcher-invitation/accept`,
          {
            body: JSON.stringify({
              password: "wrong-password-still-long",
              token,
            }),
            headers: {
              "content-type": "application/json",
              origin: settings.publicOrigin,
              "x-thesistrace-client-ip": "192.0.2.91",
            },
            method: "POST",
          },
        ),
      ),
    );

    expect(responses.map((response) => response.status).sort()).toEqual([
      400,
      400,
      400,
      400,
      400,
      429,
    ]);
  });

  it("converges ten accepts when the Better Auth Pool has one connection", async () => {
    const singleConnectionPool = new Pool({
      application_name: "thesistrace_auth_saturation_test",
      connectionString: authRuntimeDatabaseUrl,
      connectionTimeoutMillis: 500,
      max: 1,
      options: "-c search_path=auth",
      query_timeout: 3_000,
      statement_timeout: 2_500,
    });
    const singleConnectionCoordinationPool = createAuthCoordinationPool(
      authRuntimeDatabaseUrl,
    );
    const singleConnectionCredentialCoordinator =
      new CredentialOperationCoordinator({
        authSecret: settings.secret,
        coordination: new AuthOperationCoordinator(
          singleConnectionCoordinationPool,
        ),
        pool: singleConnectionPool,
      });
    const localAdmission = new InvitationAdmission();
    const auth = createThesisTraceAuth(settings, singleConnectionPool, {
      ...lifecycle,
      invitationAdmission: localAdmission,
      async isResearcherActive(userId) {
        const result = await singleConnectionPool.query<{ active: boolean }>(
          'SELECT active FROM auth."user" WHERE id = $1',
          [userId],
        );
        return result.rows[0]?.active === true;
      },
    });
    const sent: ResendEmail[] = [];
    const service = new ResearcherInvitationService({
      auth,
      authSecret: settings.secret,
      clock: () => fixedNow,
      credentialCoordinator: singleConnectionCredentialCoordinator,
      createId: () => "00000000-0000-4000-8000-000000000099",
      invitationAdmission: localAdmission,
      pool: singleConnectionPool,
      publicOrigin: settings.publicOrigin,
      randomBytes: () => Buffer.alloc(32, 99),
      async sendEmail(email) {
        sent.push(email);
      },
    });
    try {
      await service.issue("saturated@example.com");
      const token = invitationToken(sent[0]);

      const attempts = await Promise.all(
        Array.from({ length: 10 }, () =>
          service.accept(
            token,
            "correct-horse-battery-staple",
            requestHeaders(),
          ),
        ),
      );

      expect(attempts).toHaveLength(10);
      expect(await accountCounts()).toEqual({
        accounts: 1,
        sessions: 10,
        users: 1,
      });
    } finally {
      await singleConnectionCoordinationPool.end();
      await singleConnectionPool.end();
    }
  }, 15_000);

  it("removes a partial sign-up User so the Invitation can be retried", async () => {
    const harness = serviceHarness();
    await harness.service.issue("partial-signup@example.com");
    const token = invitationToken(harness.sent[0]);
    await owner.query(`
      CREATE FUNCTION auth.test_fail_credential_insert()
      RETURNS trigger
      LANGUAGE plpgsql
      AS $$
      BEGIN
        RAISE EXCEPTION 'injected credential insert failure';
      END;
      $$;
      CREATE TRIGGER test_fail_credential_insert
      BEFORE INSERT ON auth."account"
      FOR EACH ROW
      EXECUTE FUNCTION auth.test_fail_credential_insert()
    `);
    try {
      await expect(
        harness.service.accept(
          token,
          "correct-horse-battery-staple",
          requestHeaders(),
        ),
      ).rejects.toEqual(new InvitationServiceUnavailableError());
      expect(await accountCounts()).toEqual({ accounts: 0, sessions: 0, users: 0 });
    } finally {
      await owner.query(`
        DROP TRIGGER IF EXISTS test_fail_credential_insert ON auth."account";
        DROP FUNCTION IF EXISTS auth.test_fail_credential_insert()
      `);
    }

    await expect(
      harness.service.accept(
        token,
        "correct-horse-battery-staple",
        requestHeaders(),
      ),
    ).resolves.toEqual({ setCookies: [expect.stringContaining("session_token=")] });
    expect(await accountCounts()).toEqual({ accounts: 1, sessions: 1, users: 1 });
  });

  it("leaves a rejected Resend delivery terminal and unusable", async () => {
    const harness = serviceHarness(async () => {
      throw new Error("provider-body token-canary");
    });

    await expect(harness.service.issue("failed@example.com")).rejects.toEqual(
      new InvitationDeliveryError(),
    );
    const token = invitationToken(harness.sent[0]);

    const persisted = await owner.query<{ status: string; terminal_at: Date }>(
      "SELECT status, terminal_at FROM auth.researcher_invitation",
    );
    expect(persisted.rows).toEqual([
      { status: "delivery_failed", terminal_at: fixedNow },
    ]);
    await expect(harness.service.inspect(token)).rejects.toEqual(
      new InvitationRejectedError(),
    );
    await expect(
      harness.service.accept(
        token,
        "correct-horse-battery-staple",
        requestHeaders(),
      ),
    ).rejects.toEqual(new InvitationRejectedError());
    expect(await accountCounts()).toEqual({ accounts: 0, sessions: 0, users: 0 });
  });

  it("holds no PostgreSQL transaction or coordination connection during Resend delivery", async () => {
    let markDeliveryStarted: () => void = () => undefined;
    const deliveryStarted = new Promise<void>((resolve) => {
      markDeliveryStarted = resolve;
    });
    let releaseDelivery: () => void = () => undefined;
    const deliveryReleased = new Promise<void>((resolve) => {
      releaseDelivery = resolve;
    });
    const harness = serviceHarness(async () => {
      markDeliveryStarted();
      await deliveryReleased;
    });
    const issuing = harness.service.issue("delayed-invitation@example.com");

    try {
      await deliveryStarted;
      const activity = await owner.query<{
        active_count: string;
        transaction_count: string;
      }>(`
        SELECT
          count(*) FILTER (WHERE state <> 'idle') AS active_count,
          count(*) FILTER (WHERE xact_start IS NOT NULL) AS transaction_count
        FROM pg_catalog.pg_stat_activity
        WHERE usename = 'auth_runtime'
          AND application_name = 'thesistrace_auth_coordination'
      `);
      const invitation = await owner.query<{ status: string }>(
        "SELECT status FROM auth.researcher_invitation",
      );

      expect(activity.rows).toEqual([
        { active_count: "0", transaction_count: "0" },
      ]);
      expect(invitation.rows).toEqual([{ status: "delivery_pending" }]);
    } finally {
      releaseDelivery();
    }

    await expect(issuing).resolves.toMatchObject({ status: "delivered" });
    expect(
      await owner.query<{ status: string }>(
        "SELECT status FROM auth.researcher_invitation",
      ),
    ).toMatchObject({ rows: [{ status: "delivered" }] });
  });

  it("keeps the old grant effective until one replacement is delivered", async () => {
    let deliveryCount = 0;
    let markReplacementStarted: () => void = () => undefined;
    const replacementStarted = new Promise<void>((resolve) => {
      markReplacementStarted = resolve;
    });
    let releaseReplacement: () => void = () => undefined;
    const replacementReleased = new Promise<void>((resolve) => {
      releaseReplacement = resolve;
    });
    const harness = serviceHarness(async () => {
      deliveryCount += 1;
      if (deliveryCount === 2) {
        markReplacementStarted();
        await replacementReleased;
      }
    });
    await harness.service.issue("reissue@example.com");
    const firstToken = invitationToken(harness.sent[0]);

    await expect(harness.service.issue("reissue@example.com")).rejects.toEqual(
      new InvitationConflictError(),
    );
    const reissuing = harness.service.reissue("reissue@example.com");
    try {
      await replacementStarted;
      await expect(harness.service.inspect(firstToken)).resolves.toEqual({
        email: "reissue@example.com",
      });
      expect(
        await owner.query<{ status: string }>(
          "SELECT status FROM auth.researcher_invitation ORDER BY created_at, id",
        ),
      ).toMatchObject({
        rows: [{ status: "delivered" }, { status: "replacement_pending" }],
      });
    } finally {
      releaseReplacement();
    }

    const replacement = await reissuing;
    const secondToken = invitationToken(harness.sent[1]);
    const invitations = await owner.query<{ status: string }>(
      "SELECT status FROM auth.researcher_invitation ORDER BY created_at, id",
    );

    expect(replacement.status).toBe("delivered");
    expect(secondToken).not.toBe(firstToken);
    expect(invitations.rows).toEqual([
      { status: "revoked" },
      { status: "delivered" },
    ]);
    await expect(harness.service.inspect(firstToken)).rejects.toEqual(
      new InvitationRejectedError(),
    );
    await expect(harness.service.inspect(secondToken)).resolves.toEqual({
      email: "reissue@example.com",
    });
  });

  it("preserves the old effective Invitation when replacement delivery fails", async () => {
    let deliveryCount = 0;
    const harness = serviceHarness(async () => {
      deliveryCount += 1;
      if (deliveryCount === 2) throw new Error("replacement delivery failed");
    });
    await harness.service.issue("preserved@example.com");
    const firstToken = invitationToken(harness.sent[0]);

    await expect(harness.service.reissue("preserved@example.com")).rejects.toEqual(
      new InvitationDeliveryError(),
    );

    await expect(harness.service.inspect(firstToken)).resolves.toEqual({
      email: "preserved@example.com",
    });
    expect(
      await owner.query<{ status: string }>(
        "SELECT status FROM auth.researcher_invitation ORDER BY created_at, id",
      ),
    ).toMatchObject({
      rows: [{ status: "delivered" }, { status: "delivery_failed" }],
    });
  });

  it("hard secret rotation revokes an in-flight replacement before promotion", async () => {
    await enforceAuthSecretContract(runtimePool, settings.secret, () => fixedNow);
    let deliveryCount = 0;
    let markReplacementStarted: () => void = () => undefined;
    const replacementStarted = new Promise<void>((resolve) => {
      markReplacementStarted = resolve;
    });
    let releaseReplacement: () => void = () => undefined;
    const replacementReleased = new Promise<void>((resolve) => {
      releaseReplacement = resolve;
    });
    const harness = serviceHarness(async () => {
      deliveryCount += 1;
      if (deliveryCount === 2) {
        markReplacementStarted();
        await replacementReleased;
      }
    });
    await harness.service.issue("rotation@example.com");
    const oldToken = invitationToken(harness.sent[0]);
    const reissuing = harness.service.reissue("rotation@example.com");
    try {
      await replacementStarted;
      await expect(
        enforceAuthSecretContract(
          runtimePool,
          "abcdef0123456789abcdef0123456789",
          () => new Date("2026-08-28T01:03:03.000Z"),
        ),
      ).resolves.toEqual({ status: "rotated" });
    } finally {
      releaseReplacement();
    }

    await expect(reissuing).rejects.toEqual(new InvitationDeliveryError());
    const replacementToken = invitationToken(harness.sent[1]);
    await expect(harness.service.inspect(oldToken)).rejects.toEqual(
      new InvitationRejectedError(),
    );
    await expect(harness.service.inspect(replacementToken)).rejects.toEqual(
      new InvitationRejectedError(),
    );
    expect(
      await owner.query<{ status: string }>(
        "SELECT status FROM auth.researcher_invitation ORDER BY created_at, id",
      ),
    ).toMatchObject({
      rows: [{ status: "revoked" }, { status: "revoked" }],
    });
  });

  it("does not reissue after a concurrent accept creates the User", async () => {
    const harness = serviceHarness();
    await harness.service.issue("accept-reissue@example.com");
    const token = invitationToken(harness.sent[0]);
    const blocker = await owner.connect();
    let accepting: Promise<Readonly<{ setCookies: string[] }>> | undefined;
    try {
      await blocker.query("BEGIN");
      await blocker.query('LOCK TABLE auth."user" IN ACCESS EXCLUSIVE MODE');
      accepting = harness.service.accept(
        token,
        "correct-horse-battery-staple",
        requestHeaders(),
      );
      await waitForCondition(async () => {
        const result = await owner.query<{ waiting: boolean }>(`
          SELECT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_stat_activity
            WHERE application_name = 'thesistrace_auth_coordination'
              AND wait_event_type = 'Lock'
          ) AS waiting
        `);
        return result.rows[0]?.waiting === true;
      });
      const reissuing = harness.service.reissue("accept-reissue@example.com");
      await blocker.query("COMMIT");

      await expect(accepting).resolves.toEqual({
        setCookies: [expect.stringContaining("session_token=")],
      });
      await expect(reissuing).rejects.toEqual(new InvitationConflictError());
      expect(harness.sent).toHaveLength(1);
      expect(
        await owner.query<{ status: string }>(
          "SELECT status FROM auth.researcher_invitation",
        ),
      ).toMatchObject({ rows: [{ status: "consumed" }] });
    } finally {
      await blocker.query("ROLLBACK").catch(() => undefined);
      blocker.release();
      await accepting?.catch(() => undefined);
    }
  });

  it("destroys a coordination connection when advisory unlock is uncertain", async () => {
    const uncertainPool = createAuthCoordinationPool(authRuntimeDatabaseUrl);
    const contenderPool = createAuthCoordinationPool(authRuntimeDatabaseUrl);
    const originalConnect = uncertainPool.connect.bind(uncertainPool);
    uncertainPool.connect = (async () => {
      const client = await originalConnect();
      const originalQuery = client.query.bind(client);
      client.query = ((query: unknown, ...values: unknown[]) => {
        if (
          typeof query === "string" &&
          query.includes("pg_catalog.pg_advisory_unlock(")
        ) {
          return Promise.resolve({
            command: "SELECT",
            fields: [],
            oid: 0,
            rowCount: 1,
            rows: [{ unlocked: false }],
          });
        }
        return originalQuery(query as never, ...(values as never[]));
      }) as typeof client.query;
      return client;
    }) as typeof uncertainPool.connect;
    const email = "uncertain-unlock@example.com";
    const lockKey = credentialLockKey(email);
    const contender = await contenderPool.connect();
    try {
      await expect(
        new AuthOperationCoordinator(uncertainPool).run(
          ["coordination-progress-regression"],
          async () => undefined,
        ),
      ).rejects.toMatchObject({
        operationCompleted: true,
        operationStarted: true,
      });
      const harness = serviceHarness(async () => undefined, uncertainPool);
      await invitationAdmission.run(email, () =>
        directSignUp(
          harness.auth,
          email,
          "correct-horse-battery-staple",
        ),
      );
      expect(await accountCounts()).toEqual({
        accounts: 1,
        sessions: 1,
        users: 1,
      });

      await expect(harness.service.issue(email)).rejects.toThrow(
        "AUTH_COORDINATION_UNAVAILABLE",
      );

      expect(await accountCounts()).toEqual({
        accounts: 1,
        sessions: 1,
        users: 1,
      });
      expect(
        await owner.query(
          "SELECT 1 FROM auth.security_audit WHERE event = 'sessions_revoked'",
        ),
      ).toMatchObject({ rowCount: 0 });

      let acquired = false;
      await waitForCondition(async () => {
        const result = await contender.query<{ acquired: boolean }>(
          `
            SELECT pg_catalog.pg_try_advisory_lock(
              pg_catalog.hashtextextended($1, 0)
            ) AS acquired
          `,
          [lockKey],
        );
        acquired = result.rows[0]?.acquired === true;
        return acquired;
      });
      expect(acquired).toBe(true);
      if (acquired) {
        await contender.query(
          "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended($1, 0))",
          [lockKey],
        );
      }
    } finally {
      contender.release();
      await Promise.allSettled([uncertainPool.end(), contenderPool.end()]);
    }
  });

  it("keeps an existing Session when Invitation issue cannot acquire coordination", async () => {
    const unavailablePool = createAuthCoordinationPool(authRuntimeDatabaseUrl);
    const originalConnect = unavailablePool.connect.bind(unavailablePool);
    unavailablePool.connect = (async () => {
      const client = await originalConnect();
      const originalQuery = client.query.bind(client);
      client.query = ((query: unknown, ...values: unknown[]) => {
        if (
          typeof query === "string" &&
          query.includes("pg_catalog.pg_advisory_lock(")
        ) {
          return Promise.reject(new Error("injected coordination failure"));
        }
        return originalQuery(query as never, ...(values as never[]));
      }) as typeof client.query;
      return client;
    }) as typeof unavailablePool.connect;
    const email = "unavailable-issue@example.com";
    try {
      const harness = serviceHarness(async () => undefined, unavailablePool);
      await invitationAdmission.run(email, () =>
        directSignUp(
          harness.auth,
          email,
          "correct-horse-battery-staple",
        ),
      );

      await expect(harness.service.issue(email)).rejects.toThrow(
        "AUTH_COORDINATION_UNAVAILABLE",
      );

      expect(await accountCounts()).toEqual({
        accounts: 1,
        sessions: 1,
        users: 1,
      });
      expect(
        await owner.query(
          "SELECT 1 FROM auth.security_audit WHERE event = 'sessions_revoked'",
        ),
      ).toMatchObject({ rowCount: 0 });
    } finally {
      await unavailablePool.end();
    }
  });

  it("rejects direct Better Auth signup and refuses to invite an existing User", async () => {
    const harness = serviceHarness();
    const directResponse = await directSignUp(
      harness.auth,
      "bypass@example.com",
      "correct-horse-battery-staple",
    );

    expect(directResponse.status).toBe(400);
    expect(await accountCounts()).toEqual({ accounts: 0, sessions: 0, users: 0 });

    await harness.service.issue("existing@example.com");
    const token = invitationToken(harness.sent[0]);
    await harness.service.accept(
      token,
      "correct-horse-battery-staple",
      requestHeaders(),
    );
    await expect(harness.service.issue("existing@example.com")).rejects.toEqual(
      new InvitationConflictError(),
    );
    expect(await accountCounts()).toEqual({ accounts: 1, sessions: 1, users: 1 });
  });

  it("reconciles a User created before Invitation consumption only with the same password", async () => {
    const harness = serviceHarness();
    await harness.service.issue("lost-response@example.com");
    const token = invitationToken(harness.sent[0]);
    const signup = await invitationAdmission.run("lost-response@example.com", () =>
      directSignUp(
        harness.auth,
        "lost-response@example.com",
        "correct-horse-battery-staple",
      ),
    );
    expect(signup.status).toBe(200);

    await expect(
      harness.service.accept(token, "wrong-password-still-long", requestHeaders()),
    ).rejects.toEqual(new InvitationRejectedError());
    expect(
      await owner.query<{ status: string }>(
        "SELECT status FROM auth.researcher_invitation",
      ),
    ).toMatchObject({ rows: [{ status: "delivered" }] });

    await expect(
      harness.service.accept(
        token,
        "correct-horse-battery-staple",
        requestHeaders(),
      ),
    ).resolves.toEqual({ setCookies: [expect.stringContaining("session_token=")] });
    expect(await accountCounts()).toEqual({ accounts: 1, sessions: 2, users: 1 });
  });

  it("rejects expired and hash-mismatched tokens without changing Product state", async () => {
    const harness = serviceHarness();
    await harness.service.issue("expired@example.com");
    const token = invitationToken(harness.sent[0]);
    await owner.query(
      "UPDATE auth.researcher_invitation SET expires_at = $1",
      [new Date("2026-08-28T01:02:02.000Z")],
    );

    await expect(harness.service.inspect(token)).rejects.toEqual(
      new InvitationRejectedError(),
    );
    await expect(
      harness.service.accept(
        `${token.slice(0, -1)}${token.endsWith("a") ? "b" : "a"}`,
        "correct-horse-battery-staple",
        requestHeaders(),
      ),
    ).rejects.toEqual(new InvitationRejectedError());
    expect(await accountCounts()).toEqual({ accounts: 0, sessions: 0, users: 0 });
  });
});

function serviceHarness(
  delivery: (email: ResendEmail) => Promise<void> = async () => undefined,
  selectedCoordinationPool = coordinationPool,
) {
  const sent: ResendEmail[] = [];
  let nextId = 1;
  const auth = createThesisTraceAuth(settings, runtimePool, lifecycle);
  const selectedCredentialCoordinator =
    selectedCoordinationPool === coordinationPool
      ? credentialCoordinator
      : new CredentialOperationCoordinator({
          authSecret: settings.secret,
          coordination: new AuthOperationCoordinator(selectedCoordinationPool),
          pool: runtimePool,
        });
  const service = new ResearcherInvitationService({
    auth,
    authSecret: settings.secret,
    clock: () => fixedNow,
    createId: () =>
      `00000000-0000-4000-8000-${String(nextId++).padStart(12, "0")}`,
    invitationAdmission,
    credentialCoordinator: selectedCredentialCoordinator,
    pool: runtimePool,
    publicOrigin: settings.publicOrigin,
    randomBytes: () => Buffer.alloc(32, nextId),
    async sendEmail(email) {
      sent.push(email);
      await delivery(email);
    },
  });
  return { auth, sent, service };
}

async function directSignUp(
  auth: ReturnType<typeof createThesisTraceAuth>,
  email: string,
  password: string,
): Promise<Response> {
  return auth.api.signUpEmail({
    asResponse: true,
    body: { email, name: "untrusted", password },
    headers: requestHeaders(),
  });
}

function invitationToken(email: ResendEmail | undefined): string {
  const match = email?.html.match(/#token=([^"'<\s]+)/);
  if (match?.[1] === undefined) {
    throw new Error("expected an Invitation fragment token");
  }
  return decodeURIComponent(match[1]);
}

function requestHeaders(): Headers {
  return new Headers({
    origin: settings.publicOrigin,
    "x-thesistrace-client-ip": "192.0.2.10",
  });
}

async function accountCounts(): Promise<{
  accounts: number;
  sessions: number;
  users: number;
}> {
  const result = await owner.query<{
    accounts: string;
    sessions: string;
    users: string;
  }>(`
    SELECT
      (SELECT count(*) FROM auth."account") AS accounts,
      (SELECT count(*) FROM auth."session") AS sessions,
      (SELECT count(*) FROM auth."user") AS users
  `);
  const row = result.rows[0];
  if (row === undefined) {
    throw new Error("expected aggregate counts");
  }
  return {
    accounts: Number(row.accounts),
    sessions: Number(row.sessions),
    users: Number(row.users),
  };
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}

async function waitForCondition(
  condition: () => Promise<boolean>,
  timeoutMilliseconds = 2_000,
): Promise<void> {
  const deadline = performance.now() + timeoutMilliseconds;
  while (!(await condition())) {
    if (performance.now() >= deadline) {
      throw new Error("condition was not reached before its deadline");
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  }
}
