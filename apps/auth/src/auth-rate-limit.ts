import type { Pool, PoolClient } from "pg";

import { unknownEmailHmac } from "./security.js";

const WINDOW_MILLISECONDS = 60_000;
const MAX_REQUESTS = 5;

export type AuthRateLimitDecision = Readonly<{
  allowed: boolean;
  retryAfterSeconds: number;
}>;

export type AuthEndpointRateLimiterDependencies = Readonly<{
  authSecret: string;
  clock?: () => Date;
  pool: Pool;
  scope: "operator-proof" | "password-reset" | "researcher-invitation";
}>;

export class AuthEndpointRateLimiter {
  readonly #authSecret: string;
  readonly #clock: () => Date;
  readonly #pool: Pool;
  readonly #scope: AuthEndpointRateLimiterDependencies["scope"];

  constructor(dependencies: AuthEndpointRateLimiterDependencies) {
    this.#authSecret = dependencies.authSecret;
    this.#clock = dependencies.clock ?? (() => new Date());
    this.#pool = dependencies.pool;
    this.#scope = dependencies.scope;
  }

  async consume(
    secretValue: string,
    headers: Headers,
  ): Promise<AuthRateLimitDecision> {
    const ipAddress = headers.get("x-thesistrace-client-ip") ?? "missing";
    const now = this.#clock().getTime();
    const ipKey = this.#key("ip", ipAddress);
    const tokenKey = this.#key("token", secretValue);
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const ipRecord = await consumeKey(client, ipKey, now);
      if (ipRecord.count > MAX_REQUESTS) {
        await client.query("COMMIT");
        return blockedDecision([ipRecord], now);
      }
      const tokenRecord = await consumeKey(client, tokenKey, now);
      await client.query("COMMIT");
      if (tokenRecord.count > MAX_REQUESTS) {
        return blockedDecision([tokenRecord], now);
      }
      return { allowed: true, retryAfterSeconds: 0 };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  #key(dimension: "ip" | "token", value: string): string {
    const digest = unknownEmailHmac(
      this.#authSecret,
      `${this.#scope}:${dimension}:${value}`,
    ).toString("hex");
    return `${this.#scope}:${dimension}:${digest}`;
  }
}

function blockedDecision(
  records: ReadonlyArray<Readonly<{ lastRequest: number }>>,
  now: number,
): AuthRateLimitDecision {
  return {
    allowed: false,
    retryAfterSeconds: Math.max(
      1,
      ...records.map((record) =>
        Math.ceil((record.lastRequest + WINDOW_MILLISECONDS - now) / 1_000),
      ),
    ),
  };
}

async function consumeKey(
  client: PoolClient,
  key: string,
  now: number,
): Promise<Readonly<{ count: number; lastRequest: number }>> {
  const result = await client.query<{ count: number; lastRequest: string }>(
    `
      INSERT INTO auth."rateLimit" AS rate_limit (
        "key",
        "count",
        "lastRequest"
      )
      VALUES ($1, 1, $2)
      ON CONFLICT ("key") DO UPDATE
      SET
        "count" = CASE
          WHEN EXCLUDED."lastRequest" - rate_limit."lastRequest" >= $3
            THEN 1
          ELSE rate_limit."count" + 1
        END,
        "lastRequest" = CASE
          WHEN EXCLUDED."lastRequest" - rate_limit."lastRequest" >= $3
            THEN EXCLUDED."lastRequest"
          ELSE rate_limit."lastRequest"
        END
      RETURNING "count", "lastRequest"
    `,
    [key, now, WINDOW_MILLISECONDS],
  );
  const record = result.rows[0];
  if (record === undefined) {
    throw new Error("AUTH_RATE_LIMIT_WRITE_FAILED");
  }
  return { count: record.count, lastRequest: Number(record.lastRequest) };
}
