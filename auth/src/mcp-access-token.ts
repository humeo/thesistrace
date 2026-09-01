import { randomUUID } from "node:crypto";

import type { AuthSettings } from "./config.js";

const MAX_ACCESS_TOKEN_BYTES = 16 * 1024;

export type McpAccessToken = Readonly<{
  access_token: string;
  expires_in: number;
  token_type: "Bearer";
}>;

export type McpTokenPayload = Readonly<{
  client_id: string;
  exp: number;
  iat: number;
  jti: string;
  nbf: number;
  scope: string;
  sub: string;
}>;

export function createMcpAccessTokenIssuer(
  settings: AuthSettings,
  dependencies: Readonly<{
    now?: () => number;
    newTokenId?: () => string;
    sign: (payload: McpTokenPayload) => Promise<Readonly<{ token: string }>>;
  }>,
): (researcherId: string) => Promise<McpAccessToken> {
  const now = dependencies.now ?? Date.now;
  const newTokenId = dependencies.newTokenId ?? randomUUID;
  return async (researcherId) => {
    const issuedAt = Math.floor(now() / 1_000);
    const signed = await dependencies.sign({
      client_id: settings.mcpClientId,
      exp: issuedAt + settings.mcpTokenLifetimeSeconds,
      iat: issuedAt,
      jti: newTokenId(),
      nbf: issuedAt,
      scope: settings.mcpGrantScopes.join(" "),
      sub: researcherId,
    });
    if (
      typeof signed.token !== "string"
      || signed.token.length === 0
      || Buffer.byteLength(signed.token, "utf8") > MAX_ACCESS_TOKEN_BYTES
    ) {
      throw new Error("MCP_ACCESS_TOKEN_INVALID");
    }
    return {
      access_token: signed.token,
      expires_in: settings.mcpTokenLifetimeSeconds,
      token_type: "Bearer",
    };
  };
}
