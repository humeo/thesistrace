import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { createAuthPool } from "./database.js";
import { AuthEndpointRateLimiter } from "./auth-rate-limit.js";
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
