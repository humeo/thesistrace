import { describe, expect, it, vi } from "vitest";

import { createAuthApp, type AuthAppDependencies } from "./app.js";
import {
  InvitationRejectedError,
  InvitationServiceUnavailableError,
} from "./invitation.js";
import {
  createAuthHttpObserver,
  type AuthHttpEvent,
} from "./http-observability.js";

const activeSession = {
  session: { id: "session-id" },
  user: {
    active: true,
    email: "researcher@example.com",
    id: "00000000-0000-4000-8000-000000000001",
    name: "researcher",
  },
};
const opaqueInvitationToken =
  "00000000-0000-4000-8000-000000000001." + "a".repeat(43);

function dependencies(
  overrides: Partial<AuthAppDependencies> = {},
): AuthAppDependencies {
  return {
    acceptInvitation: vi.fn(async () => ({
      setCookies: [
        "thesistrace.session_token=session-value; Path=/; HttpOnly; SameSite=Lax",
      ],
    })),
    authHandler: vi.fn(async () =>
      Response.json({ status: "ok" }, { headers: { "set-cookie": "unexpected=1" } }),
    ),
    getSession: vi.fn(async () => activeSession),
    inspectInvitation: vi.fn(async () => ({ email: "researcher@example.com" })),
    consumeInvitationRateLimit: vi.fn(async () => ({
      allowed: true,
      retryAfterSeconds: 0,
    })),
    consumePasswordResetRateLimit: vi.fn(async () => ({
      allowed: true,
      retryAfterSeconds: 0,
    })),
    publicOrigin: "http://auth.test",
    readiness: vi.fn(async () => true),
    resetPassword: vi.fn(async () => undefined),
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

  it("completes Password Reset only through the atomic Auth lifecycle", async () => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/reset-password",
      {
        body: JSON.stringify({
          newPassword: "new-correct-horse-battery-staple",
          token: "reset-token-canary",
        }),
        headers: {
          "content-type": "application/json",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: true });
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(appDependencies.resetPassword).toHaveBeenCalledWith(
      "reset-token-canary",
      "new-correct-horse-battery-staple",
    );
    expect(appDependencies.consumePasswordResetRateLimit).toHaveBeenCalledWith(
      "reset-token-canary",
      expect.any(Headers),
    );
    expect(appDependencies.authHandler).not.toHaveBeenCalled();
  });

  it("rate limits Password Reset before hashing or database mutation", async () => {
    const appDependencies = dependencies({
      consumePasswordResetRateLimit: vi.fn(async () => ({
        allowed: false,
        retryAfterSeconds: 41,
      })),
    });
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/reset-password",
      {
        body: JSON.stringify({
          newPassword: "new-correct-horse-battery-staple",
          token: "reset-token-canary",
        }),
        headers: {
          "content-type": "application/json",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("41");
    expect(await response.json()).toEqual({ code: "AUTH_RATE_LIMITED" });
    expect(appDependencies.resetPassword).not.toHaveBeenCalled();
    expect(appDependencies.authHandler).not.toHaveBeenCalled();
  });

  it("inspects only a server-bound Invitation email", async () => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/researcher-invitation/inspect",
      {
        body: JSON.stringify({ token: opaqueInvitationToken }),
        headers: {
          "content-type": "application/json",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ email: "researcher@example.com" });
    expect(appDependencies.inspectInvitation).toHaveBeenCalledWith(
      opaqueInvitationToken,
    );
    expect(appDependencies.consumeInvitationRateLimit).toHaveBeenCalledWith(
      opaqueInvitationToken,
      expect.any(Headers),
    );
    expect(appDependencies.authHandler).not.toHaveBeenCalled();
  });

  it.each(["application/jsonp", "application/jsonevil", "application/json; invalid"])(
    "rejects the non-JSON Invitation media type %s before account work",
    async (contentType) => {
      const appDependencies = dependencies();
      const response = await createAuthApp(appDependencies).request(
        "http://auth.test/api/auth/researcher-invitation/inspect",
        {
          body: JSON.stringify({ token: opaqueInvitationToken }),
          headers: {
            "content-type": contentType,
            origin: "http://auth.test",
          },
          method: "POST",
        },
      );

      expect(response.status).toBe(400);
      expect(await response.json()).toEqual({ code: "INVITATION_INVALID" });
      expect(appDependencies.inspectInvitation).not.toHaveBeenCalled();
      expect(appDependencies.consumeInvitationRateLimit).not.toHaveBeenCalled();
    },
  );

  it("accepts an Invitation without client-supplied identity and forwards only Cookies", async () => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/researcher-invitation/accept",
      {
        body: JSON.stringify({
          password: "correct-horse-battery-staple",
          token: opaqueInvitationToken,
        }),
        headers: {
          "content-type": "application/json",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: true });
    expect(response.headers.get("set-cookie")).toContain(
      "thesistrace.session_token=session-value",
    );
    expect(appDependencies.acceptInvitation).toHaveBeenCalledWith(
      opaqueInvitationToken,
      "correct-horse-battery-staple",
      expect.any(Headers),
    );
    expect(appDependencies.consumeInvitationRateLimit).toHaveBeenCalledWith(
      opaqueInvitationToken,
      expect.any(Headers),
    );
    expect(appDependencies.authHandler).not.toHaveBeenCalled();
  });

  it.each([
    ["inspect", { email: "attacker@example.com", token: opaqueInvitationToken }],
    [
      "accept",
      {
        name: "attacker-controlled",
        password: "correct-horse-battery-staple",
        token: opaqueInvitationToken,
      },
    ],
    ["accept", { password: "too-short", token: opaqueInvitationToken }],
  ])("rejects a non-exact Invitation %s request", async (path, body) => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      `http://auth.test/api/auth/researcher-invitation/${path}`,
      {
        body: JSON.stringify(body),
        headers: {
          "content-type": "application/json",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ code: "INVITATION_INVALID" });
    expect(appDependencies.inspectInvitation).not.toHaveBeenCalled();
    expect(appDependencies.acceptInvitation).not.toHaveBeenCalled();
  });

  it("sanitizes an invalid Invitation without reflecting a token", async () => {
    const tokenCanary =
      "00000000-0000-4000-8000-000000000001." +
      "token-canary".padEnd(43, "a");
    const response = await createAuthApp(
      dependencies({
        inspectInvitation: vi.fn(async () => {
          throw new InvitationRejectedError();
        }),
      }),
    ).request("http://auth.test/api/auth/researcher-invitation/inspect", {
      body: JSON.stringify({ token: tokenCanary }),
      headers: {
        "content-type": "application/json",
        origin: "http://auth.test",
      },
      method: "POST",
    });

    const body = await response.text();
    expect(response.status).toBe(400);
    expect(JSON.parse(body)).toEqual({ code: "INVITATION_INVALID" });
    expect(body).not.toContain(tokenCanary);
  });

  it("maps an Invitation database failure to a sanitized 503", async () => {
    const response = await createAuthApp(
      dependencies({
        acceptInvitation: vi.fn(async () => {
          throw new InvitationServiceUnavailableError();
        }),
      }),
    ).request("http://auth.test/api/auth/researcher-invitation/accept", {
      body: JSON.stringify({
        password: "correct-horse-battery-staple",
        token: opaqueInvitationToken,
      }),
      headers: {
        "content-type": "application/json",
        origin: "http://auth.test",
      },
      method: "POST",
    });

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ code: "AUTH_SERVICE_UNAVAILABLE" });
  });

  it("rejects a cross-origin Invitation credential request", async () => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/researcher-invitation/accept",
      {
        body: JSON.stringify({
          password: "correct-horse-battery-staple",
          token: opaqueInvitationToken,
        }),
        headers: {
          "content-type": "application/json",
          origin: "https://attacker.example",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ code: "ORIGIN_NOT_ALLOWED" });
    expect(appDependencies.acceptInvitation).not.toHaveBeenCalled();
    expect(appDependencies.consumeInvitationRateLimit).not.toHaveBeenCalled();
  });

  it.each(["inspect", "accept"])(
    "rate limits the Invitation %s endpoint before doing account work",
    async (path) => {
      const appDependencies = dependencies({
        consumeInvitationRateLimit: vi.fn(async () => ({
          allowed: false,
          retryAfterSeconds: 37,
        })),
      });
      const body =
        path === "accept"
          ? {
              password: "correct-horse-battery-staple",
              token: opaqueInvitationToken,
            }
          : { token: opaqueInvitationToken };

      const response = await createAuthApp(appDependencies).request(
        `http://auth.test/api/auth/researcher-invitation/${path}`,
        {
          body: JSON.stringify(body),
          headers: {
            "content-type": "application/json",
            origin: "http://auth.test",
            "x-thesistrace-client-ip": "192.0.2.44",
          },
          method: "POST",
        },
      );

      expect(response.status).toBe(429);
      expect(response.headers.get("retry-after")).toBe("37");
      expect(await response.json()).toEqual({ code: "AUTH_RATE_LIMITED" });
      expect(appDependencies.inspectInvitation).not.toHaveBeenCalled();
      expect(appDependencies.acceptInvitation).not.toHaveBeenCalled();
    },
  );

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
        headers: { "content-type": 'application/json; charset="utf-8"' },
        method: "POST",
      },
    );

    expect(response.status).toBe(200);
    expect(delegatedBody).toEqual({
      email: "researcher@example.com",
      password: "correct-horse-battery-staple",
    });
  });

  it.each(["application/jsonp", "application/jsonevil", "application/json; invalid"])(
    "rejects the non-JSON email-password media type %s before Better Auth",
    async (contentType) => {
      const appDependencies = dependencies();
      const response = await createAuthApp(appDependencies).request(
        "http://auth.test/api/auth/sign-in/email",
        {
          body: JSON.stringify({
            email: "researcher@example.com",
            password: "correct-horse-battery-staple",
          }),
          headers: { "content-type": contentType },
          method: "POST",
        },
      );

      expect(response.status).toBe(400);
      expect(await response.json()).toEqual({ code: "AUTH_REQUEST_INVALID" });
      expect(appDependencies.authHandler).not.toHaveBeenCalled();
    },
  );

  it("forces other-Session revocation on password change", async () => {
    let delegatedBody: unknown;
    const appDependencies = dependencies({
      authHandler: vi.fn(async (request) => {
        delegatedBody = await request.json();
        return Response.json({ status: true });
      }),
    });

    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/change-password",
      {
        body: JSON.stringify({
          currentPassword: "correct-horse-battery-staple",
          newPassword: "new-correct-horse-battery-staple",
        }),
        headers: { "content-type": "application/json" },
        method: "POST",
      },
    );

    expect(response.status).toBe(200);
    expect(delegatedBody).toEqual({
      currentPassword: "correct-horse-battery-staple",
      newPassword: "new-correct-horse-battery-staple",
      revokeOtherSessions: true,
    });
  });

  it.each([
    [
      "sign-in/email",
      {
        email: "researcher@example.com",
        password: "correct-horse-battery-staple",
        rememberMe: true,
      },
    ],
    [
      "request-password-reset",
      {
        email: "researcher@example.com",
        redirectTo: "https://attacker.example",
      },
    ],
    [
      "change-password",
      {
        currentPassword: "correct-horse-battery-staple",
        newPassword: "new-correct-horse-battery-staple",
        revokeOtherSessions: false,
      },
    ],
  ])("rejects client control fields on %s", async (path, body) => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      `http://auth.test/api/auth/${path}`,
      {
        body: JSON.stringify(body),
        headers: { "content-type": "application/json" },
        method: "POST",
      },
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ code: "AUTH_REQUEST_INVALID" });
    expect(appDependencies.authHandler).not.toHaveBeenCalled();
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
    const events: AuthHttpEvent[] = [];
    const ticks = [20, 25][Symbol.iterator]();
    try {
      const app = createAuthApp(
        dependencies({
          authHandler: vi.fn(async () => {
            throw new Error("cookie-canary token-canary private-database-url");
          }),
          httpObserver: createAuthHttpObserver({
            clock: () => new Date("2026-08-29T00:00:00.000Z"),
            monotonicMilliseconds: () => ticks.next().value ?? 25,
            requestIdFactory: () => "00000000-0000-4000-8000-000000000099",
            write: (event) => events.push(event),
          }),
        }),
      );

      const response = await app.request(
        "http://auth.test/api/auth/ok?query-canary=do-not-log",
        { headers: { cookie: "cookie-canary=do-not-log" } },
      );

      expect(response.status).toBe(503);
      expect(await response.json()).toEqual({ code: "AUTH_SERVICE_UNAVAILABLE" });
      expect(response.headers.get("x-request-id")).toBe(
        "00000000-0000-4000-8000-000000000099",
      );
      expect(events).toMatchObject([
        {
          duration_ms: 5,
          http_request_id: "00000000-0000-4000-8000-000000000099",
          method: "GET",
          route: "/api/auth/ok",
          status_code: 503,
        },
      ]);
      expect(JSON.stringify(events)).not.toMatch(
        /cookie-canary|query-canary|token-canary|private-database-url/,
      );
      expect(consoleError).not.toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
  });

  it("emits one sanitized completion while excluding health probes", async () => {
    const events: AuthHttpEvent[] = [];
    const ticks = [10, 13][Symbol.iterator]();
    const app = createAuthApp(
      dependencies({
        httpObserver: createAuthHttpObserver({
          clock: () => new Date("2026-08-29T00:00:00.000Z"),
          monotonicMilliseconds: () => ticks.next().value ?? 13,
          requestIdFactory: () => "00000000-0000-4000-8000-000000000099",
          write: (event) => events.push(event),
        }),
      }),
    );

    expect((await app.request("http://auth.test/health/live")).status).toBe(200);
    const response = await app.request(
      "http://auth.test/api/auth/ok?token=query-canary",
      {
        headers: {
          cookie: "cookie-canary=private",
          "x-request-id": "00000000-0000-4000-8000-000000000001",
        },
      },
    );

    expect(response.headers.get("x-request-id")).toBe(
      "00000000-0000-4000-8000-000000000001",
    );
    expect(events).toMatchObject([
      {
        duration_ms: 3,
        http_request_id: "00000000-0000-4000-8000-000000000001",
        method: "GET",
        route: "/api/auth/ok",
        status_code: 200,
      },
    ]);
    expect(JSON.stringify(events)).not.toMatch(/query-canary|cookie-canary/);
  });
});
