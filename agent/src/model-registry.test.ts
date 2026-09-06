import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import { readModelRegistry } from "./model-registry.js";

const validRegistry = {
  default_model_key: "openai-primary",
  models: [
    {
      context_window: 258_000,
      default_reasoning_effort: "medium",
      display_name: "OpenAI Primary",
      enabled: true,
      key: "openai-primary",
      provider_adapter: "openai",
      provider_model_id: "gpt-research",
      reasoning_efforts: ["low", "medium", "high"],
      secret_env: "THESISTRACE_AGENT_OPENAI_API_KEY",
    },
    {
      context_window: 128_000,
      default_reasoning_effort: "high",
      display_name: "Anthropic Analyst",
      enabled: true,
      key: "anthropic-analyst",
      provider_adapter: "anthropic",
      provider_model_id: "claude-research",
      reasoning_efforts: ["high"],
      secret_env: "THESISTRACE_AGENT_ANTHROPIC_API_KEY",
    },
    {
      context_window: 32_768,
      default_reasoning_effort: "none",
      display_name: "Disabled Model",
      enabled: false,
      key: "disabled-model",
      provider_adapter: "google",
      provider_model_id: "gemini-disabled",
      reasoning_efforts: ["none"],
      secret_env: "THESISTRACE_AGENT_GOOGLE_API_KEY",
    },
  ],
};
const environment = {
  THESISTRACE_AGENT_ANTHROPIC_API_KEY: "provider-secret-b-canary",
  THESISTRACE_AGENT_OPENAI_API_KEY: "provider-secret-a-canary",
};

function encoded(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({ ...validRegistry, ...overrides });
}

describe("model Registry", () => {
  it("reads each model's context capacity and requires a valid explicit budget", () => {
    const registry = readModelRegistry(encoded(), environment);
    expect(registry.models.map((model) => model.contextWindow)).toEqual([258_000, 128_000, 32_768]);
    for (const context_window of [undefined, 0, -1, 8192, 65_536.5]) {
      expect(() => readModelRegistry(encoded({
        models: [{ ...validRegistry.models[0], context_window }],
      }), environment)).toThrow("Agent configuration is invalid");
    }
  });
  it("publishes every configured Luna effort from the maintained model file", () => {
    const registry = readModelRegistry(
      readFileSync(new URL("../../config/model-registry.json", import.meta.url), "utf8"),
      environment,
    );
    expect(registry.safeCatalog.models[0]).toMatchObject({
      key: "gpt-5.6-luna",
      default_reasoning_effort: "high",
      reasoning_efforts: ["none", "low", "medium", "high", "xhigh", "max"],
    });
    expect(registry.models[0]?.contextWindow).toBe(258_000);
  });
  it("builds one safe multi-provider Catalog and omits disabled models", () => {
    const registry = readModelRegistry(encoded(), environment);

    expect(registry.defaultModelKey).toBe("openai-primary");
    expect(registry.models).toHaveLength(3);
    expect(registry.safeCatalog).toEqual({
      default_model_key: "openai-primary",
      models: [
        {
          default_reasoning_effort: "medium",
          display_name: "OpenAI Primary",
          key: "openai-primary",
          reasoning_efforts: ["low", "medium", "high"],
        },
        {
          default_reasoning_effort: "high",
          display_name: "Anthropic Analyst",
          key: "anthropic-analyst",
          reasoning_efforts: ["high"],
        },
      ],
    });
    const catalog = JSON.stringify(registry.safeCatalog);
    expect(catalog).not.toContain("provider_adapter");
    expect(catalog).not.toContain("provider_model_id");
    expect(catalog).not.toContain("secret_env");
    expect(catalog).not.toContain("THESISTRACE_AGENT_OPENAI_API_KEY");
    expect(catalog).not.toContain("provider-secret-a-canary");
  });

  it.each([
    ["malformed JSON", "{"],
    ["missing default", encoded({ default_model_key: "missing" })],
    ["empty model list", encoded({ models: [] })],
    [
      "duplicate key",
      encoded({
        models: [validRegistry.models[0], { ...validRegistry.models[1], key: "openai-primary" }],
      }),
    ],
    [
      "ambiguous display identity",
      encoded({
        models: [
          validRegistry.models[0],
          { ...validRegistry.models[1], display_name: "OPENAI PRIMARY" },
        ],
      }),
    ],
    [
      "unknown Adapter",
      encoded({
        models: [{ ...validRegistry.models[0], provider_adapter: "unknown" }],
      }),
    ],
    [
      "empty Provider model ID",
      encoded({
        models: [{ ...validRegistry.models[0], provider_model_id: "" }],
      }),
    ],
    [
      "empty reasoning set",
      encoded({ models: [{ ...validRegistry.models[0], reasoning_efforts: [] }] }),
    ],
    [
      "unsupported reasoning label",
      encoded({
        models: [{ ...validRegistry.models[0], reasoning_efforts: ["automatic"] }],
      }),
    ],
    [
      "duplicate reasoning label",
      encoded({
        models: [{ ...validRegistry.models[0], reasoning_efforts: ["low", "low"] }],
      }),
    ],
    [
      "invalid default reasoning",
      encoded({
        models: [{ ...validRegistry.models[0], default_reasoning_effort: "xhigh" }],
      }),
    ],
    [
      "disabled default",
      encoded({
        models: [{ ...validRegistry.models[0], enabled: false }],
      }),
    ],
    [
      "non-canonical display name",
      encoded({ models: [{ ...validRegistry.models[0], display_name: " OpenAI" }] }),
    ],
    [
      "control character in display name",
      encoded({ models: [{ ...validRegistry.models[0], display_name: "OpenAI\nPrimary" }] }),
    ],
    [
      "format character in Provider model ID",
      encoded({
        models: [{ ...validRegistry.models[0], provider_model_id: "gpt-\u202eresearch" }],
      }),
    ],
    [
      "Adapter Secret mismatch",
      encoded({
        models: [{
          ...validRegistry.models[0],
          secret_env: "THESISTRACE_AGENT_ANTHROPIC_API_KEY",
        }],
      }),
    ],
  ])("rejects the whole Registry for %s", (_name, source) => {
    expect(() => readModelRegistry(source, environment)).toThrow(
      "Agent configuration is invalid",
    );
  });

  it("fails startup when an enabled model's Provider credential is missing", () => {
    expect(() => readModelRegistry(encoded(), {
      THESISTRACE_AGENT_OPENAI_API_KEY: "present",
    })).toThrow(
      "Agent configuration is invalid",
    );
  });

  it.each(["/private/model", "https://provider.test/model?key=private", "model private"])(
    "rejects non-identifier Provider metadata",
    (providerModelId) => {
      expect(() => readModelRegistry(encoded({ models: [{ ...validRegistry.models[0], provider_model_id: providerModelId }] }), environment))
        .toThrow("Agent configuration is invalid");
    },
  );
});
