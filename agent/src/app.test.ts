import { describe, expect, it, vi } from "vitest";

import { createAgentApp, type AgentAppDependencies } from "./app.js";
import { AgentAuthenticationUnavailableError } from "./failure.js";
import { encodeSessionCursor } from "./session-management.js";
import {
  SessionActiveRunError,
  SessionNotFoundError,
  SessionVersionConflictError,
} from "./session-repository.js";

const researcher = {
  active: true as const,
  display_label: "Researcher",
  email: "researcher@example.test",
  researcher_id: "00000000-0000-4000-8000-000000000001",
};
const catalog = {
  default_model_key: "research-primary",
  models: [{
    default_reasoning_effort: "medium" as const,
    display_name: "Research Primary",
    key: "research-primary",
    reasoning_efforts: ["low", "medium", "high"] as const,
  }],
};

function dependencies(
  overrides: Partial<AgentAppDependencies> = {},
): AgentAppDependencies {
  return {
    commandReceipt: vi.fn(async (_threadId, commandId) => ({
      commandId,
      errorCode: null,
      kind: "steer" as const,
      status: "accepted" as const,
      turnId: "00000000-0000-4000-8000-000000000222",
    })),
    deleteSession: vi.fn(async () => undefined),
    handleRuntime: vi.fn(async () => new Response("runtime-response")),
    modelCatalog: catalog,
    publicOrigin: "http://agent.test",
    renameSession: vi.fn(async (threadId, _researcher, title) => ({
      id: threadId,
      title,
      version: "2026-08-30T02:03:05.000Z",
    })),
    session: vi.fn(async (threadId) => ({
      activityAt: "2026-08-30T02:03:04.000000Z",
      createdAt: "2026-08-29T02:03:04.000000Z",
      currentTurn: null,
      id: threadId,
      latestTurn: null,
      title: "Quality Alpha",
      version: "2026-08-30T02:03:05.000Z",
    })),
    sessions: vi.fn(async () => ({
      nextCursor: null,
      sessions: [],
    })),
    steer: vi.fn(async (_threadId, _researcher, input) => ({
      commandId: input.inputId,
      errorCode: null,
      kind: "steer" as const,
      status: "accepted" as const,
      turnId: input.expectedTurnId,
    })),
    stop: vi.fn(async (_threadId, _researcher, input) => ({
      commandId: input.commandId,
      errorCode: null,
      kind: "stop" as const,
      status: "accepted" as const,
      turnId: input.expectedTurnId,
    })),
    timeline: vi.fn(async () => ({ entries: [], nextCursor: null })),
    sessionPreference: vi.fn(async () => ({
      model_key: "research-primary",
      reasoning_effort: "medium",
    })),
    verifySession: vi.fn(async () => researcher),
    ...overrides,
  };
}

describe("Agent Host HTTP boundary", () => {
  it("returns the safe Catalog only after same-origin Session verification", async () => {
    const appDependencies = dependencies();
    const response = await createAgentApp(appDependencies).request(
      "http://agent.test/api/agent/models",
      {
        headers: {
          cookie: "thesistrace.session_token=session-canary",
          "sec-fetch-site": "same-origin",
        },
      },
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual(catalog);
    expect(appDependencies.verifySession).toHaveBeenCalledOnce();
  });

  it("accepts an exact Origin and rejects a wrong or unverifiable Origin first", async () => {
    const appDependencies = dependencies();
    const app = createAgentApp(appDependencies);
    const exact = await app.request("http://agent.test/api/agent/models", {
      headers: { origin: "http://agent.test" },
    });
    const wrong = await app.request("http://agent.test/api/agent/models", {
      headers: {
        origin: "https://attacker.example",
        "sec-fetch-site": "same-origin",
      },
    });
    const missing = await app.request("http://agent.test/api/agent/models");

    expect(exact.status).toBe(200);
    expect(wrong.status).toBe(403);
    expect(await wrong.json()).toEqual({ code: "ORIGIN_NOT_ALLOWED" });
    expect(missing.status).toBe(403);
    expect(appDependencies.verifySession).toHaveBeenCalledTimes(1);
  });

  it("fails closed for a missing or unavailable Auth Session", async () => {
    const missing = await createAgentApp(dependencies({
      verifySession: vi.fn(async () => null),
    })).request("http://agent.test/api/agent/models", {
      headers: { origin: "http://agent.test" },
    });
    const unavailable = await createAgentApp(dependencies({
      verifySession: vi.fn(async () => {
        throw new AgentAuthenticationUnavailableError();
      }),
    })).request("http://agent.test/api/agent/models", {
      headers: { origin: "http://agent.test" },
    });

    expect(missing.status).toBe(401);
    expect(await missing.json()).toEqual({ code: "AUTHENTICATION_REQUIRED" });
    expect(unavailable.status).toBe(503);
    expect(await unavailable.json()).toEqual({ code: "AUTH_SERVICE_UNAVAILABLE" });
  });

  it("never serializes Provider identity, Secret references, or Secret values", async () => {
    const response = await createAgentApp(dependencies()).request(
      "http://agent.test/api/agent/models",
      { headers: { origin: "http://agent.test" } },
    );
    const body = await response.text();

    expect(body).not.toContain("provider_model_id");
    expect(body).not.toContain("provider_adapter");
    expect(body).not.toContain("secret_env");
    expect(body).not.toContain("PROVIDER_SECRET_CANARY");
    expect(body).not.toContain("provider-secret-value-canary");
  });

  it("keeps liveness and readiness private but deterministic", async () => {
    const app = createAgentApp(dependencies({ readiness: vi.fn(async () => false) }));

    expect((await app.request("http://agent.test/health/live")).status).toBe(200);
    const readiness = await app.request("http://agent.test/health/ready");
    expect(readiness.status).toBe(503);
    expect(await readiness.json()).toEqual({ status: "unavailable" });
  });

  it("protects and delegates the CopilotKit runtime with verified identity", async () => {
    const appDependencies = dependencies();
    const response = await createAgentApp(appDependencies).request(
      "http://agent.test/api/agent/copilotkit/info",
      { headers: { origin: "http://agent.test" } },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("runtime-response");
    expect(appDependencies.handleRuntime).toHaveBeenCalledWith(
      expect.any(Request),
      researcher,
    );
  });

  it("returns only an owned Session preference and hides absent Sessions", async () => {
    const appDependencies = dependencies();
    const app = createAgentApp(appDependencies);
    const owned = await app.request(
      "http://agent.test/api/agent/sessions/00000000-0000-4000-8000-000000000111/preferences",
      { headers: { origin: "http://agent.test" } },
    );
    expect(owned.status).toBe(200);
    expect(await owned.json()).toEqual({
      model_key: "research-primary",
      reasoning_effort: "medium",
    });
    expect(appDependencies.sessionPreference).toHaveBeenCalledWith(
      "00000000-0000-4000-8000-000000000111",
      researcher,
    );

    const hidden = await createAgentApp(dependencies({
      sessionPreference: vi.fn(async () => null),
    })).request(
      "http://agent.test/api/agent/sessions/00000000-0000-4000-8000-000000000999/preferences",
      { headers: { origin: "http://agent.test" } },
    );
    expect(hidden.status).toBe(404);
    expect(await hidden.json()).toEqual({ code: "CHAT_SESSION_NOT_FOUND" });
  });

  it("distinguishes product storage failure from runtime service availability", async () => {
    const response = await createAgentApp(dependencies({
      session: vi.fn(async () => {
        throw new Error("private database diagnostic");
      }),
    })).request(
      "http://agent.test/api/agent/sessions/00000000-0000-4000-8000-000000000222",
      { headers: { origin: "http://agent.test" } },
    );

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ code: "CHAT_STORAGE_FAILURE" });
  });

  it("lists one bounded owner-scoped Session page with an opaque cursor", async () => {
    const nextCursor = encodeSessionCursor({
      activityAt: "2026-08-29T01:02:03.000000Z",
      id: "00000000-0000-4000-8000-000000000111",
    });
    const sessions = vi.fn(async () => ({
      nextCursor,
      sessions: [{
        activityAt: "2026-08-30T01:02:03.000000Z",
        createdAt: "2026-08-29T01:02:03.000000Z",
        currentTurn: null,
        id: "00000000-0000-4000-8000-000000000222",
        latestTurn: null,
        title: "Quality Alpha",
        version: "2026-08-30T01:02:04.000Z",
      }],
    }));
    const response = await createAgentApp(dependencies({ sessions })).request(
      "http://agent.test/api/agent/sessions",
      { headers: { origin: "http://agent.test" } },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      next_cursor: nextCursor,
      sessions: [{
        activity_at: "2026-08-30T01:02:03.000000Z",
        created_at: "2026-08-29T01:02:03.000000Z",
        current_turn: null,
        id: "00000000-0000-4000-8000-000000000222",
        latest_turn: null,
        title: "Quality Alpha",
        version: "2026-08-30T01:02:04.000Z",
      }],
    });
    expect(sessions).toHaveBeenCalledWith(undefined, researcher);

    const invalid = await createAgentApp(dependencies({ sessions })).request(
      "http://agent.test/api/agent/sessions?page=1",
      { headers: { origin: "http://agent.test" } },
    );
    expect(invalid.status).toBe(400);
    expect(await invalid.json()).toEqual({ code: "INVALID_CHAT_SESSION_REQUEST" });
    expect(sessions).toHaveBeenCalledOnce();
  });

  it("loads one owned Session for a direct URL without enumerating history", async () => {
    const threadId = "00000000-0000-4000-8000-000000000222";
    const appDependencies = dependencies();
    const response = await createAgentApp(appDependencies).request(
      `http://agent.test/api/agent/sessions/${threadId}`,
      { headers: { origin: "http://agent.test" } },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      activity_at: "2026-08-30T02:03:04.000000Z",
      created_at: "2026-08-29T02:03:04.000000Z",
      current_turn: null,
      id: threadId,
      latest_turn: null,
      title: "Quality Alpha",
      version: "2026-08-30T02:03:05.000Z",
    });
    expect(appDependencies.session).toHaveBeenCalledWith(threadId, researcher);

    const hidden = await createAgentApp(dependencies({
      session: vi.fn(async () => {
        throw new SessionNotFoundError();
      }),
    })).request(
      `http://agent.test/api/agent/sessions/${threadId}`,
      { headers: { origin: "http://agent.test" } },
    );
    expect(hidden.status).toBe(404);
    expect(await hidden.json()).toEqual({ code: "CHAT_SESSION_NOT_FOUND" });
  });

  it("renames one owned Session with optimistic concurrency", async () => {
    const renameSession = vi.fn(async (threadId, _researcher, title) => ({
      id: threadId,
      title,
      version: "2026-08-30T02:03:05.000Z",
    }));
    const response = await createAgentApp(dependencies({ renameSession })).request(
      "http://agent.test/api/agent/sessions/00000000-0000-4000-8000-000000000111",
      {
        body: JSON.stringify({
          title: "Quality Alpha",
          version: "2026-08-30T02:03:04.000Z",
        }),
        headers: {
          "content-type": "application/json",
          origin: "http://agent.test",
        },
        method: "PATCH",
      },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      id: "00000000-0000-4000-8000-000000000111",
      title: "Quality Alpha",
      version: "2026-08-30T02:03:05.000Z",
    });
    expect(renameSession).toHaveBeenCalledWith(
      "00000000-0000-4000-8000-000000000111",
      researcher,
      "Quality Alpha",
      new Date("2026-08-30T02:03:04.000Z"),
    );
  });

  it("bounds a streamed rename body before parsing or calling storage", async () => {
    const renameSession = vi.fn();
    const encoded = new TextEncoder().encode(JSON.stringify({
      title: "a".repeat(2_000),
      version: "2026-08-30T02:03:04.000Z",
    }));
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoded.slice(0, 700));
        controller.enqueue(encoded.slice(700, 1_400));
        controller.enqueue(encoded.slice(1_400));
        controller.close();
      },
    });
    const request = new Request(
      "http://agent.test/api/agent/sessions/00000000-0000-4000-8000-000000000111",
      {
        body,
        duplex: "half",
        headers: {
          "content-type": "application/json",
          origin: "http://agent.test",
        },
        method: "PATCH",
      } as RequestInit & { duplex: "half" },
    );

    const response = await createAgentApp(dependencies({ renameSession })).request(request);

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ code: "INVALID_CHAT_SESSION_REQUEST" });
    expect(renameSession).not.toHaveBeenCalled();
  });

  it.each([
    [new SessionNotFoundError(), 404, "CHAT_SESSION_NOT_FOUND"],
    [new SessionVersionConflictError(), 409, "CHAT_SESSION_CHANGED"],
    [new SessionActiveRunError(), 409, "CHAT_SESSION_RUN_ACTIVE"],
  ] as const)("maps Session management errors without leaking storage", async (
    error,
    status,
    code,
  ) => {
    const rename = await createAgentApp(dependencies({
      renameSession: vi.fn(async () => {
        throw error;
      }),
    })).request(
      "http://agent.test/api/agent/sessions/00000000-0000-4000-8000-000000000111",
      {
        body: JSON.stringify({
          title: "Quality Alpha",
          version: "2026-08-30T02:03:04.000Z",
        }),
        headers: { "content-type": "application/json", origin: "http://agent.test" },
        method: "PATCH",
      },
    );

    const body = await rename.text();
    expect(rename.status).toBe(status);
    expect(JSON.parse(body)).toEqual({ code });
    expect(body).not.toContain("storage");
  });

  it("deletes only an idle owned Chat Session through the management dependency", async () => {
    const deleteSession = vi.fn(async () => undefined);
    const response = await createAgentApp(dependencies({ deleteSession })).request(
      "http://agent.test/api/agent/sessions/00000000-0000-4000-8000-000000000111",
      { headers: { origin: "http://agent.test" }, method: "DELETE" },
    );
    expect(response.status).toBe(204);
    expect(await response.text()).toBe("");
    expect(deleteSession).toHaveBeenCalledWith(
      "00000000-0000-4000-8000-000000000111",
      researcher,
    );

    const active = await createAgentApp(dependencies({
      deleteSession: vi.fn(async () => {
        throw new SessionActiveRunError();
      }),
    })).request(
      "http://agent.test/api/agent/sessions/00000000-0000-4000-8000-000000000111",
      { headers: { origin: "http://agent.test" }, method: "DELETE" },
    );
    expect(active.status).toBe(409);
    expect(await active.json()).toEqual({ code: "CHAT_SESSION_RUN_ACTIVE" });
  });
});
