import { createOpenAI } from "@ai-sdk/openai";
import { createAnthropic } from "@ai-sdk/anthropic";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { afterEach, expect, it, vi } from "vitest";
import { MeteredLanguageModel } from "./metered-language-model.js";
import type { RegisteredModel } from "./model-registry.js";
import { AgentRunFailure } from "./run-failure.js";

const model: RegisteredModel = { key: "fixture", displayName: "Fixture", enabled: true,
  providerAdapter: "openai", providerModelId: "gpt-5.6-luna", credential: "fixture",
  defaultReasoningEffort: "none", reasoningEfforts: ["none"], contextWindow: 258000, maxOutputTokens: 128000,
  pricing: { input: 200, cacheRead: 20, cacheWrite: 200, output: 1200 } };
const options = { maxOutputTokens: 100, providerOptions: { openai: { store: false, serviceTier: "default" } },
  prompt: [{ role: "user" as const, content: [{ type: "text" as const, text: "Hello" }] }] };
afterEach(() => vi.unstubAllGlobals());

function fixture(denied = false, unknown = false) {
  const requests: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", async (url: URL | string, init: RequestInit) => {
    const body = JSON.parse(String(init.body));
    requests.push(body);
    if (String(url).endsWith("/input_tokens")) return new Response(null, { status: 404 });
    return Response.json({ id: "resp_fixture", created_at: 1788148800, model: model.providerModelId,
      output: [{ type: "message", id: "msg_fixture", role: "assistant",
        content: [{ type: "output_text", text: "Hello", annotations: [] }] }],
      ...(unknown ? {} : { usage: { input_tokens: 1000, input_tokens_details: { cached_tokens: 400 },
        output_tokens: 10, output_tokens_details: { reasoning_tokens: 0 } } }),
    });
  });
  const budget = { reserve: vi.fn(async () => {
    if (denied) throw new AgentRunFailure("DAILY_MODEL_BUDGET_EXCEEDED");
    return { id: "charge", amount: 51720000 };
  }), settle: vi.fn(async () => undefined) };
  const metered = new MeteredLanguageModel(fetch => createOpenAI({ apiKey: "fixture", fetch })(model.providerModelId), model, budget, "researcher");
  return { metered, budget, requests };
}
it("reserves the configured input ceiling without a count endpoint and settles actual discounted usage", async () => {
  const f = fixture();
  await f.metered.doGenerate(options);
  expect(f.budget.reserve).toHaveBeenCalledWith("researcher", 51720000);
  expect(f.budget.settle).toHaveBeenCalledWith({ id: "charge", amount: 51720000 }, 140000);
  expect(f.requests).toHaveLength(1);
  expect(f.requests[0]).toHaveProperty("max_output_tokens", 100);
});
it("never dispatches generation when the daily budget refuses the reservation", async () => {
  const f = fixture(true);
  await expect(f.metered.doGenerate(options)).rejects.toMatchObject({ code: "DAILY_MODEL_BUDGET_EXCEEDED" });
  expect(f.requests).toHaveLength(0);
  expect(f.budget.settle).not.toHaveBeenCalled();
});
it("sends the configured output bound when the caller omits one", async () => {
  const f = fixture();
  await f.metered.doGenerate({ ...options, maxOutputTokens: undefined });
  expect(f.requests[0]).toHaveProperty("max_output_tokens", 128000);
  expect(f.budget.reserve).toHaveBeenCalledWith("researcher", 205200000);
});
it("retains the reservation when the provider omits usage", async () => {
  const f = fixture(false, true);
  await expect(f.metered.doGenerate(options)).rejects.toMatchObject({ code: "PROVIDER_MALFORMED_STREAM" });
  expect(f.budget.settle).not.toHaveBeenCalled();
});

it.each([false, true])("meters native SDK streaming with interrupted=%s", async interrupted => {
  const budget = { reserve: vi.fn(async (_researcher: string, amount: number) => ({ id: "stream-charge", amount })),
    settle: vi.fn(async () => undefined) };
  vi.stubGlobal("fetch", async (url: URL | string) => {
    if (!String(url).endsWith("/responses")) return new Response(null, { status: 404 });
    const events = [
      { type: "response.created", response: { id: "stream-fixture", model: model.providerModelId, created_at: 1 } },
      { type: "response.completed", response: { usage: { input_tokens: 1000,
        input_tokens_details: { cached_tokens: 400 }, output_tokens: 10,
        output_tokens_details: { reasoning_tokens: 0 } } } },
    ];
    return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(events[0])}\n\n`));
      if (interrupted) { controller.error(new Error("connection interrupted")); return; }
      controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(events[1])}\n\n`)); controller.close();
    } }), { headers: { "content-type": "text/event-stream" } });
  });
  const metered = new MeteredLanguageModel(fetch => createOpenAI({ apiKey: "fixture", fetch })(model.providerModelId), model, budget, "researcher");
  const drain = async () => {
    const reader = (await metered.doStream(options)).stream.getReader();
    for (;;) { const next = await reader.read(); if (next.done) break;
      if (next.value.type === "error") throw next.value.error; }
  };
  if (interrupted) {
    await expect(drain()).rejects.toThrow();
    expect(budget.settle).not.toHaveBeenCalled();
  } else {
    await drain();
    expect(budget.settle).toHaveBeenCalledWith({ id: "stream-charge", amount: 51720000 }, 140000);
  }
  expect(budget.reserve).toHaveBeenCalledWith("researcher", 51720000);
});

it.each(["anthropic", "google"] as const)("meters the existing %s SDK adapter with configured prices", async adapter => {
  const selected = { ...model, providerAdapter: adapter,
    providerModelId: adapter === "anthropic" ? "claude-sonnet-4-5" : "gemini-2.5-flash" };
  const countBodies: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", async (url: URL | string, init: RequestInit) => {
    if (/count_tokens|countTokens/.test(String(url))) {
      countBodies.push(JSON.parse(String(init.body)));
      return Response.json(adapter === "anthropic" ? { input_tokens: 1000 } : { totalTokens: 1000 });
    }
    return Response.json(adapter === "anthropic" ? {
      id: "msg_fixture", type: "message", role: "assistant", model: selected.providerModelId,
      content: [{ type: "text", text: "Hello" }], stop_reason: "end_turn", stop_sequence: null,
      usage: { input_tokens: 600, cache_read_input_tokens: 400, cache_creation_input_tokens: 0, output_tokens: 10 },
    } : {
      candidates: [{ content: { role: "model", parts: [{ text: "Hello" }] }, finishReason: "STOP", index: 0 }],
      usageMetadata: { promptTokenCount: 1000, candidatesTokenCount: 10, totalTokenCount: 1010, cachedContentTokenCount: 400 },
    });
  });
  const budget = { reserve: vi.fn(async () => ({ id: "charge", amount: 51720000 })), settle: vi.fn(async () => undefined) };
  const metered = new MeteredLanguageModel(fetch => adapter === "anthropic"
    ? createAnthropic({ apiKey: "fixture", fetch })(selected.providerModelId)
    : createGoogleGenerativeAI({ apiKey: "fixture", fetch })(selected.providerModelId), selected, budget, "researcher");
  await metered.doGenerate({ ...options, providerOptions: {} });
  expect(budget.settle).toHaveBeenCalledWith({ id: "charge", amount: 51720000 }, 140000);
  expect(countBodies).toHaveLength(0);
});
