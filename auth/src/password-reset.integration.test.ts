import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { createAuthApp } from "./app.js";
import {
  createThesisTraceAuth,
  type AuthLifecycleDependencies,
} from "./auth.js";
import { AuthBackgroundTasks } from "./background-tasks.js";
import { AuthEndpointRateLimiter } from "./auth-rate-limit.js";
import type { AuthSettings } from "./config.js";
import {
  AuthOperationCoordinator,
  CredentialOperationCoordinator,
} from "./coordination.js";
import { createAuthCoordinationPool, createAuthPool } from "./database.js";
import { InvitationRejectedError } from "./invitation.js";
import { InvitationAdmission } from "./invitation-admission.js";
import { PasswordResetLifecycle } from "./password-reset.js";
import { passwordResetIdentifier } from "./password-reset-token.js";
import type { ResendEmail } from "./resend.js";
import { initializeAuthSchema } from "./schema-initialize.js";
import { sha256 } from "./security.js";

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
const settings: AuthSettings = {
  databaseUrl: authRuntimeDatabaseUrl,
  environment: "test",
  host: "127.0.0.1",
  port: 8200,
  publicOrigin: "http://127.0.0.1:5173",
  resendApiKey: "test-resend-key",
  resendApiUrl: "http://127.0.0.1:8300",
  resendFromEmail: "ThesisTrace <noreply@thesistrace.test>",
  secret: "0123456789abcdef0123456789abcdef",
  secureCookies: false,
};
const fixedNow = new Date("2026-08-28T05:00:00.000Z");
const coordination = new AuthOperationCoordinator(coordinationPool);
const credentialCoordinator = createCredentialCoordinator();

describe.sequential("Password Reset lifecycle", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    await owner.query(`
      TRUNCATE
        auth.security_audit,
        auth.password_reset,
        auth.researcher_invitation,
        auth."rateLimit",
        auth."verification",
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

  it("returns the same response for known and unknown email while delivering a fragment link", async () => {
    const harness = resetHarness();
    await createUser(harness, "known@example.com");

    const known = await requestReset(harness, "known@example.com");
    await harness.tasks.drain();
    const unknown = await requestReset(harness, "unknown@example.com");
    await harness.tasks.drain();
    const email = harness.sent[0];
    const token = resetToken(email);
    const reset = await owner.query<{
      delivered_at: Date;
      expires_at: Date;
      status: string;
      token_hash: Buffer;
    }>(`
      SELECT delivered_at, expires_at, status, token_hash
      FROM auth.password_reset
    `);
    const verification = await owner.query<{ identifier: string }>(`
      SELECT identifier
      FROM auth."verification"
      WHERE identifier LIKE 'reset-password:%'
    `);

    expect(known.status).toBe(200);
    expect(unknown.status).toBe(200);
    expect(await known.json()).toEqual(await unknown.json());
    expect(harness.sent).toHaveLength(1);
    expect(email?.to).toBe("known@example.com");
    expect(email?.html).toContain("/reset-password#token=");
    expect(email?.html).not.toContain("/api/auth/reset-password/");
    expect(reset.rows).toEqual([
      {
        delivered_at: fixedNow,
        expires_at: new Date("2026-08-28T05:30:00.000Z"),
        status: "delivered",
        token_hash: sha256(token),
      },
    ]);
    expect(verification.rows).toEqual([
      { identifier: `reset-password:${sha256(token).toString("hex")}` },
    ]);
    expect(JSON.stringify(verification.rows)).not.toContain(token);
  });

  it("sends nothing and removes the Better Auth token for an inactive Researcher", async () => {
    const harness = resetHarness();
    await createUser(harness, "inactive@example.com");
    await owner.query('UPDATE auth."user" SET active = FALSE');

    const response = await requestReset(harness, "inactive@example.com");
    await harness.tasks.drain();
    const verification = await owner.query<{ count: string }>(
      `SELECT count(*) FROM auth.verification WHERE identifier LIKE 'reset-password:%'`,
    );

    expect(response.status).toBe(200);
    expect(harness.sent).toEqual([]);
    expect(verification.rows).toEqual([{ count: "0" }]);
    expect(
      await owner.query<{ count: string }>("SELECT count(*) FROM auth.password_reset"),
    ).toMatchObject({ rows: [{ count: "0" }] });
  });

  it("makes a rejected Resend delivery terminal and unusable", async () => {
    const harness = resetHarness(async () => {
      throw new Error("provider-body token-canary");
    });
    await createUser(harness, "failed@example.com");

    const response = await requestReset(harness, "failed@example.com");
    await harness.tasks.drain();
    const reset = await owner.query<{ status: string; terminal_at: Date }>(
      "SELECT status, terminal_at FROM auth.password_reset",
    );
    const verification = await owner.query<{ count: string }>(
      `SELECT count(*) FROM auth.verification WHERE identifier LIKE 'reset-password:%'`,
    );

    expect(response.status).toBe(200);
    expect(reset.rows).toEqual([
      { status: "delivery_failed", terminal_at: fixedNow },
    ]);
    expect(verification.rows).toEqual([{ count: "0" }]);
  });

  it("does not exhaust credential coordination while two Resend deliveries are pending", async () => {
    let startedCount = 0;
    let markDeliveriesStarted: () => void = () => undefined;
    const deliveriesStarted = new Promise<void>((resolve) => {
      markDeliveriesStarted = resolve;
    });
    let releaseDelivery: () => void = () => undefined;
    const deliveryReleased = new Promise<void>((resolve) => {
      releaseDelivery = resolve;
    });
    const harness = resetHarness(async () => {
      startedCount += 1;
      if (startedCount === 2) {
        markDeliveriesStarted();
      }
      await deliveryReleased;
    });
    await createUser(harness, "delayed-a@example.com");
    await createUser(harness, "delayed-b@example.com");
    await createUser(harness, "available@example.com");

    try {
      const responses = await Promise.all([
        requestReset(harness, "delayed-a@example.com"),
        requestReset(harness, "delayed-b@example.com"),
      ]);
      await deliveriesStarted;
      const activity = await owner.query<{
        coordination_transaction_count: string;
        runtime_transaction_count: string;
      }>(`
        SELECT
          count(*) FILTER (
            WHERE application_name = 'thesistrace_auth_coordination'
              AND xact_start IS NOT NULL
          ) AS coordination_transaction_count,
          count(*) FILTER (
            WHERE application_name = 'thesistrace_auth'
              AND xact_start IS NOT NULL
          ) AS runtime_transaction_count
        FROM pg_catalog.pg_stat_activity
        WHERE usename = 'auth_runtime'
      `);
      const resets = await owner.query<{ status: string }>(`
        SELECT status FROM auth.password_reset ORDER BY id
      `);
      const signInResponse = await publicSignIn(
        harness,
        "available@example.com",
        "correct-horse-battery-staple",
      );

      expect(responses.map((response) => response.status)).toEqual([200, 200]);
      expect(activity.rows).toEqual([
        {
          coordination_transaction_count: "0",
          runtime_transaction_count: "0",
        },
      ]);
      expect(resets.rows).toEqual([
        { status: "delivery_pending" },
        { status: "delivery_pending" },
      ]);
      expect(signInResponse.status).toBe(200);
    } finally {
      releaseDelivery();
    }
    await harness.tasks.drain();
    expect(
      await owner.query<{ status: string }>(
        "SELECT status FROM auth.password_reset ORDER BY id",
      ),
    ).toMatchObject({
      rows: [{ status: "delivered" }, { status: "delivered" }],
    });
  });

  it("delivers only a Reset whose verification survives concurrent requests", async () => {
    const harness = resetHarness();
    await createUser(harness, "concurrent-reset@example.com");
    const user = await owner.query<{ email: string; id: string; name: string }>(
      'SELECT email, id, name FROM auth."user" WHERE email = $1',
      ["concurrent-reset@example.com"],
    );
    const researcher = user.rows[0];
    if (researcher === undefined) {
      throw new Error("expected a concurrent Reset Researcher");
    }
    const tokens = ["concurrent-reset-token-a", "concurrent-reset-token-b"] as const;
    for (const token of tokens) {
      await owner.query(
        `
          INSERT INTO auth."verification" (
            "identifier",
            "value",
            "expiresAt"
          )
          VALUES ($1, $2, $3)
        `,
        [
          passwordResetIdentifier(token),
          researcher.id,
          new Date(fixedNow.getTime() + 30 * 60 * 1_000),
        ],
      );
    }

    await Promise.all(
      tokens.map((token) =>
        harness.reset.sendResetPassword({
          token,
          url: `${settings.publicOrigin}/api/auth/reset-password/${token}`,
          user: researcher,
        }),
      ),
    );

    expect(harness.sent).toHaveLength(1);
    const deliveredToken = resetToken(harness.sent[0]);
    expect(tokens).toContain(deliveredToken as (typeof tokens)[number]);
    expect(
      await owner.query<{ identifier: string }>(
        `
          SELECT identifier
          FROM auth."verification"
          WHERE value = $1 AND identifier LIKE 'reset-password:%'
        `,
        [researcher.id],
      ),
    ).toMatchObject({
      rows: [{ identifier: passwordResetIdentifier(deliveredToken) }],
    });
    expect(
      await owner.query<{ status: string }>(
        "SELECT status FROM auth.password_reset",
      ),
    ).toMatchObject({ rows: [{ status: "delivered" }] });
  });

  it("resets the password, consumes its lifecycle row, and revokes every Session", async () => {
    const harness = resetHarness();
    await createUser(harness, "reset@example.com");
    await signIn(harness, "reset@example.com", "correct-horse-battery-staple");
    expect(await sessionCount()).toBe(2);
    await requestReset(harness, "reset@example.com");
    await harness.tasks.drain();
    const token = resetToken(harness.sent[0]);

    const response = await harness.app.request(
      `${settings.publicOrigin}/api/auth/reset-password`,
      {
        body: JSON.stringify({
          newPassword: "new-correct-horse-battery-staple",
          token,
        }),
        headers: {
          "content-type": "application/json",
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(200);
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(await sessionCount()).toBe(0);
    expect(
      await owner.query<{ status: string; terminal_at: Date }>(
        "SELECT status, terminal_at FROM auth.password_reset",
      ),
    ).toMatchObject({
      rows: [{ status: "consumed", terminal_at: fixedNow }],
    });
    expect(
      (
        await signIn(
          harness,
          "reset@example.com",
          "correct-horse-battery-staple",
        )
      ).status,
    ).not.toBe(200);
    expect(
      (
        await signIn(
          harness,
          "reset@example.com",
          "new-correct-horse-battery-staple",
        )
      ).status,
    ).toBe(200);
    expect((await resetPassword(harness, token)).status).toBe(400);
    await harness.tasks.drain();
    expect(
      await owner.query<{ event: string; outcome: string }>(
        `
          SELECT event, outcome
          FROM auth.security_audit
          WHERE event IN ('password_reset_succeeded', 'password_reset_failed')
          ORDER BY event DESC
        `,
      ),
    ).toMatchObject({
      rows: [
        { event: "password_reset_succeeded", outcome: "succeeded" },
        { event: "password_reset_failed", outcome: "failed" },
      ],
    });
  });

  it("revokes a Session whose old-password sign-in overlaps a successful Reset", async () => {
    const harness = resetHarness(
      undefined,
      undefined,
      { request: createCredentialCoordinator() },
    );
    await createUser(harness, "linearized@example.com");
    await owner.query('DELETE FROM auth."session"');
    await requestReset(harness, "linearized@example.com");
    await harness.tasks.drain();
    const token = resetToken(harness.sent[0]);
    const blocker = await owner.connect();
    const insertHoldKey = "password-reset-sign-in-insert-hold";
    let signInPromise: Promise<Response> | undefined;
    let resetPromise: Promise<Response> | undefined;
    try {
      await blocker.query(
        "SELECT pg_catalog.pg_advisory_lock(pg_catalog.hashtextextended($1, 0))",
        [insertHoldKey],
      );
      await owner.query(`
        CREATE FUNCTION auth.test_hold_session_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
          PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended('${insertHoldKey}', 0)
          );
          RETURN NEW;
        END;
        $function$;
        CREATE TRIGGER test_hold_session_insert
        BEFORE INSERT ON auth."session"
        FOR EACH ROW
        EXECUTE FUNCTION auth.test_hold_session_insert()
      `);

      signInPromise = publicSignIn(
        harness,
        "linearized@example.com",
        "correct-horse-battery-staple",
      );
      await waitForCondition(async () =>
        hasAdvisoryWaiter("thesistrace_auth"),
      );
      resetPromise = resetPassword(harness, token);
      await waitForCondition(async () =>
        hasAdvisoryWaiter("thesistrace_auth_coordination"),
      );

      await blocker.query(
        "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended($1, 0))",
        [insertHoldKey],
      );
      const [signInResponse, resetResponse] = await Promise.all([
        signInPromise,
        resetPromise,
      ]);
      const cookie = signInResponse.headers.get("set-cookie") ?? "";
      const session = await harness.auth.api.getSession({
        headers: new Headers({ cookie }),
        query: { disableCookieCache: true, disableRefresh: true },
      });

      expect(signInResponse.status).toBe(200);
      expect(resetResponse.status).toBe(200);
      expect(session).toBeNull();
      expect(await sessionCount()).toBe(0);
      expect(
        (
          await signIn(
            harness,
            "linearized@example.com",
            "correct-horse-battery-staple",
          )
        ).status,
      ).not.toBe(200);
    } finally {
      await blocker
        .query(
          "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended($1, 0))",
          [insertHoldKey],
        )
        .catch(() => undefined);
      blocker.release();
      await Promise.allSettled([
        signInPromise ?? Promise.resolve(),
        resetPromise ?? Promise.resolve(),
      ]);
      await owner.query(
        "DROP TRIGGER IF EXISTS test_hold_session_insert ON auth.\"session\"; DROP FUNCTION IF EXISTS auth.test_hold_session_insert()",
      );
    }
  });

  it("removes a Session if its checked-out credential lock connection disconnects", async () => {
    const harness = resetHarness(
      undefined,
      undefined,
      { request: createCredentialCoordinator() },
    );
    await createUser(harness, "coordination-loss@example.com");
    await owner.query('DELETE FROM auth."session"');
    const blocker = await owner.connect();
    const insertHoldKey = "coordination-loss-session-insert-hold";
    let signInPromise: Promise<Response> | undefined;
    try {
      await blocker.query(
        "SELECT pg_catalog.pg_advisory_lock(pg_catalog.hashtextextended($1, 0))",
        [insertHoldKey],
      );
      await owner.query(`
        CREATE FUNCTION auth.test_hold_coordination_loss_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
          PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended('${insertHoldKey}', 0)
          );
          RETURN NEW;
        END;
        $function$;
        CREATE TRIGGER test_hold_coordination_loss_insert
        BEFORE INSERT ON auth."session"
        FOR EACH ROW
        EXECUTE FUNCTION auth.test_hold_coordination_loss_insert()
      `);

      signInPromise = publicSignIn(
        harness,
        "coordination-loss@example.com",
        "correct-horse-battery-staple",
      );
      await waitForCondition(async () =>
        hasAdvisoryWaiter("thesistrace_auth"),
      );
      const terminated = await owner.query<{ terminated: boolean }>(`
        SELECT pg_catalog.pg_terminate_backend(activity.pid) AS terminated
        FROM pg_catalog.pg_stat_activity AS activity
        WHERE activity.application_name = 'thesistrace_auth_coordination'
          AND activity.usename = 'auth_runtime'
          AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_locks AS held
            WHERE held.pid = activity.pid
              AND held.locktype = 'advisory'
              AND held.granted
          )
        ORDER BY activity.backend_start DESC
        LIMIT 1
      `);
      expect(terminated.rows).toEqual([{ terminated: true }]);
      await blocker.query(
        "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended($1, 0))",
        [insertHoldKey],
      );

      const response = await signInPromise;

      expect(response.status).toBe(503);
      expect(await sessionCount()).toBe(0);
    } finally {
      await blocker
        .query(
          "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended($1, 0))",
          [insertHoldKey],
        )
        .catch(() => undefined);
      blocker.release();
      await signInPromise?.catch(() => undefined);
      await owner.query(`
        DROP TRIGGER IF EXISTS test_hold_coordination_loss_insert
          ON auth."session";
        DROP FUNCTION IF EXISTS auth.test_hold_coordination_loss_insert()
      `);
    }
  });

  it("revokes and audits a completed sign-in when coordination release is uncertain", async () => {
    const uncertainPool = createAuthCoordinationPool(authRuntimeDatabaseUrl);
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
    const requestCoordinator = new CredentialOperationCoordinator({
      authSecret: settings.secret,
      coordination: new AuthOperationCoordinator(uncertainPool),
      pool: runtimePool,
    });
    try {
      const harness = resetHarness(
        undefined,
        undefined,
        { request: requestCoordinator },
      );
      await createUser(harness, "uncertain-sign-in@example.com");
      await owner.query('DELETE FROM auth."session"');

      expect(
        (
          await publicSignIn(
            harness,
            "uncertain-sign-in@example.com",
            "correct-horse-battery-staple",
          )
        ).status,
      ).toBe(503);

      expect(await sessionCount()).toBe(0);
      expect(
        await owner.query<{ event: string; outcome: string }>(
          `
            SELECT event, outcome
            FROM auth.security_audit
            WHERE event = 'sessions_revoked'
          `,
        ),
      ).toMatchObject({
        rows: [{ event: "sessions_revoked", outcome: "succeeded" }],
      });
    } finally {
      await uncertainPool.end();
    }
  });

  it("keeps existing Sessions when Reset delivery cannot acquire coordination", async () => {
    const uncertainPool = createAuthCoordinationPool(authRuntimeDatabaseUrl);
    const originalConnect = uncertainPool.connect.bind(uncertainPool);
    uncertainPool.connect = (async () => {
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
    }) as typeof uncertainPool.connect;
    const deliveryCoordinator = new CredentialOperationCoordinator({
      authSecret: settings.secret,
      coordination: new AuthOperationCoordinator(uncertainPool),
      pool: runtimePool,
    });
    try {
      const harness = resetHarness(
        undefined,
        undefined,
        { delivery: deliveryCoordinator },
      );
      await createUser(harness, "delivery-lock@example.com");
      await signIn(
        harness,
        "delivery-lock@example.com",
        "correct-horse-battery-staple",
      );
      expect(await sessionCount()).toBe(2);

      expect(
        (await requestReset(harness, "delivery-lock@example.com")).status,
      ).toBe(200);
      await harness.tasks.drain();

      expect(await sessionCount()).toBe(2);
      expect(
        await owner.query(
          "SELECT 1 FROM auth.security_audit WHERE event = 'sessions_revoked'",
        ),
      ).toMatchObject({ rowCount: 0 });
    } finally {
      await uncertainPool.end();
    }
  });

  it("admits only five concurrent Reset attempts for one IP and token", async () => {
    const limiter = new AuthEndpointRateLimiter({
      authSecret: settings.secret,
      clock: () => fixedNow,
      pool: runtimePool,
      scope: "password-reset",
    });
    const harness = resetHarness(
      async () => undefined,
      (token, headers) => limiter.consume(token, headers),
    );
    await createUser(harness, "limited-reset@example.com");
    await requestReset(harness, "limited-reset@example.com");
    await harness.tasks.drain();
    const token = resetToken(harness.sent[0]);

    const responses = await Promise.all(
      Array.from({ length: 6 }, () => resetPassword(harness, token)),
    );
    await harness.tasks.drain();

    expect(responses.map((response) => response.status).sort()).toEqual([
      200,
      400,
      400,
      400,
      400,
      429,
    ]);
    expect(
      responses.find((response) => response.status === 429)?.headers.get(
        "retry-after",
      ),
    ).toBe("60");
  });

  it("rolls back atomically when success audit persistence is unavailable", async () => {
    const harness = resetHarness();
    await createUser(harness, "audit-lock@example.com");
    await signIn(
      harness,
      "audit-lock@example.com",
      "correct-horse-battery-staple",
    );
    await requestReset(harness, "audit-lock@example.com");
    await harness.tasks.drain();
    const token = resetToken(harness.sent[0]);
    const blocker = await owner.connect();
    try {
      await blocker.query("BEGIN");
      await blocker.query("LOCK TABLE auth.security_audit IN ACCESS EXCLUSIVE MODE");

      const response = await resetPassword(harness, token);

      expect(response.status).toBe(503);
      expect(await sessionCount()).toBe(2);
      expect(
        await owner.query<{ status: string }>(
          "SELECT status FROM auth.password_reset",
        ),
      ).toMatchObject({ rows: [{ status: "delivered" }] });
      expect(
        await owner.query<{ count: string }>(
          `SELECT count(*) FROM auth."verification" WHERE identifier = $1`,
          [passwordResetIdentifier(token)],
        ),
      ).toMatchObject({ rows: [{ count: "1" }] });
    } finally {
      await blocker.query("ROLLBACK").catch(() => undefined);
      blocker.release();
    }
    expect((await resetPassword(harness, token)).status).toBe(200);
    expect(await sessionCount()).toBe(0);
  });

  it("rolls back the credential and keeps the Reset retryable when Session revocation fails", async () => {
    const harness = resetHarness();
    await createUser(harness, "session-lock@example.com");
    await signIn(
      harness,
      "session-lock@example.com",
      "correct-horse-battery-staple",
    );
    await requestReset(harness, "session-lock@example.com");
    await harness.tasks.drain();
    const token = resetToken(harness.sent[0]);
    const blocker = await owner.connect();
    let response: Response;
    try {
      await blocker.query("BEGIN");
      await blocker.query('LOCK TABLE auth."session" IN ACCESS EXCLUSIVE MODE');

      response = await resetPassword(harness, token);
    } finally {
      await blocker.query("ROLLBACK").catch(() => undefined);
      blocker.release();
    }

    expect(response.status).toBe(503);
    expect(await sessionCount()).toBe(2);
    expect(
      await owner.query<{ status: string }>(
        "SELECT status FROM auth.password_reset",
      ),
    ).toMatchObject({ rows: [{ status: "delivered" }] });
    expect(
      await owner.query<{ count: string }>(
        `SELECT count(*) FROM auth."verification" WHERE identifier = $1`,
        [passwordResetIdentifier(token)],
      ),
    ).toMatchObject({ rows: [{ count: "1" }] });
    expect(
      (
        await signIn(
          harness,
          "session-lock@example.com",
          "correct-horse-battery-staple",
        )
      ).status,
    ).toBe(200);

    expect((await resetPassword(harness, token)).status).toBe(200);
    expect(await sessionCount()).toBe(0);
  });

  it("binds a delayed lifecycle callback to its exact Reset token", async () => {
    const harness = resetHarness();
    await createUser(harness, "overlap@example.com");
    await requestReset(harness, "overlap@example.com");
    await harness.tasks.drain();
    const firstToken = resetToken(harness.sent[0]);
    await requestReset(harness, "overlap@example.com");
    await harness.tasks.drain();
    const secondToken = resetToken(harness.sent[1]);
    expect((await resetPassword(harness, firstToken)).status).toBe(400);
    expect(
      await owner.query<{ status: string }>(
        "SELECT status FROM auth.password_reset ORDER BY id",
      ),
    ).toMatchObject({ rows: [{ status: "revoked" }, { status: "delivered" }] });

    const response = await resetPassword(harness, secondToken);
    expect(response.status).toBe(200);
    expect(
      await owner.query<{ status: string }>(
        "SELECT status FROM auth.password_reset ORDER BY id",
      ),
    ).toMatchObject({ rows: [{ status: "revoked" }, { status: "consumed" }] });
  });
});

function resetHarness(
  delivery: (email: ResendEmail) => Promise<void> = async () => undefined,
  consumePasswordResetRateLimit: (
    token: string,
    headers: Headers,
  ) => Promise<Readonly<{ allowed: boolean; retryAfterSeconds: number }>> = async () => ({
    allowed: true,
    retryAfterSeconds: 0,
  }),
  coordinators: Readonly<{
    completion?: CredentialOperationCoordinator;
    delivery?: CredentialOperationCoordinator;
    request?: CredentialOperationCoordinator;
  }> = {},
) {
  const sent: ResendEmail[] = [];
  const tasks = new AuthBackgroundTasks();
  let nextId = 1;
  const reset = new PasswordResetLifecycle({
    authSecret: settings.secret,
    backgroundTask: tasks.handler,
    clock: () => fixedNow,
    credentialCoordinator: coordinators.delivery ?? credentialCoordinator,
    createId: () =>
      `00000000-0000-4000-8000-${String(nextId++).padStart(12, "0")}`,
    pool: runtimePool,
    publicOrigin: settings.publicOrigin,
    async sendEmail(email) {
      sent.push(email);
      await delivery(email);
    },
  });
  const completionReset =
    coordinators.completion === undefined
      ? reset
      : new PasswordResetLifecycle({
          authSecret: settings.secret,
          backgroundTask: tasks.handler,
          clock: () => fixedNow,
          credentialCoordinator: coordinators.completion,
          pool: runtimePool,
          publicOrigin: settings.publicOrigin,
          async sendEmail() {
            throw new Error("PASSWORD_RESET_DELIVERY_NOT_AVAILABLE");
          },
        });
  const invitationAdmission = new InvitationAdmission();
  const lifecycle: AuthLifecycleDependencies = {
    backgroundTask: tasks.handler,
    invitationAdmission,
    isResearcherActive: reset.isResearcherActive,
    sendResetPassword: reset.sendResetPassword,
  };
  const auth = createThesisTraceAuth(settings, runtimePool, lifecycle);
  const app = createAuthApp({
    async acceptInvitation() {
      throw new InvitationRejectedError();
    },
    authHandler: (request) =>
      (coordinators.request ?? credentialCoordinator).handleAuthRequest(
        request,
        (coordinated) => auth.handler(coordinated),
        (headers) =>
          auth.api.getSession({
            headers,
            query: { disableCookieCache: true, disableRefresh: true },
          }),
      ),
    async consumeInvitationRateLimit() {
      return { allowed: true, retryAfterSeconds: 0 };
    },
    consumePasswordResetRateLimit,
    getSession: (input) => auth.api.getSession(input),
    async inspectInvitation() {
      throw new InvitationRejectedError();
    },
    publicOrigin: settings.publicOrigin,
    readiness: async () => true,
    resetPassword: completionReset.completeReset,
  });
  return { app, auth, invitationAdmission, reset, sent, tasks };
}

function createCredentialCoordinator(): CredentialOperationCoordinator {
  return new CredentialOperationCoordinator({
    authSecret: settings.secret,
    coordination,
    pool: runtimePool,
  });
}

async function createUser(
  harness: ReturnType<typeof resetHarness>,
  email: string,
): Promise<void> {
  const response = await harness.invitationAdmission.run(email, () =>
    harness.auth.api.signUpEmail({
      asResponse: true,
      body: {
        email,
        name: "untrusted",
        password: "correct-horse-battery-staple",
      },
      headers: requestHeaders(),
    }),
  );
  expect(response.status).toBe(200);
}

async function requestReset(
  harness: ReturnType<typeof resetHarness>,
  email: string,
): Promise<Response> {
  return await harness.app.request(
    `${settings.publicOrigin}/api/auth/request-password-reset`,
    {
      body: JSON.stringify({ email }),
      headers: {
        "content-type": "application/json",
        origin: settings.publicOrigin,
      },
      method: "POST",
    },
  );
}

async function resetPassword(
  harness: ReturnType<typeof resetHarness>,
  token: string,
): Promise<Response> {
  return await harness.app.request(`${settings.publicOrigin}/api/auth/reset-password`, {
    body: JSON.stringify({
      newPassword: "new-correct-horse-battery-staple",
      token,
    }),
    headers: {
      "content-type": "application/json",
      origin: settings.publicOrigin,
      "x-thesistrace-client-ip": "192.0.2.20",
    },
    method: "POST",
  });
}

async function signIn(
  harness: ReturnType<typeof resetHarness>,
  email: string,
  password: string,
): Promise<Response> {
  return await harness.auth.api.signInEmail({
    asResponse: true,
    body: { email, password },
    headers: requestHeaders(),
  });
}

async function publicSignIn(
  harness: ReturnType<typeof resetHarness>,
  email: string,
  password: string,
): Promise<Response> {
  return await harness.app.request(
    `${settings.publicOrigin}/api/auth/sign-in/email`,
    {
      body: JSON.stringify({ email, password }),
      headers: {
        "content-type": "application/json",
        origin: settings.publicOrigin,
      },
      method: "POST",
    },
  );
}

function resetToken(email: ResendEmail | undefined): string {
  const match = email?.html.match(/#token=([^"'<\s]+)/);
  if (match?.[1] === undefined) {
    throw new Error("expected a Password Reset fragment token");
  }
  return decodeURIComponent(match[1]);
}

function requestHeaders(): Headers {
  return new Headers({
    origin: settings.publicOrigin,
    "x-thesistrace-client-ip": "192.0.2.20",
  });
}

async function sessionCount(): Promise<number> {
  const result = await owner.query<{ count: string }>(
    'SELECT count(*) FROM auth."session"',
  );
  return Number(result.rows[0]?.count ?? "0");
}

async function hasAdvisoryWaiter(applicationName: string): Promise<boolean> {
  const result = await owner.query<{ waiting: boolean }>(
    `
      SELECT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_stat_activity
        WHERE application_name = $1
          AND wait_event_type = 'Lock'
      ) AS waiting
    `,
    [applicationName],
  );
  return result.rows[0]?.waiting === true;
}

async function waitForCondition(
  condition: () => Promise<boolean>,
  timeoutMilliseconds = 4_000,
): Promise<void> {
  const deadline = performance.now() + timeoutMilliseconds;
  while (!(await condition())) {
    if (performance.now() >= deadline) {
      throw new Error("condition was not reached before its deadline");
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  }
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
