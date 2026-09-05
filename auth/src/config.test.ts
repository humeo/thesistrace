import { describe, expect, it } from "vitest";

import { readAuthInitializerSettings, readAuthSettings } from "./config.js";

const mcpPrivateJwk = {
  alg: "EdDSA",
  crv: "Ed25519",
  d: "2SCCVM_DYKEJvq18KV1M4UNFhxTHLKtdXxQFXLGlEBs",
  kid: "test-signing-key-01",
  kty: "OKP",
  use: "sig",
  x: "3d8K_V0qubfzURRlfRFt44Yk4LeNW6HkQMaeiPIhJA8",
};
const mcpPublicJwk = {
  alg: "EdDSA",
  crv: "Ed25519",
  kid: "test-signing-key-01",
  kty: "OKP",
  use: "sig",
  x: "3d8K_V0qubfzURRlfRFt44Yk4LeNW6HkQMaeiPIhJA8",
};
const baseEnvironment = {
  BETTER_AUTH_SECRET: "0123456789abcdef0123456789abcdef",
  RESEND_API_KEY: "test-resend-key",
  RESEND_FROM_EMAIL: "ThesisTrace <noreply@thesistrace.test>",
  THESISTRACE_AUTH_DATABASE_URL:
    "postgresql://auth_runtime:auth-password@postgres:5432/thesistrace",
  THESISTRACE_ENVIRONMENT: "test",
  THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS: "300",
  THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS: "360",
  THESISTRACE_MCP_AGENT_SCOPES:
    '["research:read","research:execute","tracking:read","tracking:execute"]',
  THESISTRACE_MCP_CLIENT_ID: "thesistrace-agent",
  THESISTRACE_MCP_CLOCK_SKEW_SECONDS: "30",
  THESISTRACE_MCP_ISSUER_URL: "http://127.0.0.1:5173/api/auth",
  THESISTRACE_MCP_RESOURCE_URL: "https://core.test/mcp",
  THESISTRACE_MCP_SIGNING_PRIVATE_JWK: JSON.stringify(mcpPrivateJwk),
  THESISTRACE_MCP_VERIFYING_PUBLIC_JWK: JSON.stringify(mcpPublicJwk),
  THESISTRACE_PUBLIC_ORIGIN: "http://127.0.0.1:5173",
  THESISTRACE_RESEND_API_URL: "http://127.0.0.1:8300",
};

const productionEnvironment = {
  ...baseEnvironment,
  BETTER_AUTH_SECRET:
    "a4f781c2d6e9035b8a1f74c092e5bd3680c4f719a2e65b03d8f14c7a9e256bd0",
  THESISTRACE_ENVIRONMENT: "production",
  THESISTRACE_PUBLIC_ORIGIN: "https://thesistrace.test",
  THESISTRACE_MCP_ISSUER_URL: "https://thesistrace.test/api/auth",
  THESISTRACE_RESEND_API_URL: "https://api.resend.com",
};

describe("readAuthSettings", () => {
  it("accepts one exact loopback origin for Test", () => {
    expect(readAuthSettings(baseEnvironment)).toMatchObject({
      environment: "test",
      publicOrigin: "http://127.0.0.1:5173",
      resendApiKey: "test-resend-key",
      resendApiUrl: "http://127.0.0.1:8300",
      resendFromEmail: "ThesisTrace <noreply@thesistrace.test>",
      secureCookies: false,
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
      mcpIssuer: "http://127.0.0.1:5173/api/auth",
      mcpTokenLifetimeSeconds: 360,
    });
  });

  it.each([
    "THESISTRACE_MCP_ISSUER_URL",
    "THESISTRACE_MCP_RESOURCE_URL",
    "THESISTRACE_MCP_CLIENT_ID",
    "THESISTRACE_MCP_AGENT_SCOPES",
    "THESISTRACE_MCP_SIGNING_PRIVATE_JWK",
    "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK",
    "THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS",
    "THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS",
    "THESISTRACE_MCP_CLOCK_SKEW_SECONDS",
  ])("requires the %s MCP setting", (name) => {
    expect(() => readAuthSettings({ ...baseEnvironment, [name]: "" })).toThrow(name);
  });

  it.each([
    '["research:read","research:cancel"]',
    '["tracking:stop"]',
    '["research:read","research:read"]',
    "[]",
    "not-json",
  ])("rejects a dangerous, duplicate, empty, or malformed grant: %s", (grant) => {
    expect(() => readAuthSettings({
      ...baseEnvironment,
      THESISTRACE_MCP_AGENT_SCOPES: grant,
    })).toThrow(/THESISTRACE_MCP_AGENT_SCOPES/);
  });

  it("requires one matching Ed25519 signing and verifying key pair", () => {
    expect(() => readAuthSettings({
      ...baseEnvironment,
      THESISTRACE_MCP_VERIFYING_PUBLIC_JWK: JSON.stringify({
        ...mcpPublicJwk,
        x: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
      }),
    })).toThrow(/key pair/);
    expect(() => readAuthSettings({
      ...baseEnvironment,
      THESISTRACE_MCP_SIGNING_PRIVATE_JWK: JSON.stringify({
        ...mcpPrivateJwk,
        alg: "HS256",
      }),
    })).toThrow(/THESISTRACE_MCP_SIGNING_PRIVATE_JWK/);
    expect(() => readAuthSettings({
      ...baseEnvironment,
      THESISTRACE_MCP_SIGNING_PRIVATE_JWK: JSON.stringify({
        ...mcpPrivateJwk,
        d: `A${mcpPrivateJwk.d.slice(1)}`,
      }),
    })).toThrow(/key pair/);
  });

  it("requires Token lifetime to exceed Run wall time plus skew", () => {
    expect(() => readAuthSettings({
      ...baseEnvironment,
      THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS: "330",
    })).toThrow(/must exceed/);
    expect(readAuthSettings({
      ...baseEnvironment,
      THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS: "331",
    }).mcpTokenLifetimeSeconds).toBe(331);
  });

  it("accepts only the canonical internal Resend fake origin for Compose Test", () => {
    expect(
      readAuthSettings({
        ...baseEnvironment,
        THESISTRACE_RESEND_API_URL: "http://resend-fake:8300",
      }).resendApiUrl,
    ).toBe("http://resend-fake:8300");
  });

  it.each(["RESEND_API_KEY", "RESEND_FROM_EMAIL", "THESISTRACE_RESEND_API_URL"])(
    "requires the %s Resend setting",
    (name) => {
      expect(() => readAuthSettings({ ...baseEnvironment, [name]: "" })).toThrow(name);
    },
  );

  it.each([
    "https://api.resend.com/",
    "https://resend.example.test",
    "http://127.0.0.1:8300",
  ])("rejects a non-canonical Production Resend URL: %s", (resendApiUrl) => {
    expect(() =>
      readAuthSettings({
        ...productionEnvironment,
        THESISTRACE_RESEND_API_URL: resendApiUrl,
      }),
    ).toThrow(/THESISTRACE_RESEND_API_URL/);
  });

  it.each([
    "https://api.resend.com",
    "http://example.test",
    "http://0.0.0.0:8300",
  ])("rejects a non-loopback Test Resend URL: %s", (resendApiUrl) => {
    expect(() =>
      readAuthSettings({
        ...baseEnvironment,
        THESISTRACE_RESEND_API_URL: resendApiUrl,
      }),
    ).toThrow(/THESISTRACE_RESEND_API_URL/);
  });

  it.each([
    "not-an-email",
    "ThesisTrace <not-an-email>",
    "ThesisTrace <noreply@thesistrace.test>\r\nBcc: attacker@example.test",
  ])("rejects an invalid Resend From value", (fromEmail) => {
    expect(() =>
      readAuthSettings({ ...baseEnvironment, RESEND_FROM_EMAIL: fromEmail }),
    ).toThrow(/RESEND_FROM_EMAIL/);
  });

  it.each([
    "http://127.0.0.1:5173/",
    "http://127.0.0.1:5173/path",
    "http://user@example.test",
    "ftp://example.test",
  ])("rejects a non-canonical public origin: %s", (publicOrigin) => {
    expect(() =>
      readAuthSettings({ ...baseEnvironment, THESISTRACE_PUBLIC_ORIGIN: publicOrigin }),
    ).toThrow(/THESISTRACE_PUBLIC_ORIGIN/);
  });

  it.each([
    "http://example.test",
    "https://localhost",
    "https://localhost.",
    "https://admin.localhost",
    "https://admin.localhost.",
    "https://127.0.0.1",
    "https://127.0.0.2",
    "https://0.0.0.0",
    "https://[::1]",
    "https://[::ffff:7f00:1]",
  ])(
    "rejects an insecure or loopback Production origin: %s",
    (publicOrigin) => {
      expect(() =>
        readAuthSettings({
          ...productionEnvironment,
          THESISTRACE_PUBLIC_ORIGIN: publicOrigin,
        }),
      ).toThrow(/THESISTRACE_PUBLIC_ORIGIN/);
    },
  );

  it("accepts one canonical 32-byte hexadecimal Production secret", () => {
    expect(readAuthSettings(productionEnvironment).secret).toBe(
      productionEnvironment.BETTER_AUTH_SECRET,
    );
  });

  it.each([
    "",
    "change-me",
    "01234567890123456789012345678901",
    "0123456789abcdef".repeat(4),
    "00".repeat(32),
    "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
  ])(
    "rejects a missing, non-canonical, or predictable Production secret",
    (secret) => {
      expect(() =>
        readAuthSettings({
          ...productionEnvironment,
          BETTER_AUTH_SECRET: secret,
        }),
      ).toThrow(/BETTER_AUTH_SECRET/);
    },
  );

  it.each([
    "BETTER_AUTH_SECRETS",
    "BETTER_AUTH_TELEMETRY",
    "BETTER_AUTH_TELEMETRY_DEBUG",
    "BETTER_AUTH_TELEMETRY_ENDPOINT",
    "BETTER_AUTH_TELEMETRY_ID",
    "BETTER_AUTH_TRUSTED_ORIGINS",
  ])("rejects Better Auth's ambient override: %s", (name) => {
    expect(() =>
      readAuthSettings({
        ...baseEnvironment,
        [name]: "enabled-by-ambient-environment",
      }),
    ).toThrow(name);
  });

  it("rejects a non-PostgreSQL Auth database URL", () => {
    expect(() =>
      readAuthSettings({
        ...baseEnvironment,
        THESISTRACE_AUTH_DATABASE_URL: "https://database.test",
      }),
    ).toThrow(/THESISTRACE_AUTH_DATABASE_URL/);
  });

  it("requires the isolated Auth runtime database role", () => {
    expect(() =>
      readAuthSettings({
        ...baseEnvironment,
        THESISTRACE_AUTH_DATABASE_URL:
          "postgresql://thesistrace_owner:owner-password@postgres:5432/thesistrace",
      }),
    ).toThrow(/auth_runtime/);
  });

  it.each([
    "postgresql://auth%ZZ_runtime:auth-password@postgres:5432/thesistrace",
    "postgresql://auth_runtime:auth%ZZpassword@postgres:5432/thesistrace",
    "postgresql://auth_runtime:auth-password@postgres:5432/thesis%ZZtrace",
  ])("rejects malformed database URL percent-encoding: %s", (databaseUrl) => {
    expect(() =>
      readAuthSettings({
        ...baseEnvironment,
        THESISTRACE_AUTH_DATABASE_URL: databaseUrl,
      }),
    ).toThrow(/THESISTRACE_AUTH_DATABASE_URL/);
  });
});

describe("readAuthInitializerSettings", () => {
  it("accepts only the owner database role", () => {
    expect(
      readAuthInitializerSettings({
        THESISTRACE_OWNER_DATABASE_URL:
          "postgresql://thesistrace_owner:owner-password@postgres:5432/thesistrace",
      }),
    ).toEqual({
      databaseUrl:
        "postgresql://thesistrace_owner:owner-password@postgres:5432/thesistrace",
    });

    expect(() =>
      readAuthInitializerSettings({
        THESISTRACE_OWNER_DATABASE_URL:
          "postgresql://auth_runtime:auth-password@postgres:5432/thesistrace",
      }),
    ).toThrow(/thesistrace_owner/);
  });
});
