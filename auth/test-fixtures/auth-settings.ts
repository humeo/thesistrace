import type { AuthSettings } from "../src/config.js";

const privateJwk = {
  alg: "EdDSA",
  crv: "Ed25519",
  d: "2SCCVM_DYKEJvq18KV1M4UNFhxTHLKtdXxQFXLGlEBs",
  kid: "test-signing-key-01",
  kty: "OKP",
  use: "sig",
  x: "3d8K_V0qubfzURRlfRFt44Yk4LeNW6HkQMaeiPIhJA8",
} as const;

const publicJwk = {
  alg: "EdDSA",
  crv: "Ed25519",
  kid: "test-signing-key-01",
  kty: "OKP",
  use: "sig",
  x: "3d8K_V0qubfzURRlfRFt44Yk4LeNW6HkQMaeiPIhJA8",
} as const;

export function authTestSettings(
  overrides: Partial<AuthSettings> = {},
): AuthSettings {
  return {
    databaseUrl:
      "postgresql://auth_runtime:password@127.0.0.1:5432/thesistrace",
    environment: "test",
    host: "127.0.0.1",
    mcpAgentRunMaxWallSeconds: 300,
    mcpAudience: "https://core.test/mcp",
    mcpClientId: "thesistrace-agent",
    mcpClockSkewSeconds: 30,
    mcpGrantScopes: [
      "research:read",
      "research:execute",
      "tracking:read",
      "tracking:execute",
    ],
    mcpIssuer: "https://issuer.test/",
    mcpPrivateJwk: privateJwk,
    mcpPublicJwk: publicJwk,
    mcpTokenLifetimeSeconds: 360,
    port: 8200,
    publicOrigin: "http://127.0.0.1:5173",
    resendApiKey: "test-resend-key",
    resendApiUrl: "http://127.0.0.1:8300",
    resendFromEmail: "ThesisTrace <noreply@thesistrace.test>",
    secret: "0123456789abcdef0123456789abcdef",
    secureCookies: false,
    ...overrides,
  };
}
