import { describe, expect, it, vi } from "vitest";

import {
  createMcpTokenExchanger,
  McpRunPreparationError,
} from "./mcp-token-exchanger.js";

describe("private MCP token exchange", () => {
  it("forwards only the Login Session Cookie and accepts sufficient lifetime", async () => {
    const fetch = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      expect(new Headers(init?.headers)).toEqual(
        new Headers({ cookie: "thesistrace.session_token=session-canary" }),
      );
      return Response.json({
        access_token: "opaque-access-token",
        expires_in: 360,
        token_type: "Bearer",
      });
    });
    const exchange = createMcpTokenExchanger({
      authInternalOrigin: "http://auth:8200",
      clockSkewSeconds: 30,
      fetch,
      runMaxWallSeconds: 300,
    });
    const headers = new Headers({
      authorization: "browser-auth-canary",
      cookie: "analytics=discard-me; thesistrace.session_token=session-canary; preference=discard-me-too",
      origin: "https://attacker.test",
    });

    await expect(exchange(headers)).resolves.toEqual({
      access_token: "opaque-access-token",
      expires_in: 360,
      token_type: "Bearer",
    });
    expect(fetch).toHaveBeenCalledWith(
      "http://auth:8200/internal/session/exchange",
      expect.objectContaining({ method: "POST", redirect: "error" }),
    );
  });

  it("prefers the secure production Login Session Cookie when both names arrive", async () => {
    const fetch = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("cookie")).toBe(
        "__Secure-thesistrace.session_token=secure-session",
      );
      return Response.json({
        access_token: "opaque-access-token",
        expires_in: 360,
        token_type: "Bearer",
      });
    });
    const exchange = createMcpTokenExchanger({
      authInternalOrigin: "http://auth:8200",
      clockSkewSeconds: 30,
      fetch,
      runMaxWallSeconds: 300,
    });

    await exchange(new Headers({
      cookie: "thesistrace.session_token=discarded; __Secure-thesistrace.session_token=secure-session",
    }));
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("fails closed for Auth errors, malformed responses, and short lifetime", async () => {
    const responses = [
      new Response(null, { status: 401 }),
      Response.json({ code: "AUTH_SERVICE_UNAVAILABLE" }, { status: 503 }),
      Response.json({ access_token: "token", expires_in: 330, token_type: "Bearer" }),
      Response.json({ access_token: "token", expires_in: 360, token_type: "bearer" }),
      new Response("not-json"),
    ];
    for (const response of responses) {
      const exchange = createMcpTokenExchanger({
        authInternalOrigin: "http://auth:8200",
        clockSkewSeconds: 30,
        fetch: async () => response,
        runMaxWallSeconds: 300,
      });
      await expect(exchange(new Headers())).rejects.toBeInstanceOf(
        McpRunPreparationError,
      );
    }
  });

  it("requires sufficient remaining lifetime after the exchange completes", async () => {
    const clock = vi.fn()
      .mockReturnValueOnce(10_000)
      .mockReturnValueOnce(10_001);
    const exchange = createMcpTokenExchanger({
      authInternalOrigin: "http://auth:8200",
      clockSkewSeconds: 30,
      fetch: async () => Response.json({
        access_token: "opaque-access-token",
        expires_in: 331,
        token_type: "Bearer",
      }),
      now: clock,
      runMaxWallSeconds: 300,
    });

    await expect(exchange(new Headers())).rejects.toBeInstanceOf(
      McpRunPreparationError,
    );
    expect(clock).toHaveBeenCalledTimes(2);
  });

  it("accepts a token whose conservative remaining lifetime exceeds the Run budget", async () => {
    const clock = vi.fn()
      .mockReturnValueOnce(10_000)
      .mockReturnValueOnce(11_500);
    const exchange = createMcpTokenExchanger({
      authInternalOrigin: "http://auth:8200",
      clockSkewSeconds: 30,
      fetch: async () => Response.json({
        access_token: "opaque-access-token",
        expires_in: 333,
        token_type: "Bearer",
      }),
      now: clock,
      runMaxWallSeconds: 300,
    });

    await expect(exchange(new Headers())).resolves.toMatchObject({
      access_token: "opaque-access-token",
      expires_in: 333,
    });
  });

  it("fails closed when the monotonic exchange clock is invalid", async () => {
    const exchange = createMcpTokenExchanger({
      authInternalOrigin: "http://auth:8200",
      clockSkewSeconds: 30,
      fetch: async () => Response.json({
        access_token: "opaque-access-token",
        expires_in: 360,
        token_type: "Bearer",
      }),
      now: vi.fn().mockReturnValueOnce(20).mockReturnValueOnce(19),
      runMaxWallSeconds: 300,
    });

    await expect(exchange(new Headers())).rejects.toBeInstanceOf(
      McpRunPreparationError,
    );
  });

  it("maps timeout or disconnect to one safe preparation error", async () => {
    const exchange = createMcpTokenExchanger({
      authInternalOrigin: "http://auth:8200",
      clockSkewSeconds: 30,
      fetch: async () => {
        throw new Error("raw network failure with token canary");
      },
      runMaxWallSeconds: 300,
    });
    await expect(exchange(new Headers())).rejects.toEqual(
      new McpRunPreparationError(),
    );
  });
});
