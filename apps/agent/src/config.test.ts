import { describe, expect, it } from "vitest";

import { readAgentInitializerSettings, readAgentSettings } from "./config.js";

const registry = JSON.stringify({
  min_compaction_context_window: 65_536, default_model_key: "scripted",
  models: [{
    default_reasoning_effort: "medium",
    display_name: "Scripted Research Model",
    enabled: true,
    key: "scripted",
    provider_adapter: "scripted",
    provider_model_id: "scripted-v1",
    reasoning_efforts: ["low", "medium", "high"],
    context_window: 65_536, max_output_tokens: 128_000, pricing_usd_per_million_tokens: { input: 0, cache_read: 0, cache_write: 0, output: 0 }, secret_env: "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET",
  }],
});
const environment = {
  THESISTRACE_AGENT_BUILD_REVISION: "test-build-1",
  THESISTRACE_AGENT_DATABASE_URL:
    "postgresql://agent_runtime:agent-password@postgres:5432/thesistrace",
  THESISTRACE_AGENT_MODEL_REGISTRY: registry,
  THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET: "scripted-test-secret",
  THESISTRACE_AUTH_INTERNAL_ORIGIN: "http://auth:8200",
  THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS: "300",
  THESISTRACE_ENVIRONMENT: "test",
  THESISTRACE_MCP_CLOCK_SKEW_SECONDS: "30",
  THESISTRACE_MCP_INTERNAL_URL: "http://api:8100/mcp",
  THESISTRACE_PUBLIC_ORIGIN: "http://127.0.0.1:5173",
};

describe("Agent Host configuration", () => {
  it("reads one exact Test configuration and validated Registry", () => {
    expect(readAgentSettings(environment)).toMatchObject({
      agentBuildRevision: "test-build-1",
      authInternalOrigin: "http://auth:8200",
      environment: "test",
      host: "0.0.0.0",
      mcpClockSkewSeconds: 30,
      mcpInternalUrl: "http://api:8100/mcp",
      port: 8400,
      publicOrigin: "http://127.0.0.1:5173",
      runMaxWallSeconds: 300,
      databaseUrl:
        "postgresql://agent_runtime:agent-password@postgres:5432/thesistrace",
    });
  });

  it.each([
    "THESISTRACE_AGENT_BUILD_REVISION",
    "THESISTRACE_AGENT_DATABASE_URL",
    "THESISTRACE_AGENT_MODEL_REGISTRY",
    "THESISTRACE_AUTH_INTERNAL_ORIGIN",
    "THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS",
    "THESISTRACE_ENVIRONMENT",
    "THESISTRACE_MCP_CLOCK_SKEW_SECONDS",
    "THESISTRACE_MCP_INTERNAL_URL",
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

  it.each([
    "http://api:8100/mcp/",
    "http://api:8100/mcp?token=canary",
    "http://user@api:8100/mcp",
    "http://api:8100/other",
  ])("rejects a non-canonical MCP URL: %s", (mcpUrl) => {
    expect(() => readAgentSettings({
      ...environment,
      THESISTRACE_MCP_INTERNAL_URL: mcpUrl,
    })).toThrow("Agent configuration is invalid");
  });

  it("bounds the Run wall time and MCP clock skew", () => {
    for (const [name, value] of [
      ["THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS", "0"],
      ["THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS", "3601"],
      ["THESISTRACE_MCP_CLOCK_SKEW_SECONDS", "301"],
      ["THESISTRACE_MCP_CLOCK_SKEW_SECONDS", "-1"],
    ] as const) {
      expect(() => readAgentSettings({ ...environment, [name]: value })).toThrow(
        "Agent configuration is invalid",
      );
    }
  });

  it("requires HTTPS and a non-loopback hostname in Production", () => {
    const productionRegistry = JSON.stringify({
      min_compaction_context_window: 65_536, default_model_key: "openai-research",
      models: [{
        default_reasoning_effort: "high",
        display_name: "OpenAI Research",
        enabled: true,
        key: "openai-research",
        provider_adapter: "openai",
        provider_model_id: "gpt-research",
        reasoning_efforts: ["high"],
        context_window: 65_536, max_output_tokens: 128_000, pricing_usd_per_million_tokens: { input: 0, cache_read: 0, cache_write: 0, output: 0 }, secret_env: "THESISTRACE_AGENT_OPENAI_API_KEY",
      }],
    });
    const productionEnvironment = {
      ...environment,
      THESISTRACE_AGENT_MODEL_REGISTRY: productionRegistry,
      THESISTRACE_AGENT_OPENAI_API_KEY: "production-provider-secret",
      THESISTRACE_ENVIRONMENT: "production",
    };
    expect(
      readAgentSettings({
        ...productionEnvironment,
        THESISTRACE_PUBLIC_ORIGIN: "https://thesistrace.test",
      }).publicOrigin,
    ).toBe("https://thesistrace.test");
    expect(() =>
      readAgentSettings({
        ...productionEnvironment,
        THESISTRACE_PUBLIC_ORIGIN: "https://127.0.0.1",
      }),
    ).toThrow("Agent configuration is invalid");
  });

  it("rejects the Scripted test Provider in Production", () => {
    expect(() => readAgentSettings({
      ...environment,
      THESISTRACE_ENVIRONMENT: "production",
      THESISTRACE_PUBLIC_ORIGIN: "https://thesistrace.test",
    })).toThrow("Agent configuration is invalid");
  });
});
