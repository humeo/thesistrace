import { expect, test, vi } from "vitest";

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
    openai: { reasoningEffort: "high", serviceTier: "default", store: false },
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

test("continues OpenAI tool results without relying on provider-side stored items", async () => {
  const lunaRegistry = readModelRegistry(JSON.stringify({
    default_model_key: "luna",
    models: [model("luna", "openai", "gpt-5.6-luna", ["high"])],
  }), environment);
  const requests: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", async (_url: unknown, init: RequestInit) => {
    const body = JSON.parse(String(init.body));
    requests.push(body);
    // This external stateless service cannot resolve another request's IDs.
    // The synthetic refusal reproduces the real failed continuation boundary.
    if (body.store !== false || body.input.some((item: { type: string }) => item.type === "item_reference")) {
      return Response.json({ error: { type: "invalid_request_error", message: "Item not found in stateless service." } }, { status: 404 });
    }
    return Response.json({
      id: "resp_stateless_fixture", created_at: 1_788_148_800, model: "gpt-5.6-luna",
      output: [{ type: "message", id: "msg_stateless_fixture", role: "assistant",
        content: [{ type: "output_text", text: "Value: 17", annotations: [] }] }],
      usage: { input_tokens: 20, output_tokens: 4, output_tokens_details: { reasoning_tokens: 0 } },
    });
  });
  try {
    const selection = new RegisteredModelRuntime(lunaRegistry).resolve("luna", "high");
    const result = await selection.languageModel.doGenerate({
      providerOptions: selection.providerOptions,
      prompt: [
        { role: "user", content: [{ type: "text", text: "Read and report the value." }] },
        { role: "assistant", content: [
          { type: "reasoning", text: "Read the authoritative value before answering.",
            providerOptions: { openai: { itemId: "rs_stateless_fixture", reasoningEncryptedContent: "encrypted-fixture" } } },
          { type: "tool-call", toolCallId: "call_stateless_fixture", toolName: "read_value", input: "{}" },
        ] },
        { role: "tool", content: [{ type: "tool-result", toolCallId: "call_stateless_fixture",
          toolName: "read_value", output: { type: "json", value: { value: 17 } } }] },
      ],
    });
    expect(result.content).toMatchObject([{ type: "text", text: "Value: 17" }]);
    expect(requests).toMatchObject([{
      store: false, include: ["reasoning.encrypted_content"],
      reasoning: { effort: "high" },
      input: [
        { role: "user" },
        { type: "reasoning", encrypted_content: "encrypted-fixture" },
        { type: "function_call", call_id: "call_stateless_fixture" },
        { type: "function_call_output", call_id: "call_stateless_fixture" },
      ],
    }]);
  } finally {
    vi.unstubAllGlobals();
  }
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
