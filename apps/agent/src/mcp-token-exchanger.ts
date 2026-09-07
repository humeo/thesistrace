import { z } from "zod";

import { loginSessionCookieHeader } from "./login-session-cookie.js";
import { AgentRunFailure } from "./run-failure.js";
import type { AgentFailureCode } from "@thesistrace/contracts/agent-failure";

const MAX_ACCESS_TOKEN_BYTES = 16 * 1024;
const exchangedTokenSchema = z.object({
  access_token: z.string().min(1).max(MAX_ACCESS_TOKEN_BYTES),
  expires_in: z.number().int().positive(),
  token_type: z.literal("Bearer"),
}).strict();

export type ExchangedMcpToken = Readonly<z.infer<typeof exchangedTokenSchema>>;
type FetchImplementation = typeof globalThis.fetch;

export class McpRunPreparationError extends AgentRunFailure {
  constructor(code: AgentFailureCode = "MCP_TRANSIENT") {
    super(code);
    this.name = "McpRunPreparationError";
  }
}

export function createMcpTokenExchanger(dependencies: Readonly<{
  authInternalOrigin: string;
  clockSkewSeconds: number;
  fetch?: FetchImplementation;
  now?: () => number;
  runMaxWallSeconds: number;
  timeoutMs?: number;
}>): (headers: Headers) => Promise<ExchangedMcpToken> {
  const fetchImplementation = dependencies.fetch ?? globalThis.fetch;
  const now = dependencies.now ?? (() => globalThis.performance.now());
  const timeoutMs = dependencies.timeoutMs ?? 2_000;
  return async (headers) => {
    const forwarded = new Headers();
    const cookie = loginSessionCookieHeader(headers.get("cookie"));
    if (cookie !== undefined) forwarded.set("cookie", cookie);

    let response: Response;
    const exchangeStartedAt = now();
    try {
      response = await fetchImplementation(
        `${dependencies.authInternalOrigin}/internal/session/exchange`,
        {
          headers: forwarded,
          method: "POST",
          redirect: "error",
          signal: AbortSignal.timeout(timeoutMs),
        },
      );
    } catch {
      throw new McpRunPreparationError();
    }
    if (response.status === 401) throw new McpRunPreparationError("AUTHENTICATION_REQUIRED");
    if (response.status === 403) throw new McpRunPreparationError("MCP_AUTHENTICATION");
    if (response.status !== 200) throw new McpRunPreparationError();

    try {
      const parsed = exchangedTokenSchema.safeParse(await response.json());
      const exchangeCompletedAt = now();
      if (
        !Number.isFinite(exchangeStartedAt)
        || !Number.isFinite(exchangeCompletedAt)
        || exchangeCompletedAt < exchangeStartedAt
      ) {
        throw new McpRunPreparationError();
      }
      const elapsedSeconds = Math.ceil(
        (exchangeCompletedAt - exchangeStartedAt) / 1_000,
      );
      if (
        !parsed.success
        || parsed.data.expires_in - elapsedSeconds
          <= dependencies.runMaxWallSeconds + dependencies.clockSkewSeconds
      ) {
        throw new McpRunPreparationError();
      }
      return parsed.data;
    } catch (error) {
      if (error instanceof McpRunPreparationError) throw error;
      throw new McpRunPreparationError();
    }
  };
}
