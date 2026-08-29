import { describe, expect, it } from "vitest";

import { readAgentInitializerSettings, readAgentSettings } from "./config.js";

const registry = JSON.stringify({
  default_model_key: "scripted",
  models: [{
    default_reasoning_effort: "medium",
    display_name: "Scripted Research Model",
    enabled: true,
    key: "scripted",
    provider_adapter: "scripted",
    provider_model_id: "scripted-v1",
    reasoning_efforts: ["low", "medium", "high"],
    secret_env: "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET",
  }],
});
const environment = {
  THESISTRACE_AGENT_BUILD_REVISION: "test-build-1",
  THESISTRACE_AGENT_DATABASE_URL:
    "postgresql://agent_runtime:agent-password@postgres:5432/thesistrace",
  THESISTRACE_AGENT_MODEL_REGISTRY: registry,
  THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET: "scripted-test-secret",
  THESISTRACE_AUTH_INTERNAL_ORIGIN: "http://auth:8200",
  THESISTRACE_ENVIRONMENT: "test",
  THESISTRACE_PUBLIC_ORIGIN: "http://127.0.0.1:5173",
};

describe("Agent Host configuration", () => {
  it("reads one exact Test configuration and validated Registry", () => {
    expect(readAgentSettings(environment)).toMatchObject({
      agentBuildRevision: "test-build-1",
      authInternalOrigin: "http://auth:8200",
      environment: "test",
      host: "0.0.0.0",
      port: 8400,
      publicOrigin: "http://127.0.0.1:5173",
      databaseUrl:
        "postgresql://agent_runtime:agent-password@postgres:5432/thesistrace",
    });
  });

  it.each([
    "THESISTRACE_AGENT_BUILD_REVISION",
    "THESISTRACE_AGENT_DATABASE_URL",
    "THESISTRACE_AGENT_MODEL_REGISTRY",
    "THESISTRACE_AUTH_INTERNAL_ORIGIN",
    "THESISTRACE_ENVIRONMENT",
    "THESISTRACE_PUBLIC_ORIGIN",
  ])("requires %s", (name) => {
    expect(() => readAgentSettings({ ...environment, [name]: "" })).toThrow(
      "Agent configuration is invalid",
    );
  });

  it("requires the dedicated Runtime and Owner database roles", () => {
    expect(() => readAgentSettings({
      ...environment,
      THESISTRACE_AGENT_DATABASE_URL:
        "postgresql://auth_runtime:agent-password@postgres:5432/thesistrace",
    })).toThrow("Agent configuration is invalid");

    expect(readAgentInitializerSettings({
      THESISTRACE_OWNER_DATABASE_URL:
        "postgresql://thesistrace_owner:owner-password@postgres:5432/thesistrace",
    })).toEqual({
      databaseUrl:
        "postgresql://thesistrace_owner:owner-password@postgres:5432/thesistrace",
    });
  });

  it.each([
    "http://127.0.0.1:5173/",
    "https://127.0.0.1:5173",
    "http://example.test",
  ])("rejects a non-canonical Test public Origin: %s", (publicOrigin) => {
    expect(() =>
      readAgentSettings({ ...environment, THESISTRACE_PUBLIC_ORIGIN: publicOrigin }),
    ).toThrow("Agent configuration is invalid");
  });

  it.each(["http://auth:8200/", "http://user@auth:8200", "not-an-origin"])(
    "rejects a non-canonical Auth Origin: %s",
    (authOrigin) => {
      expect(() =>
        readAgentSettings({
          ...environment,
          THESISTRACE_AUTH_INTERNAL_ORIGIN: authOrigin,
        }),
      ).toThrow("Agent configuration is invalid");
    },
  );

  it("requires HTTPS and a non-loopback hostname in Production", () => {
    expect(
      readAgentSettings({
        ...environment,
        THESISTRACE_ENVIRONMENT: "production",
        THESISTRACE_PUBLIC_ORIGIN: "https://thesistrace.test",
      }).publicOrigin,
    ).toBe("https://thesistrace.test");
    expect(() =>
      readAgentSettings({
        ...environment,
        THESISTRACE_ENVIRONMENT: "production",
        THESISTRACE_PUBLIC_ORIGIN: "https://127.0.0.1",
      }),
    ).toThrow("Agent configuration is invalid");
  });
});
