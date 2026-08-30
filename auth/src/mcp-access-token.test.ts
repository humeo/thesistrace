import { describe, expect, it, vi } from "vitest";

import { authTestSettings } from "../test-fixtures/auth-settings.js";
import { createMcpAccessTokenIssuer } from "./mcp-access-token.js";

const settings = authTestSettings({
  databaseUrl: "postgresql://auth_runtime:password@postgres/thesistrace",
  host: "0.0.0.0",
  resendApiKey: "resend-test",
  resendFromEmail: "noreply@thesistrace.test",
});

describe("MCP access-token issuer", () => {
  it("asks Auth to sign only the bounded Researcher grant", async () => {
    const sign = vi.fn(async () => ({ token: "signed-token" }));
    const issue = createMcpAccessTokenIssuer(settings, {
      newTokenId: () => "00000000-0000-4000-8000-000000000099",
      now: () => 2_000_000_000_000,
      sign,
    });

    await expect(issue("00000000-0000-4000-8000-000000000001")).resolves.toEqual({
      access_token: "signed-token",
      expires_in: 360,
      token_type: "Bearer",
    });
    expect(sign).toHaveBeenCalledWith({
      client_id: "thesistrace-agent",
      exp: 2_000_000_360,
      iat: 2_000_000_000,
      jti: "00000000-0000-4000-8000-000000000099",
      nbf: 2_000_000_000,
      scope: "research:read research:execute tracking:read tracking:execute",
      sub: "00000000-0000-4000-8000-000000000001",
    });
  });

  it("fails closed for an empty or oversized signer result", async () => {
    for (const token of ["", "x".repeat(16 * 1024 + 1)]) {
      const issue = createMcpAccessTokenIssuer(settings, {
        sign: async () => ({ token }),
      });
      await expect(
        issue("00000000-0000-4000-8000-000000000001"),
      ).rejects.toThrow("MCP_ACCESS_TOKEN_INVALID");
    }
  });
});
