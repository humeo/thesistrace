import { describe, expect, it, vi } from "vitest";

import { ResearcherNotFoundError } from "./access.js";
import { createAuthApp, type AuthAppDependencies } from "./app.js";
import {
  InvitationRejectedError,
  InvitationServiceUnavailableError,
} from "./invitation.js";
import {
  createAuthHttpObserver,
  type AuthHttpEvent,
} from "./http-observability.js";
import { OperatorAccessNotFoundError } from "./operator-directory.js";
import {
  OperatorCodeInvalidError,
  OperatorProofInvalidError,
} from "./operator-proof.js";
import { OperatorSessionTargetProtectedError } from "./operator-session-revocation.js";

const activeSession = {
  session: { id: "00000000-0000-4000-8000-000000000010" },
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
    confirmOperatorProof: vi.fn(async () => ({
      expiresAt: "2026-08-29T06:01:00.000Z",
      proof: opaqueInvitationToken,
    })),
    consumeOperatorProof: vi.fn(async () => undefined),
    issueMcpAccessToken: vi.fn(async () => ({
      access_token: "opaque-signed-token",
      expires_in: 360,
      token_type: "Bearer" as const,
    })),
    consumeInvitationRateLimit: vi.fn(async () => ({
      allowed: true,
      retryAfterSeconds: 0,
    })),
    consumeOperatorProofRateLimit: vi.fn(async () => ({
      allowed: true,
      retryAfterSeconds: 0,
    })),

    getSession: vi.fn(async () => activeSession),
    isOperator: vi.fn(async () => false),
    hasOperatorCapability: vi.fn(async () => true),
    inspectInvitation: vi.fn(async () => ({ email: "researcher@example.com" })),
    issueOperatorInvitation: vi.fn(async (_principal, input) => ({
      email: input.email,
      invitationId: "00000000-0000-4000-8000-000000000041",
      status: "delivered" as const,
    })),
    listOperatorInvitations: vi.fn(async () => ({
      items: [],
      nextCursor: null,
    })),
    listOperatorResearchers: vi.fn(async () => ({
      items: [],
      nextCursor: null,
    })),
    publicOrigin: "http://auth.test",
    readiness: vi.fn(async () => true),
    reissueOperatorInvitation: vi.fn(async (_principal, input) => ({
      email: input.email,
      invitationId: "00000000-0000-4000-8000-000000000042",
      status: "delivered" as const,
    })),
    revokeOperatorResearcherSessions: vi.fn(async (_principal, input) => ({
      researcherId: input.researcherId,
      revokedSessionCount: 2,
      status: "updated" as const,
    })),
    ...overrides,
  };
}

describe("Auth HTTP boundary", () => {
  it("returns live quota policy and fails closed when Auth cannot resolve it", async () => {
    const isOperator = vi.fn(async () => true);
    const app = createAuthApp(dependencies({ isOperator }));
    const path = "/internal/researchers/00000000-0000-4000-8000-000000000001/quota-policy";
    expect(await (await app.request(`http://auth.test${path}`)).json()).toEqual({ timezone: "Asia/Shanghai", daily_model_budget_nanodollars: null, daily_run_limit: null, active_daily_track_limit: null });
    isOperator.mockResolvedValueOnce(false);
    expect(await (await app.request(`http://auth.test${path}`)).json()).toEqual({ timezone: "Asia/Shanghai", daily_model_budget_nanodollars: 1_000_000_000, daily_run_limit: 10, active_daily_track_limit: 3 });
    isOperator.mockRejectedValueOnce(new Error("database unavailable"));
    expect((await app.request(`http://auth.test${path}`)).status).toBe(503);
    expect((await app.request("http://auth.test/internal/researchers/invalid/quota-policy")).status).toBe(400);
  });
  it("exchanges only a freshly database-verified Active Session", async () => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/internal/session/exchange",
      {
        headers: { cookie: "thesistrace.session_token=session-canary" },
        method: "POST",
      },
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({
      access_token: "opaque-signed-token",
      expires_in: 360,
      token_type: "Bearer",
    });
    expect(appDependencies.getSession).toHaveBeenCalledWith({
      headers: expect.any(Headers),
      query: { disableCookieCache: true, disableRefresh: true },
    });
    expect(appDependencies.issueMcpAccessToken).toHaveBeenCalledWith(
      activeSession.user.id,
    );
  });

  it("does not issue an MCP token for an invalid, Inactive, or unavailable Session", async () => {
    const scenarios = [
      { expected: 401, getSession: vi.fn(async () => null) },
      {
        expected: 401,
        getSession: vi.fn(async () => ({
          ...activeSession,
          user: { ...activeSession.user, active: false },
        })),
      },
      {
        expected: 503,
        getSession: vi.fn(async () => {
          throw new Error("database unavailable canary");
        }),
      },
    ] as const;
    for (const scenario of scenarios) {
      const appDependencies = dependencies({ getSession: scenario.getSession });
      const response = await createAuthApp(appDependencies).request(
        "http://auth.test/internal/session/exchange",
        { method: "POST" },
      );
      expect(response.status).toBe(scenario.expected);
      expect(appDependencies.issueMcpAccessToken).not.toHaveBeenCalled();
    }
  });

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

  it("confirms one target-bound Session proof and never forwards its otp", async () => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);
    const otp = "123456";
    const researcherId = "00000000-0000-4000-8000-000000000002";
    const confirmation = await app.request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          operation: "researcher.sessions.revoke",
          otp,
          researcher_id: researcherId,
        }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(confirmation.status).toBe(200);
    expect(appDependencies.confirmOperatorProof).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      {
        operation: "researcher.sessions.revoke",
        otp,
        researcherId,
      },
    );

    const mutation = await app.request(
      "http://auth.test/api/auth/operator/researchers/sessions/revoke",
      {
        body: JSON.stringify({
          proof: opaqueInvitationToken,
          researcher_id: researcherId,
        }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(mutation.status).toBe(200);
    expect(await mutation.json()).toEqual({
      researcher_id: researcherId,
      revoked_session_count: 2,
      status: "updated",
    });
    expect(appDependencies.revokeOperatorResearcherSessions).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      { proof: opaqueInvitationToken, researcherId },
    );
    expect(
      JSON.stringify(
        vi.mocked(appDependencies.revokeOperatorResearcherSessions).mock.calls,
      ),
    ).not.toContain(otp);
  });

  it("rejects a non-exact Session revocation before mutation", async () => {
    const appDependencies = dependencies();
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/operator/researchers/sessions/revoke",
      {
        body: JSON.stringify({
          password: "must-not-cross-this-boundary",
          proof: opaqueInvitationToken,
          researcher_id: "00000000-0000-4000-8000-000000000002",
        }),
        headers: {
          "content-type": "application/json",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ code: "OPERATOR_REQUEST_INVALID" });
    expect(appDependencies.revokeOperatorResearcherSessions).not.toHaveBeenCalled();
  });

  it.each([
    [
      "invalid proof",
      new OperatorProofInvalidError(),
      400,
      "OPERATOR_PROOF_INVALID",
    ],
    [
      "protected target",
      new OperatorSessionTargetProtectedError(),
      409,
      "OPERATOR_SESSION_TARGET_PROTECTED",
    ],
    [
      "stale target",
      new ResearcherNotFoundError(),
      409,
      "OPERATOR_SESSION_TARGET_INVALID",
    ],
  ] as const)(
    "sanitizes a %s Session revocation",
    async (_case, error, status, code) => {
      const response = await createAuthApp(
        dependencies({
          revokeOperatorResearcherSessions: vi.fn(async () => {
            throw error;
          }),
        }),
      ).request(
        "http://auth.test/api/auth/operator/researchers/sessions/revoke",
        {
          body: JSON.stringify({
            proof: opaqueInvitationToken,
            researcher_id: "00000000-0000-4000-8000-000000000002",
          }),
          headers: {
            "content-type": "application/json",
            origin: "http://auth.test",
          },
          method: "POST",
        },
      );

      expect(response.status).toBe(status);
      expect(await response.json()).toEqual({ code });
    },
  );

  it("rejects every cross-origin Operator mutation before its handler", async () => {
    for (const { body, path } of [
      {
        body: {
          email: "researcher@example.com",
          operation: "invitation.issue",
          otp: "123456",
        },
        path: "/api/auth/operator/proofs",
      },
      {
        body: { email: "researcher@example.com", proof: opaqueInvitationToken },
        path: "/api/auth/operator/invitations/issue",
      },
      {
        body: { email: "researcher@example.com", proof: opaqueInvitationToken },
        path: "/api/auth/operator/invitations/reissue",
      },
    ]) {
      const appDependencies = dependencies();
      const response = await createAuthApp(appDependencies).request(
        `http://auth.test${path}`,
        {
          body: JSON.stringify(body),
          headers: {
            "content-type": "application/json",
            origin: "https://attacker.example",
          },
          method: "POST",
        },
      );

      expect(response.status).toBe(403);
      expect(await response.json()).toEqual({ code: "ORIGIN_NOT_ALLOWED" });
      expect(appDependencies.confirmOperatorProof).not.toHaveBeenCalled();
      expect(appDependencies.issueOperatorInvitation).not.toHaveBeenCalled();
      expect(appDependencies.reissueOperatorInvitation).not.toHaveBeenCalled();
    }
  });

  it("rate limits proof confirmation before otp verification", async () => {
    const appDependencies = dependencies({
      consumeOperatorProofRateLimit: vi.fn(async () => ({
        allowed: false,
        retryAfterSeconds: 37,
      })),
    });
    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          email: "researcher@example.com",
          operation: "invitation.issue",
          otp: "123456",
        }),
        headers: {
          "content-type": "application/json",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("37");
    expect(await response.json()).toEqual({ code: "AUTH_RATE_LIMITED" });
    expect(appDependencies.confirmOperatorProof).not.toHaveBeenCalled();
  });

  it("uses the Python boundary-whitespace set for Unicode Market keys", async () => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);
    const request = async (idempotencyKey: string) => app.request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          as_of: "2026-08-11T18:00:00+08:00",
          idempotency_key: idempotencyKey,
          operation: "data.refresh.market.submit",
          otp: "123456",
        }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect((await request("\uFEFFmarket-key")).status).toBe(200);
    vi.mocked(appDependencies.confirmOperatorProof).mockClear();
    expect((await request("\u0085market-key")).status).toBe(400);
    expect(appDependencies.confirmOperatorProof).not.toHaveBeenCalled();
  });

  it.each(["reset-password", "request-password-reset", "change-password", "sign-in/email", "list-sessions", "update-session", "sign-in/social", "unknown"])(
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

  it("canonicalizes email before delegating an email-code request", async () => {
    let delegatedBody: unknown;
    const appDependencies = dependencies({
      authHandler: vi.fn(async (request) => {
        delegatedBody = await request.json();
        return Response.json({ status: "ok" });
      }),
    });

    const response = await createAuthApp(appDependencies).request(
      "http://auth.test/api/auth/sign-in/email-otp",
      {
        body: JSON.stringify({
          email: "  Researcher@Example.COM  ",
          otp: "123456",
        }),
        headers: { "content-type": 'application/json; charset="utf-8"', origin: "http://auth.test" },
        method: "POST",
      },
    );

    expect(response.status).toBe(200);
    expect(delegatedBody).toEqual({
      email: "researcher@example.com",
      otp: "123456",
    });
  });

  it.each(["application/jsonp", "application/jsonevil", "application/json; invalid"])(
    "rejects the non-JSON email-code media type %s before Better Auth",
    async (contentType) => {
      const appDependencies = dependencies();
      const response = await createAuthApp(appDependencies).request(
        "http://auth.test/api/auth/sign-in/email-otp",
        {
          body: JSON.stringify({
            email: "researcher@example.com",
            otp: "123456",
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

  it.each([
    ["sign-in/email-otp", {email: "researcher@example.com", otp: "123456", rememberMe: true}],
    ["sign-in/email-otp", {email: "researcher@example.com", otp: "123456", active: true}],
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
      "http://auth.test/api/auth/sign-in/email-otp",
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

  it("admits the Operator page check and exposes only read-only projections", async () => {
    const appDependencies = dependencies({
      listOperatorResearchers: vi.fn(async () => ({
        items: [{
          active: true,
          createdAt: "2026-08-28T00:00:00.000Z",
          currentSessionCount: 2,
          displayLabel: "Researcher",
          effectiveInvitation: null,
          email: "researcher@example.com",
          id: "00000000-0000-4000-8000-000000000001",
          latestSuccessfulLoginAt: null,
        }],
        nextCursor: "opaque-cursor",
      })),
    });
    const app = createAuthApp(appDependencies);

    expect((await app.request(
      "http://auth.test/internal/operator/page-access",
      { headers: { cookie: "session=fake" } },
    )).status).toBe(204);
    const capability = await app.request(
      "http://auth.test/api/auth/operator/capability",
      { headers: { cookie: "session=fake" } },
    );
    expect(capability.status).toBe(200);
    expect(await capability.json()).toEqual({ operator: true });
    const researchers = await app.request(
      "http://auth.test/api/auth/operator/researchers?search=Research&cursor=opaque",
      { headers: { cookie: "session=fake" } },
    );
    expect(researchers.status).toBe(200);
    expect(await researchers.json()).toEqual({
      items: [{
        active: true,
        created_at: "2026-08-28T00:00:00.000Z",
        current_session_count: 2,
        display_label: "Researcher",
        effective_invitation: null,
        email: "researcher@example.com",
        latest_successful_login_at: null,
        researcher_id: "00000000-0000-4000-8000-000000000001",
      }],
      next_cursor: "opaque-cursor",
    });
    expect(appDependencies.listOperatorResearchers).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      { cursor: "opaque", search: "Research" },
    );
  });

  it("confirms and privately consumes one exact Market submission proof", async () => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);
    const request = {
      as_of: "2026-08-11T18:00:00+08:00",
      idempotency_key: "market-20260811T180000+0800",
      operation: "data.refresh.market.submit",
    } as const;
    const confirmation = await app.request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          ...request,
          otp: "123456",
        }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(confirmation.status).toBe(200);
    expect(appDependencies.confirmOperatorProof).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      {
        asOf: request.as_of,
        idempotencyKey: request.idempotency_key,
        operation: request.operation,
        otp: "123456",
      },
    );

    const consumed = await app.request(
      "http://auth.test/internal/operator/proofs/consume",
      {
        body: JSON.stringify({ ...request, proof: opaqueInvitationToken }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
        },
        method: "POST",
      },
    );

    expect(consumed.status).toBe(204);
    expect(appDependencies.consumeOperatorProof).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      {
        asOf: request.as_of,
        idempotencyKey: request.idempotency_key,
        operation: request.operation,
        proof: opaqueInvitationToken,
      },
    );
  });

  it("confirms and privately consumes one exact Financial submission proof", async () => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);
    const request = {
      idempotency_key: "financial-20260814-custom",
      observation_through_session: "2026-08-14",
      operation: "data.refresh.financial.submit",
    } as const;
    const confirmation = await app.request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          ...request,
          otp: "123456",
        }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(confirmation.status).toBe(200);
    expect(appDependencies.confirmOperatorProof).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      {
        idempotencyKey: request.idempotency_key,
        observationThroughSession: request.observation_through_session,
        operation: request.operation,
        otp: "123456",
      },
    );

    const consumed = await app.request(
      "http://auth.test/internal/operator/proofs/consume",
      {
        body: JSON.stringify({ ...request, proof: opaqueInvitationToken }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
        },
        method: "POST",
      },
    );

    expect(consumed.status).toBe(204);
    expect(appDependencies.consumeOperatorProof).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      {
        idempotencyKey: request.idempotency_key,
        observationThroughSession: request.observation_through_session,
        operation: request.operation,
        proof: opaqueInvitationToken,
      },
    );
  });

  it("confirms and privately consumes one exact Industry submission proof", async () => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);
    const request = {
      idempotency_key: "industry-20260814-custom",
      observation_through_session: "2026-08-14",
      operation: "data.refresh.industry.submit",
    } as const;
    const confirmation = await app.request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          ...request,
          otp: "123456",
        }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(confirmation.status).toBe(200);
    expect(appDependencies.confirmOperatorProof).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      {
        idempotencyKey: request.idempotency_key,
        observationThroughSession: request.observation_through_session,
        operation: request.operation,
        otp: "123456",
      },
    );

    const consumed = await app.request(
      "http://auth.test/internal/operator/proofs/consume",
      {
        body: JSON.stringify({ ...request, proof: opaqueInvitationToken }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
        },
        method: "POST",
      },
    );

    expect(consumed.status).toBe(204);
    expect(appDependencies.consumeOperatorProof).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      {
        idempotencyKey: request.idempotency_key,
        observationThroughSession: request.observation_through_session,
        operation: request.operation,
        proof: opaqueInvitationToken,
      },
    );
  });

  it.each([
    {
      expected: {
        kind: "market",
        operation: "data.refresh.cancel",
        sourceIdempotencyKey: "market-cancel-source",
        target: "2026-08-11T10:00:00+00:00",
      },
      request: {
        kind: "market",
        operation: "data.refresh.cancel",
        source_idempotency_key: "market-cancel-source",
        target: "2026-08-11T10:00:00+00:00",
      },
    },
    {
      expected: {
        kind: "industry",
        newIdempotencyKey: "industry-retry-new",
        operation: "data.refresh.retry",
        sourceIdempotencyKey: "industry-failed-source",
        target: "2026-08-14",
      },
      request: {
        kind: "industry",
        new_idempotency_key: "industry-retry-new",
        operation: "data.refresh.retry",
        source_idempotency_key: "industry-failed-source",
        target: "2026-08-14",
      },
    },
  ] as const)("confirms and privately consumes exact $request.operation proof", async ({
    expected,
    request,
  }) => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);
    const confirmation = await app.request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          ...request,
          otp: "123456",
        }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(confirmation.status).toBe(200);
    expect(appDependencies.confirmOperatorProof).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      { ...expected, otp: "123456" },
    );

    const consumed = await app.request(
      "http://auth.test/internal/operator/proofs/consume",
      {
        body: JSON.stringify({ ...request, proof: opaqueInvitationToken }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
        },
        method: "POST",
      },
    );

    expect(consumed.status).toBe(204);
    expect(appDependencies.consumeOperatorProof).toHaveBeenCalledWith(
      {
        researcherId: "00000000-0000-4000-8000-000000000001",
        sessionId: "00000000-0000-4000-8000-000000000010",
      },
      { ...expected, proof: opaqueInvitationToken },
    );
  });

  it("rejects malformed action target at both proof HTTP boundaries", async () => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);
    const request = {
      kind: "market",
      operation: "data.refresh.cancel",
      source_idempotency_key: "market-cancel-source",
      target: "2026-08-11",
    } as const;
    const headers = {
      "content-type": "application/json",
      cookie: "operator=fake",
      origin: "http://auth.test",
    };

    const confirmation = await app.request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          ...request,
          otp: "123456",
        }),
        headers,
        method: "POST",
      },
    );
    const consumption = await app.request(
      "http://auth.test/internal/operator/proofs/consume",
      {
        body: JSON.stringify({ ...request, proof: opaqueInvitationToken }),
        headers,
        method: "POST",
      },
    );

    expect(confirmation.status).toBe(400);
    expect(consumption.status).toBe(400);
    expect(appDependencies.confirmOperatorProof).not.toHaveBeenCalled();
    expect(appDependencies.consumeOperatorProof).not.toHaveBeenCalled();
  });

  it("rejects year zero at both Financial proof HTTP boundaries", async () => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);
    const request = {
      idempotency_key: "financial-year-zero",
      observation_through_session: "0000-01-01",
      operation: "data.refresh.financial.submit",
    } as const;
    const headers = {
      "content-type": "application/json",
      cookie: "operator=fake",
      origin: "http://auth.test",
    };

    const confirmation = await app.request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          ...request,
          otp: "123456",
        }),
        headers,
        method: "POST",
      },
    );
    const consumption = await app.request(
      "http://auth.test/internal/operator/proofs/consume",
      {
        body: JSON.stringify({ ...request, proof: opaqueInvitationToken }),
        headers,
        method: "POST",
      },
    );

    expect(confirmation.status).toBe(400);
    expect(consumption.status).toBe(400);
    expect(appDependencies.confirmOperatorProof).not.toHaveBeenCalled();
    expect(appDependencies.consumeOperatorProof).not.toHaveBeenCalled();
  });

  it("counts Unicode Market keys by characters at both Auth proof boundaries", async () => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);
    const request = {
      as_of: "2026-08-11T18:00:00+08:00",
      idempotency_key: "market-刷新",
      operation: "data.refresh.market.submit",
    } as const;
    const headers = {
      "content-type": "application/json",
      cookie: "operator=fake",
      origin: "http://auth.test",
    };

    const confirmation = await app.request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          ...request,
          otp: "123456",
        }),
        headers,
        method: "POST",
      },
    );
    const consumption = await app.request(
      "http://auth.test/internal/operator/proofs/consume",
      {
        body: JSON.stringify({ ...request, proof: opaqueInvitationToken }),
        headers,
        method: "POST",
      },
    );

    expect(confirmation.status).toBe(200);
    expect(consumption.status).toBe(204);
    expect(appDependencies.confirmOperatorProof).toHaveBeenCalled();
    expect(appDependencies.consumeOperatorProof).toHaveBeenCalled();
  });

  it.each([
    "market-\0-key",
    `market-${String.fromCharCode(0xD800)}-key`,
  ])("rejects PostgreSQL-incompatible key %j before proof work", async (key) => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);
    const response = await app.request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          as_of: "2026-08-11T18:00:00+08:00",
          idempotency_key: key,
          operation: "data.refresh.market.submit",
          otp: "123456",
        }),
        headers: {
          "content-type": "application/json",
          cookie: "operator=fake",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(400);
    expect(appDependencies.confirmOperatorProof).not.toHaveBeenCalled();
  });

  it.each([
    ["issue", "invitation.issue"],
    ["reissue", "invitation.reissue"],
  ] as const)(
    "confirms the exact %s request and never forwards the otp to mutation",
    async (path, operation) => {
      const appDependencies = dependencies();
      const app = createAuthApp(appDependencies);
      const otp = "123456";
      const confirmation = await app.request(
        "http://auth.test/api/auth/operator/proofs",
        {
          body: JSON.stringify({
            email: " Researcher@Example.COM ",
            operation,
            otp,
          }),
          headers: {
            "content-type": "application/json",
            cookie: "operator=fake",
            origin: "http://auth.test",
          },
          method: "POST",
        },
      );

      expect(confirmation.status).toBe(200);
      expect(await confirmation.json()).toEqual({
        expires_at: "2026-08-29T06:01:00.000Z",
        proof: opaqueInvitationToken,
      });
      expect(appDependencies.confirmOperatorProof).toHaveBeenCalledWith(
        {
          researcherId: "00000000-0000-4000-8000-000000000001",
          sessionId: "00000000-0000-4000-8000-000000000010",
        },
        { email: "researcher@example.com", operation, otp },
      );

      const mutation = await app.request(
        `http://auth.test/api/auth/operator/invitations/${path}`,
        {
          body: JSON.stringify({
            email: " Researcher@Example.COM ",
            proof: opaqueInvitationToken,
          }),
          headers: {
            "content-type": "application/json",
            cookie: "operator=fake",
            origin: "http://auth.test",
          },
          method: "POST",
        },
      );

      expect(mutation.status).toBe(200);
      expect(await mutation.json()).toMatchObject({
        email: "researcher@example.com",
        status: "delivered",
      });
      const mutationHandler = path === "issue"
        ? appDependencies.issueOperatorInvitation
        : appDependencies.reissueOperatorInvitation;
      expect(mutationHandler).toHaveBeenCalledWith(
        {
          researcherId: "00000000-0000-4000-8000-000000000001",
          sessionId: "00000000-0000-4000-8000-000000000010",
        },
        { email: "researcher@example.com", proof: opaqueInvitationToken },
      );
      expect(JSON.stringify(vi.mocked(mutationHandler).mock.calls)).not.toContain(
        otp,
      );
    },
  );

  it("maps otp and proof rejection without exposing an Operator surface", async () => {
    const invalidPassword = dependencies({
      confirmOperatorProof: vi.fn(async () => {
        throw new OperatorCodeInvalidError();
      }),
    });
    const otpResponse = await createAuthApp(invalidPassword).request(
      "http://auth.test/api/auth/operator/proofs",
      {
        body: JSON.stringify({
          email: "researcher@example.com",
          operation: "invitation.issue",
          otp: "000000",
        }),
        headers: {
          "content-type": "application/json",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );
    expect(otpResponse.status).toBe(400);
    expect(await otpResponse.json()).toEqual({
      code: "OPERATOR_CODE_INVALID",
    });

    const invalidProof = dependencies({
      issueOperatorInvitation: vi.fn(async () => {
        throw new OperatorProofInvalidError();
      }),
    });
    const proofResponse = await createAuthApp(invalidProof).request(
      "http://auth.test/api/auth/operator/invitations/issue",
      {
        body: JSON.stringify({
          email: "researcher@example.com",
          proof: opaqueInvitationToken,
        }),
        headers: {
          "content-type": "application/json",
          origin: "http://auth.test",
        },
        method: "POST",
      },
    );
    expect(proofResponse.status).toBe(400);
    expect(await proofResponse.json()).toEqual({ code: "OPERATOR_PROOF_INVALID" });
  });

  it("returns an empty 404 for every ordinary-Researcher Operator boundary", async () => {
    const appDependencies = dependencies({
      hasOperatorCapability: vi.fn(async () => false),
      listOperatorInvitations: vi.fn(async () => {
        throw new OperatorAccessNotFoundError();
      }),
      listOperatorResearchers: vi.fn(async () => {
        throw new OperatorAccessNotFoundError();
      }),
    });
    const app = createAuthApp(appDependencies);

    for (const path of [
      "/internal/operator/page-access",
      "/internal/operator/proofs/consume",
      "/api/auth/operator/capability",
      "/api/auth/operator/researchers",
      "/api/auth/operator/invitations",
    ]) {
      const response = await app.request(`http://auth.test${path}`, {
        body: path.endsWith("/consume") ? JSON.stringify({}) : undefined,
        headers: path.endsWith("/consume")
          ? { "content-type": "application/json", cookie: "ordinary=fake" }
          : { cookie: "ordinary=fake" },
        method: path.endsWith("/consume") ? "POST" : "GET",
      });
      expect(response.status).toBe(404);
      expect(await response.text()).toBe("");
    }
    for (const path of [
      "/api/auth/operator/proofs",
      "/api/auth/operator/invitations/issue",
      "/api/auth/operator/invitations/reissue",
      "/api/auth/operator/researchers/sessions/revoke",
    ]) {
      const response = await app.request(`http://auth.test${path}`, {
        body: JSON.stringify({}),
        headers: {
          "content-type": "application/json",
          cookie: "ordinary=fake",
          origin: "https://attacker.example",
        },
        method: "POST",
      });
      expect(response.status).toBe(404);
      expect(await response.text()).toBe("");
    }
  });

  it("rejects malformed Operator list queries without calling the projection", async () => {
    const appDependencies = dependencies();
    const app = createAuthApp(appDependencies);

    const response = await app.request(
      "http://auth.test/api/auth/operator/researchers?search=a&search=b",
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ code: "OPERATOR_REQUEST_INVALID" });
    expect(appDependencies.listOperatorResearchers).not.toHaveBeenCalled();
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
