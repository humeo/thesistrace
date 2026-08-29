import { describe, expect, it, vi } from "vitest";

import { createAgentApp, type AgentAppDependencies } from "./app.js";
import { AgentAuthenticationUnavailableError } from "./failure.js";

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
    modelCatalog: catalog,
    publicOrigin: "http://agent.test",
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
});
