import { getIPFromHeader } from "@better-auth/core/utils/ip";
import type { Pool } from "pg";
import { canonicalizeEmail } from "./identity.js";
import { createBetterAuthRateLimitStorage, consumeRateLimitKey } from "./auth-rate-limit.js";
import { unknownEmailHmac } from "./security.js";

export const SIGN_IN_CHALLENGE_ACTION = "sign-in-code";
export type SignInCodeDecision = Readonly<{allowed: true}> | Readonly<{
  allowed: false;
  reason: "rate-limit" | "challenge" | "unavailable";
  retryAfterSeconds: number;
}>;

type Dependencies = Readonly<{
  pool: Pool;
  authSecret: string;
  verifyChallenge: (token: string, remoteIp: string) => Promise<boolean>;
  globalHourlyLimit: number;
  globalDailyLimit: number;
  clock?: () => Date;
  onBudgetReached?: (windowSeconds: number, limit: number) => void;
}>;

/** Public sign-in delivery is admitted before generating or rotating an OTP. */
export class SignInCodeAdmission {
  readonly #deps: Dependencies;
  readonly #clock: () => Date;
  readonly #requests;

  constructor(deps: Dependencies) {
    for (const limit of [deps.globalHourlyLimit, deps.globalDailyLimit]) {
      if (!Number.isSafeInteger(limit) || limit < 1) throw new Error("AUTH_EMAIL_BUDGET_INVALID");
    }
    this.#deps = deps;
    this.#clock = deps.clock ?? (() => new Date());
    this.#requests = createBetterAuthRateLimitStorage({pool: deps.pool, clock: this.#clock});
  }

  async admit(email: string, token: string, headers: Headers): Promise<SignInCodeDecision> {
    const header = headers.get("x-thesistrace-client-ip");
    const subnet = header === null ? null : getIPFromHeader(header, {ipv6Subnet: 64});
    const remoteIp = header === null ? null : getIPFromHeader(header, {ipv6Subnet: 128});
    if (subnet === null || remoteIp === null) return {allowed: false, reason: "unavailable", retryAfterSeconds: 0};
    const request = await this.#requests.consume(this.#key("ip", subnet), {max: 5, window: 60});
    if (!request.allowed) {
      if (request.retryAfter === null) throw new Error("AUTH_RATE_LIMIT_RECORD_INVALID");
      return {allowed: false, reason: "rate-limit", retryAfterSeconds: request.retryAfter};
    }
    try {
      if (!await this.#deps.verifyChallenge(token, remoteIp)) return {allowed: false, reason: "challenge", retryAfterSeconds: 0};
    } catch {
      return {allowed: false, reason: "unavailable", retryAfterSeconds: 0};
    }

    const canonical = canonicalizeEmail(email);
    const rules = [
      {key: this.#key("email-minute", canonical), seconds: 60, limit: 1},
      {key: this.#key("email-hour", canonical), seconds: 3600, limit: 5},
      {key: this.#key("email-day", canonical), seconds: 86400, limit: 10},
      {key: this.#key("global-hour", "all"), seconds: 3600, limit: this.#deps.globalHourlyLimit},
      {key: this.#key("global-day", "all"), seconds: 86400, limit: this.#deps.globalDailyLimit},
    ];
    const client = await this.#deps.pool.connect();
    const reached: typeof rules = [];
    try {
      await client.query("BEGIN");
      // A fixed order prevents deadlocks. Rollback keeps rejected requests from
      // consuming other budgets or extending an existing email's cooldown.
      const now = this.#clock().getTime();
      for (const rule of rules) {
        const record = await consumeRateLimitKey(client, rule.key, now, rule.seconds * 1000);
        if (record.count > rule.limit) {
          await client.query("ROLLBACK");
          return {allowed: false, reason: "rate-limit", retryAfterSeconds: Math.max(1, Math.ceil((record.lastRequest + rule.seconds * 1000 - now) / 1000))};
        }
        if (rule.key.includes(":global-") && record.count === rule.limit) reached.push(rule);
      }
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
    for (const rule of reached) this.#deps.onBudgetReached?.(rule.seconds, rule.limit);
    return {allowed: true};
  }

  #key(dimension: string, value: string): string {
    return "sign-in-code:" + dimension + ":" + unknownEmailHmac(this.#deps.authSecret, "sign-in-code:" + dimension + ":" + value).toString("hex");
  }
}
