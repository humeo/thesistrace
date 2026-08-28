import { describe, expect, it, vi } from "vitest";

import { createAuthApp, type AuthAppDependencies } from "./app.js";

const activeSession = {
  session: { id: "session-id" },
  user: {
    active: true,
    email: "researcher@example.com",
    id: "00000000-0000-4000-8000-000000000001",
    name: "researcher",
  },
};

function dependencies(
  overrides: Partial<AuthAppDependencies> = {},
): AuthAppDependencies {
  return {
    authHandler: vi.fn(async () =>
      Response.json({ status: "ok" }, { headers: { "set-cookie": "unexpected=1" } }),
    ),
    getSession: vi.fn(async () => activeSession),
    readiness: vi.fn(async () => true),
    ...overrides,
  };
}

describe("Auth HTTP boundary", () => {
  it("delegates the Better Auth operational endpoint", async () => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/ok",
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
    expect(appDependencies.authHandler).toHaveBeenCalledOnce();
  });

  it("rejects direct email signup before Better Auth handles it", async () => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/sign-up/email",
      { method: "POST", body: JSON.stringify({ email: "researcher@example.com" }) },
    );

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ code: "RESEARCHER_INVITATION_REQUIRED" });
    expect(appDependencies.authHandler).not.toHaveBeenCalled();
  });

  it.each(["list-sessions", "update-session", "sign-in/social", "unknown"])(
    "rejects the unapproved Better Auth path: %s",
    async (path) => {
      const appDependencies = dependencies();
      const response = await createAuthApp(appDependencies).request(
        `http://auth.test/api/auth/${path}`,
        { method: "POST" },
      );

      expect(response.status).toBe(404);
      expect(appDependencies.authHandler).not.toHaveBeenCalled();
    },
  );

  it("canonicalizes email before delegating an email-password request", async () => {
    let delegatedBody: unknown;
    const appDependencies = dependencies({
      authHandler: vi.fn(async (request) => {
        delegatedBody = await request.json();
        return Response.json({ status: "ok" });
      }),
    });

    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/sign-in/email",
      {
        body: JSON.stringify({
          email: "  Researcher@Example.COM  ",
          password: "correct-horse-battery-staple",
        }),
        headers: { "content-type": "application/json" },
        method: "POST",
      },
    );

    expect(response.status).toBe(200);
    expect(delegatedBody).toEqual({
      email: "researcher@example.com",
      password: "correct-horse-battery-staple",
    });
  });

  it("rejects an overlong email before Better Auth receives it", async () => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/sign-in/email",
      {
        body: JSON.stringify({ email: `${"a".repeat(255)}@example.com` }),
        headers: { "content-type": "application/json" },
        method: "POST",
      },
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ code: "INVALID_EMAIL" });
    expect(appDependencies.authHandler).not.toHaveBeenCalled();
  });

  it("returns only the verified active Researcher identity", async () => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/internal/session/verify",
      { method: "POST", headers: { cookie: "thesistrace.session=fake" } },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      active: true,
      display_label: "researcher",
      email: "researcher@example.com",
      researcher_id: "00000000-0000-4000-8000-000000000001",
    });
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(appDependencies.getSession).toHaveBeenCalledWith({
      headers: expect.any(Headers),
      query: { disableCookieCache: true, disableRefresh: true },
    });
  });

  it.each([
    ["missing", null],
    ["inactive", { ...activeSession, user: { ...activeSession.user, active: false } }],
  ])("rejects a %s Session", async (_case, session) => {
    const response = await createAuthApp(
      dependencies({ getSession: vi.fn(async () => session) }),
    ).request("http://auth.test/internal/session/verify", { method: "POST" });

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ code: "AUTHENTICATION_REQUIRED" });
  });

  it.each([
    ["malformed", vi.fn(async () => ({ user: { active: true } }))],
    [
      "unavailable",
      vi.fn(async () => {
        throw new Error("private database details");
      }),
    ],
  ])("fails closed when Auth is %s", async (_case, getSession) => {
    const response = await createAuthApp(dependencies({ getSession })).request(
      "http://auth.test/internal/session/verify",
      { method: "POST" },
    );
    const body = await response.text();

    expect(response.status).toBe(503);
    expect(JSON.parse(body)).toEqual({ code: "AUTH_SERVICE_UNAVAILABLE" });
    expect(body).not.toContain("private database details");
  });

  it("keeps liveness dependency-free and readiness database-backed", async () => {
    const app = createAuthApp(dependencies({ readiness: vi.fn(async () => false) }));

    expect((await app.request("http://auth.test/health/live")).status).toBe(200);
    expect((await app.request("http://auth.test/health/ready")).status).toBe(503);
  });

  it("sanitizes an unexpected Better Auth handler failure without logging it", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      const app = createAuthApp(
        dependencies({
          authHandler: vi.fn(async () => {
            throw new Error("cookie-canary token-canary private-database-url");
          }),
        }),
      );

      const response = await app.request(
        "http://auth.test/api/auth/ok?query-canary=do-not-log",
        { headers: { cookie: "cookie-canary=do-not-log" } },
      );

      expect(response.status).toBe(503);
      expect(await response.json()).toEqual({ code: "AUTH_SERVICE_UNAVAILABLE" });
      expect(consoleError).not.toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
  });
});
