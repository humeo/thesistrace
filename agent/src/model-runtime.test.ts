import { expect, test } from "vitest";

import { RegisteredModelRuntime } from "./model-runtime.js";
import { readModelRegistry } from "./model-registry.js";

const environment = {
  THESISTRACE_AGENT_ANTHROPIC_API_KEY: "anthropic-test",
  THESISTRACE_AGENT_GOOGLE_API_KEY: "google-test",
  THESISTRACE_AGENT_OPENAI_API_KEY: "openai-test",
  THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET: "scripted-test",
};
const registry = readModelRegistry(JSON.stringify({
  default_model_key: "openai",
  models: [
    model("openai", "openai", "openai-test-model", ["none", "high"]),
    model("anthropic", "anthropic", "anthropic-test-model", ["none", "xhigh"]),
    model("google", "google", "google-test-model", ["none", "minimal", "high"]),
    model("scripted", "scripted", "scripted-v1", ["medium"]),
  ],
}), environment);

test("maps each registered provider's supported reasoning contract", () => {
  const runtime = new RegisteredModelRuntime(registry);
  expect(runtime.resolve("openai", "high").providerOptions).toEqual({
    openai: { reasoningEffort: "high" },
  });
  expect(runtime.resolve("anthropic", "none").providerOptions).toEqual({
    anthropic: { thinking: { type: "disabled" } },
  });
  expect(runtime.resolve("anthropic", "xhigh").providerOptions).toEqual({
    anthropic: { effort: "xhigh", thinking: { type: "adaptive" } },
  });
  expect(runtime.resolve("google", "none").providerOptions).toEqual({
    google: { thinkingConfig: { thinkingBudget: 0 } },
  });
  expect(runtime.resolve("google", "minimal").providerOptions).toEqual({
    google: { thinkingConfig: { thinkingLevel: "minimal" } },
  });
  expect(runtime.resolve("scripted", "medium").providerOptions).toEqual({});
});

test("rejects a model or effort not enabled by the startup registry", () => {
  const runtime = new RegisteredModelRuntime(registry);
  expect(() => runtime.resolve("missing", "high")).toThrow();
  expect(() => runtime.resolve("anthropic", "minimal")).toThrow();
});

function model(
  key: string,
  provider: "anthropic" | "google" | "openai" | "scripted",
  providerModelId: string,
  efforts: string[],
) {
  const secret = {
    anthropic: "THESISTRACE_AGENT_ANTHROPIC_API_KEY",
    google: "THESISTRACE_AGENT_GOOGLE_API_KEY",
    openai: "THESISTRACE_AGENT_OPENAI_API_KEY",
    scripted: "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET",
  }[provider];
  return {
    default_reasoning_effort: efforts[0],
    display_name: key[0]?.toUpperCase() + key.slice(1),
    enabled: true,
    key,
    provider_adapter: provider,
    provider_model_id: providerModelId,
    reasoning_efforts: efforts,
    secret_env: secret,
  };
}
