import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { createAuthApp } from "./app.js";
import { createThesisTraceAuth } from "./auth.js";
import type { AuthSettings } from "./config.js";
import { createAuthPool } from "./database.js";
import { checkAuthReadiness } from "./readiness.js";
import { initializeAuthSchema } from "./schema-initialize.js";
import { verifyAuthSchema } from "./schema-contract.js";

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
const settings: AuthSettings = {
  databaseUrl: authRuntimeDatabaseUrl,
  environment: "test",
  host: "127.0.0.1",
  port: 8200,
  publicOrigin: "http://127.0.0.1:5173",
  secret: "0123456789abcdef0123456789abcdef",
  secureCookies: false,
};
const ambientOverrideNames = [
  "BETTER_AUTH_SECRETS",
  "BETTER_AUTH_TELEMETRY",
  "BETTER_AUTH_TELEMETRY_DEBUG",
  "BETTER_AUTH_TELEMETRY_ENDPOINT",
  "BETTER_AUTH_TELEMETRY_ID",
  "BETTER_AUTH_TRUSTED_ORIGINS",
] as const;
const originalOverrides = new Map(
  ambientOverrideNames.map((name) => [name, process.env[name]]),
);

describe.sequential("Auth database-backed HTTP contract", () => {
  beforeAll(async () => {
    for (const name of ambientOverrideNames) {
      delete process.env[name];
    }
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    await owner.query('TRUNCATE auth."user" CASCADE');
    await owner.query('TRUNCATE auth."rateLimit"');
  });

  afterAll(async () => {
    await runtimePool.end();
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
    for (const name of ambientOverrideNames) {
      const original = originalOverrides.get(name);
      if (original === undefined) {
        delete process.env[name];
      } else {
        process.env[name] = original;
      }
    }
  });

  it("serves Better Auth ok through Hono against the initialized database", async () => {
    const { app } = runtime();
    const response = await app.request(`${settings.publicOrigin}/api/auth/ok`);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
  });

  it("verifies a valid Session from PostgreSQL without refreshing its Cookie", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "valid@example.com");
    await owner.query(`
      UPDATE auth."session"
      SET
        "expiresAt" = CURRENT_TIMESTAMP + INTERVAL '4 days',
        "updatedAt" = CURRENT_TIMESTAMP - INTERVAL '3 days'
    `);
    const before = await persistedSessionTimes();

    const response = await app.request(
      `${settings.publicOrigin}/internal/session/verify`,
      { method: "POST", headers: { cookie } },
    );

    expect(response.status).toBe(200);
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(await response.json()).toMatchObject({
      active: true,
      display_label: "valid",
      email: "valid@example.com",
      researcher_id: expect.stringMatching(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      ),
    });
    expect(await persistedSessionTimes()).toEqual(before);
  });

  it("trims and lowercases email at the public email-password boundary", async () => {
    const { app, auth } = runtime();
    await createSessionCookie(auth, "canonical@example.com");

    const response = await app.request(
      `${settings.publicOrigin}/api/auth/sign-in/email`,
      {
        body: JSON.stringify({
          email: "  Canonical@Example.COM  ",
          password: "correct-horse-battery-staple",
        }),
        headers: {
          "content-type": "application/json",
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );

    const users = await owner.query<{ email: string }>('SELECT email FROM auth."user"');
    expect(response.status).toBe(200);
    expect(users.rows).toEqual([{ email: "canonical@example.com" }]);
  });

  it("rejects a cross-origin credential request", async () => {
    const { app, auth } = runtime();
    await createSessionCookie(auth, "origin@example.com");

    const response = await app.request(
      `${settings.publicOrigin}/api/auth/sign-in/email`,
      {
        body: JSON.stringify({
          email: "origin@example.com",
          password: "correct-horse-battery-staple",
        }),
        headers: {
          "content-type": "application/json",
          origin: "https://attacker.example",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(403);
  });

  it.each([11, 129])("rejects a %i-character password", async (length) => {
    const { auth } = runtime();
    const response = await directSignUp(auth, {
      email: `password-${length}@example.com`,
      password: "x".repeat(length),
    });

    expect(response.status).toBe(400);
    expect(
      await owner.query<{ count: string }>('SELECT count(*) FROM auth."user"'),
    ).toMatchObject({ rows: [{ count: "0" }] });
  });

  it("enforces the sign-in rate limit in PostgreSQL", async () => {
    const { app } = runtime();
    const statuses: number[] = [];
    for (let attempt = 0; attempt < 6; attempt += 1) {
      const response = await app.request(
        `${settings.publicOrigin}/api/auth/sign-in/email`,
        {
          body: JSON.stringify({
            email: "missing@example.com",
            password: "correct-horse-battery-staple",
          }),
          headers: {
            "content-type": "application/json",
            origin: settings.publicOrigin,
            "x-thesistrace-client-ip": "192.0.2.10",
          },
          method: "POST",
        },
      );
      statuses.push(response.status);
    }

    expect(statuses.slice(0, 5)).not.toContain(429);
    expect(statuses[5]).toBe(429);
    const records = await owner.query<{ count: string }>(
      'SELECT count(*) FROM auth."rateLimit"',
    );
    expect(records.rows).toEqual([{ count: "1" }]);
  });

  it("sets the complete Production Session Cookie attributes", async () => {
    const auth = createThesisTraceAuth(
      {
        ...settings,
        environment: "production",
        publicOrigin: "https://thesistrace.test",
        secret:
          "a4f781c2d6e9035b8a1f74c092e5bd3680c4f719a2e65b03d8f14c7a9e256bd0",
        secureCookies: true,
      },
      runtimePool,
    );
    const response = await directSignUp(auth, {
      email: "cookie@example.com",
      origin: "https://thesistrace.test",
      password: "correct-horse-battery-staple",
      publicOrigin: "https://thesistrace.test",
    });
    const cookie = response.headers.get("set-cookie") ?? "";

    expect(response.status).toBe(200);
    expect(cookie).toContain("__Secure-thesistrace.session_token=");
    expect(cookie).toMatch(/; HttpOnly/i);
    expect(cookie).toMatch(/; SameSite=Lax/i);
    expect(cookie).toMatch(/; Secure/i);
  });

  it("refreshes an aged Session through the public get-session endpoint", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "rolling@example.com");
    await owner.query(`
      UPDATE auth."session"
      SET
        "expiresAt" = CURRENT_TIMESTAMP + INTERVAL '4 days',
        "updatedAt" = CURRENT_TIMESTAMP - INTERVAL '3 days'
    `);
    const before = await persistedSessionTimes();

    const response = await app.request(
      `${settings.publicOrigin}/api/auth/get-session`,
      { headers: { cookie } },
    );
    const after = await persistedSessionTimes();

    expect(response.status).toBe(200);
    expect(response.headers.has("set-cookie")).toBe(true);
    expect(after.updatedAt.getTime()).toBeGreaterThan(before.updatedAt.getTime());
    expect(after.expiresAt.getTime()).toBeGreaterThan(before.expiresAt.getTime());
  });

  it("keeps self-service display-label editing disabled", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "immutable@example.com");

    const response = await app.request(
      `${settings.publicOrigin}/api/auth/update-user`,
      {
        body: JSON.stringify({ name: "changed-by-user" }),
        headers: {
          "content-type": "application/json",
          cookie,
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );
    const user = await owner.query<{ name: string }>('SELECT name FROM auth."user"');

    expect(response.status).toBe(404);
    expect(user.rows).toEqual([{ name: "immutable" }]);
  });

  it.each(["list-sessions", "update-session"])(
    "does not expose the %s Session-management endpoint",
    async (path) => {
      const { app, auth } = runtime();
      const cookie = await createSessionCookie(auth, `${path}@example.com`);

      const response = await app.request(
        `${settings.publicOrigin}/api/auth/${path}`,
        {
          body: JSON.stringify({}),
          headers: {
            "content-type": "application/json",
            cookie,
            origin: settings.publicOrigin,
          },
          method: "POST",
        },
      );

      expect(response.status).toBe(404);
      expect(await response.text()).toBe("");
    },
  );

  it.each(["invalid", "expired", "revoked", "inactive"])(
    "rejects an %s database Session",
    async (state) => {
      const { app, auth } = runtime();
      let cookie = "thesistrace.session_token=invalid";
      if (state !== "invalid") {
        cookie = await createSessionCookie(auth, `${state}@example.com`);
      }
      if (state === "expired") {
        await owner.query(
          `UPDATE auth."session" SET "expiresAt" = CURRENT_TIMESTAMP - INTERVAL '1 second'`,
        );
      } else if (state === "revoked") {
        await owner.query('DELETE FROM auth."session"');
      } else if (state === "inactive") {
        await owner.query('UPDATE auth."user" SET active = FALSE');
      }

      const response = await app.request(
        `${settings.publicOrigin}/internal/session/verify`,
        { method: "POST", headers: { cookie } },
      );

      expect(response.status).toBe(401);
      expect(response.headers.has("set-cookie")).toBe(false);
      expect(await response.json()).toEqual({ code: "AUTHENTICATION_REQUIRED" });
    },
  );

  it("fails closed on malformed persisted identity state", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "malformed@example.com");
    await owner.query('UPDATE auth."user" SET name = \'\'');

    const response = await app.request(
      `${settings.publicOrigin}/internal/session/verify`,
      { method: "POST", headers: { cookie } },
    );

    expect(response.status).toBe(503);
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(await response.json()).toEqual({ code: "AUTH_SERVICE_UNAVAILABLE" });
  });

  it("returns 503 within the database lock budget", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "locked@example.com");
    const blocker = await owner.connect();
    try {
      await blocker.query("BEGIN");
      await blocker.query('LOCK TABLE auth."session" IN ACCESS EXCLUSIVE MODE');
      const startedAt = performance.now();

      const response = await app.request(
        `${settings.publicOrigin}/internal/session/verify`,
        { method: "POST", headers: { cookie } },
      );

      expect(response.status).toBe(503);
      expect(performance.now() - startedAt).toBeLessThan(4_000);
    } finally {
      await blocker.query("ROLLBACK").catch(() => undefined);
      blocker.release();
    }
  });

  it("checks the exact startup schema and Session storage for readiness", async () => {
    await expect(verifyAuthSchema(runtimePool)).resolves.toBeUndefined();
    await expect(checkAuthReadiness(runtimePool)).resolves.toBe(true);

    await owner.query(
      "UPDATE auth.schema_contract SET schema_fingerprint = repeat('0', 64)",
    );
    await expect(checkAuthReadiness(runtimePool)).resolves.toBe(false);
  });
});

function runtime() {
  const auth = createThesisTraceAuth(settings, runtimePool);
  const app = createAuthApp({
    authHandler: (request) => auth.handler(request),
    getSession: (input) => auth.api.getSession(input),
    readiness: () => checkAuthReadiness(runtimePool),
  });
  return { app, auth };
}

async function createSessionCookie(
  auth: ReturnType<typeof createThesisTraceAuth>,
  email: string,
): Promise<string> {
  const response = await directSignUp(auth, {
    email,
    password: "correct-horse-battery-staple",
  });
  expect(response.status).toBe(200);
  const setCookie = response.headers.get("set-cookie");
  expect(setCookie).not.toBeNull();
  return setCookie ?? "";
}

async function directSignUp(
  auth: ReturnType<typeof createThesisTraceAuth>,
  input: Readonly<{
    email: string;
    origin?: string;
    password: string;
    publicOrigin?: string;
  }>,
): Promise<Response> {
  const publicOrigin = input.publicOrigin ?? settings.publicOrigin;
  return auth.handler(
    new Request(`${publicOrigin}/api/auth/sign-up/email`, {
      body: JSON.stringify({
        email: input.email,
        name: "client-supplied-label",
        password: input.password,
      }),
      headers: {
        "content-type": "application/json",
        origin: input.origin ?? settings.publicOrigin,
        "x-thesistrace-client-ip": `192.0.2.${input.password.length}`,
      },
      method: "POST",
    }),
  );
}

async function persistedSessionTimes(): Promise<{
  expiresAt: Date;
  updatedAt: Date;
}> {
  const result = await owner.query<{ expiresAt: Date; updatedAt: Date }>(
    'SELECT "expiresAt", "updatedAt" FROM auth."session"',
  );
  const row = result.rows[0];
  if (row === undefined) {
    throw new Error("expected one persisted Session");
  }
  return row;
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
