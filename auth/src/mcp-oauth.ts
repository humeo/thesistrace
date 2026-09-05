import { createHash } from "node:crypto";
import { APIError } from "better-auth/api";
import type { OAuthOptions } from "@better-auth/oauth-provider";
import type { AuthSettings } from "./config.js";

export const MCP_ACCESS_PREFIX = "tt_mcp_";
export const mcpTokenHash = (token: string): string => createHash("sha256").update(token).digest("hex");

export function mcpOAuthOptions(
  settings: AuthSettings,
  isActive: (id: string) => Promise<boolean>,
): OAuthOptions<string[]> {
  const scopes = [...settings.mcpGrantScopes, "offline_access"];
  return {
    loginPage: "/login",
    consentPage: "/connections/mcp/authorize",
    disableJwtPlugin: true,
    scopes,
    grantTypes: ["authorization_code", "refresh_token"],
    allowPublicClientPrelogin: true,
    allowDynamicClientRegistration: true,
    allowUnauthenticatedClientRegistration: true,
    clientRegistrationRequirePKCE: true,
    clientRegistrationDefaultScopes: scopes,
    clientRegistrationDefaultResources: [settings.mcpAudience],
    enforcePerClientResources: true,
    resources: [{ identifier: settings.mcpAudience, allowedScopes: scopes }],
    resourceSeedMode: "overwrite",
    resourcePrivileges: () => false,
    clientPrivileges: () => false,
    prefix: { opaqueAccessToken: MCP_ACCESS_PREFIX, refreshToken: "tt_refresh_" },
    storeTokens: { hash: mcpTokenHash },
    accessTokenExpiresIn: settings.mcpTokenLifetimeSeconds,
    refreshTokenExpiresIn: 30 * 86400,
    async customAccessTokenClaims({ user }) {
      if (!user || !(await isActive(user.id))) throw new APIError("UNAUTHORIZED");
      return {};
    },
  };
}
