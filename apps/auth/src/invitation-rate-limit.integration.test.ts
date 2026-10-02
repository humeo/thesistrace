import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { createAuthPool } from "./database.js";
import { createBetterAuthRateLimitStorage, AuthEndpointRateLimiter } from "./auth-rate-limit.js";
import { initializeAuthSchema } from "./schema-initialize.js";

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
const fixedNow = new Date("2026-08-28T07:00:00.000Z");
const secret = "0123456789abcdef0123456789abcdef";

describe.sequential("Auth endpoint PostgreSQL rate limit", () => {
  beforeAll(async () => {
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    await owner.query('TRUNCATE auth."rateLimit"');
  });

  afterAll(async () => {
    await runtimePool.end();
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
  });

  it("shares atomic fixed windows across Better Auth storage instances, including expiry", async () => {
    let now = fixedNow.getTime();
    const instances = [0, 1].map(() => createBetterAuthRateLimitStorage({ pool: runtimePool, clock: () => new Date(now) }));
    const consume = () => Promise.all(Array.from({ length: 6 }, (_, i) => instances[i % 2]!.consume("192.0.2.80|/sign-in/email-otp", { max: 5, window: 60 })));
    for (const offset of [0, 60_000]) {
      now = fixedNow.getTime() + offset;
      const decisions = await consume();
      expect(decisions.filter(d => d.allowed)).toHaveLength(5);
      expect(decisions.filter(d => !d.allowed)).toEqual([{ allowed: false, retryAfter: 60 }]);
    }
    now += 59_999;
    await expect(instances[0]!.consume("192.0.2.80|/sign-in/email-otp", { max: 5, window: 60 })).resolves.toEqual({ allowed: false, retryAfter: 1 });
    now += 1;
    await expect(instances[1]!.consume("192.0.2.80|/sign-in/email-otp", { max: 5, window: 60 })).resolves.toEqual({ allowed: true, retryAfter: null });
  });

  it("uses an existing persisted bucket until its window expires", async () => {
    await owner.query('INSERT INTO auth."rateLimit" (key,count,"lastRequest") VALUES ($1,60,$2)', ['192.0.2.81|/ok', fixedNow.getTime()]);
    let now = fixedNow.getTime() + 20_000;
    const storage = createBetterAuthRateLimitStorage({ pool: runtimePool, clock: () => new Date(now) });
    await expect(storage.consume('192.0.2.81|/ok', {max: 60, window: 60})).resolves.toEqual({allowed: false, retryAfter: 40});
    now = fixedNow.getTime() + 60_000;
    await expect(storage.consume('192.0.2.81|/ok', {max: 60, window: 60})).resolves.toEqual({allowed: true, retryAfter: null});
  });

  it.each(["email-code", "operator-proof", "password-reset", "researcher-invitation"] as const)("retains fixed windows for continuous activity in %s", async scope => {
    let now = fixedNow.getTime();
    const limiter = new AuthEndpointRateLimiter({authSecret: secret, pool: runtimePool, scope, clock: () => new Date(now)});
    for (let i = 0; i < 20; i += 1) {
      now = fixedNow.getTime() + i * 20_000;
      await expect(limiter.consume("subject", new Headers({"x-thesistrace-client-ip": "192.0.2.82"}))).resolves.toEqual({allowed: true, retryAfterSeconds: 0});
    }
  });

  it("atomically admits only five concurrent requests for one IP and token", async () => {
    const limiter = new AuthEndpointRateLimiter({
      authSecret: secret,
      clock: () => fixedNow,
      pool: runtimePool,
      scope: "researcher-invitation",
    });
    const token = "opaque-invitation-token-canary";
    const headers = new Headers({
      "x-thesistrace-client-ip": "192.0.2.71",
    });

    const decisions = await Promise.all(
      Array.from({ length: 6 }, () => limiter.consume(token, headers)),
    );
    const keys = await owner.query<{ key: string }>(
      'SELECT key FROM auth."rateLimit" ORDER BY key',
    );

    expect(decisions.filter((decision) => decision.allowed)).toHaveLength(5);
    expect(decisions.filter((decision) => !decision.allowed)).toEqual([
      { allowed: false, retryAfterSeconds: 60 },
    ]);
    expect(keys.rows).toHaveLength(2);
    expect(JSON.stringify(keys.rows)).not.toContain(token);
    expect(JSON.stringify(keys.rows)).not.toContain("192.0.2.71");
  });

  it("enforces the IP and token budgets independently", async () => {
    const limiter = new AuthEndpointRateLimiter({
      authSecret: secret,
      clock: () => fixedNow,
      pool: runtimePool,
      scope: "researcher-invitation",
    });
    const firstIp = new Headers({
      "x-thesistrace-client-ip": "192.0.2.72",
    });
    for (let index = 0; index < 5; index += 1) {
      await expect(limiter.consume(`token-${index}`, firstIp)).resolves.toMatchObject({
        allowed: true,
      });
    }
    await expect(limiter.consume("token-over-ip-budget", firstIp)).resolves.toEqual({
      allowed: false,
      retryAfterSeconds: 60,
    });
    expect(
      await owner.query<{ count: string }>(
        'SELECT count(*) FROM auth."rateLimit"',
      ),
    ).toMatchObject({ rows: [{ count: "6" }] });

    await owner.query('TRUNCATE auth."rateLimit"');
    for (let index = 0; index < 5; index += 1) {
      await expect(
        limiter.consume(
          "shared-token",
          new Headers({
            "x-thesistrace-client-ip": `198.51.100.${index + 1}`,
          }),
        ),
      ).resolves.toMatchObject({ allowed: true });
    }
    await expect(
      limiter.consume(
        "shared-token",
        new Headers({ "x-thesistrace-client-ip": "198.51.100.99" }),
      ),
    ).resolves.toEqual({ allowed: false, retryAfterSeconds: 60 });
  });

  it("keeps Invitation and Password Reset budgets in independent scopes", async () => {
    const invitation = new AuthEndpointRateLimiter({
      authSecret: secret,
      clock: () => fixedNow,
      pool: runtimePool,
      scope: "researcher-invitation",
    });
    const reset = new AuthEndpointRateLimiter({
      authSecret: secret,
      clock: () => fixedNow,
      pool: runtimePool,
      scope: "password-reset",
    });
    const headers = new Headers({
      "x-thesistrace-client-ip": "203.0.113.80",
    });
    for (let index = 0; index < 5; index += 1) {
      await expect(invitation.consume("shared-secret", headers)).resolves.toMatchObject({
        allowed: true,
      });
    }

    await expect(reset.consume("shared-secret", headers)).resolves.toEqual({
      allowed: true,
      retryAfterSeconds: 0,
    });
    expect(
      await owner.query<{ count: string }>(
        'SELECT count(*) FROM auth."rateLimit"',
      ),
    ).toMatchObject({ rows: [{ count: "4" }] });
  });
});

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
