import { APICallError, type LanguageModelV3, type LanguageModelV3CallOptions, type LanguageModelV3StreamPart } from "@ai-sdk/provider";
import { expect, test } from "vitest";

import { AGENT_LIMITS, GuardedLanguageModel, RunModelObservation } from "./guarded-language-model.js";
import { ScriptedLanguageModel } from "./scripted-language-model.js";
import { RunUsageCapture } from "./usage-capture.js";
import { SCRIPTED_FAILURE_PROMPTS } from "./scripted-failure-model.js";

const options: LanguageModelV3CallOptions = { prompt: [{ role: "user", content: [{ type: "text", text: "Alpha idea" }] }] };
const finish: LanguageModelV3StreamPart = {
  type: "finish", finishReason: { unified: "stop", raw: "stop" },
  usage: { inputTokens: { total: 5, noCache: 5, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 1, text: 1, reasoning: 0 } },
};
const textPart: LanguageModelV3StreamPart = { type: "text-delta", id: "text", delta: "An answer." };

test.each(Object.entries(SCRIPTED_FAILURE_PROMPTS))("scripted provider deterministically produces %s", async (code, prompt) => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const model = new GuardedLanguageModel(new ScriptedLanguageModel("fixture"), observation);
  const run = async () => drain(await model.doStream({ prompt: [{ role: "user", content: [{ type: "text", text: prompt }] }] }));
  await expect(run()).rejects.toMatchObject({ code });
  expect(observation.failure).toBe(code);
  expect(observation.steps).toBe(1);
});

test("the model receives an explicit output bound and reported usage stays safe", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  let received: LanguageModelV3CallOptions | undefined;
  const guarded = new GuardedLanguageModel(fake(async (input) => { received = input; return stream([textPart, finish]); }), observation);
  await drain(await guarded.doStream(options));
  expect(received?.maxOutputTokens).toBe(AGENT_LIMITS.outputTokens);
  expect(observation.steps).toBe(1);
  expect(observation.failure).toBeUndefined();
  expect(observation.usage.value()?.outputTokens.total).toBe(1);
});

test("context including Tool schemas fails before the provider is invoked", async () => {
  let invoked = false;
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async () => { invoked = true; return stream([finish]); }), observation);
  await expect(guarded.doStream({
    ...options,
    tools: [{ type: "function", name: "large_tool", inputSchema: { description: "context ".repeat(AGENT_LIMITS.contextTokens + 1) } }],
  })).rejects.toMatchObject({ code: "AGENT_LIMIT" });
  expect(invoked).toBe(false);
  expect(observation.steps).toBe(0);
});

test.each([
  [[], "PROVIDER_MALFORMED_STREAM"],
  [[finish], "PROVIDER_MALFORMED_STREAM"],
  [[null], "PROVIDER_MALFORMED_STREAM"],
  [[{ type: "text-delta", id: "text", delta: "   " }, finish], "PROVIDER_MALFORMED_STREAM"],
  [[{ ...finish, finishReason: { unified: "content-filter", raw: "private" } }], "PROVIDER_REFUSAL"],
  [[{ ...finish, finishReason: { unified: "length", raw: "private" } }], "AGENT_LIMIT"],
  [[{ type: "text-delta", id: "text", delta: "a".repeat(AGENT_LIMITS.outputBytes + 1) }], "AGENT_LIMIT"],
  [[{ type: "raw", rawValue: "a".repeat(AGENT_LIMITS.outputBytes + 1) }], "AGENT_LIMIT"],
  [[{ type: "not-a-provider-event", private: "canary" }], "PROVIDER_MALFORMED_STREAM"],
])("terminates unsafe provider stream %# without a success finish", async (parts, code) => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async () => stream(parts as LanguageModelV3StreamPart[])), observation);
  await expect(drain(await guarded.doStream(options))).rejects.toMatchObject({ code });
  expect(observation.failure).toBe(code);
});

test("never retries provider errors and never exposes their private cause", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  let invocations = 0;
  const guarded = new GuardedLanguageModel(fake(async () => {
    invocations++;
    throw new APICallError({ message: "private", requestBodyValues: "private", url: "https://private.invalid", statusCode: 429 });
  }), observation);
  const error = await guarded.doStream(options).catch((failure: unknown) => failure);
  expect(error).toMatchObject({ code: "PROVIDER_RATE_LIMIT" });
  expect(error).not.toHaveProperty("cause");
  expect(invocations).toBe(1);
});

test("a bounded loop cannot start a seventeenth model step", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(new ScriptedLanguageModel("fixture"), observation);
  for (let index = 0; index < AGENT_LIMITS.steps; index++) await drain(await guarded.doStream(options));
  await expect(guarded.doStream(options)).rejects.toMatchObject({ code: "AGENT_LIMIT" });
  expect(observation.steps).toBe(AGENT_LIMITS.steps);
});

test("invalid usage stays unreported without failing a completed answer", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async () => stream([
    textPart, { ...finish, usage: undefined } as unknown as LanguageModelV3StreamPart,
  ])), observation);
  await drain(await guarded.doStream(options));
  expect(observation.failure).toBeUndefined();
  expect(observation.usage.value()).toBeUndefined();
});

test.each(["9000", Infinity, NaN, -9000, 9000.5, Number.MAX_SAFE_INTEGER + 1, null])(
  "invalid output accounting %s cannot turn a completed answer into a limit failure", async (total) => {
    const observation = new RunModelObservation(new RunUsageCapture());
    const guarded = new GuardedLanguageModel(fake(async () => stream([
      textPart, { ...finish, usage: { inputTokens: { total: 5 }, outputTokens: { total } } } as unknown as LanguageModelV3StreamPart,
    ])), observation);
    await drain(await guarded.doStream(options));
    expect(observation.failure).toBeUndefined();
    expect(observation.usage.value()?.outputTokens.total).toBeNull();
  },
);

test("valid reported output over the bound still terminates the Run", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async () => stream([
    textPart, { ...finish, usage: { ...finish.usage, outputTokens: { ...finish.usage.outputTokens, total: AGENT_LIMITS.outputTokens + 1 } } },
  ])), observation);
  await expect(drain(await guarded.doStream(options))).rejects.toMatchObject({ code: "AGENT_LIMIT" });
});

function fake(doStream: LanguageModelV3["doStream"]): LanguageModelV3 {
  return { specificationVersion: "v3", provider: "fixture", modelId: "fixture", supportedUrls: {}, doStream,
    doGenerate: async () => { throw new Error("This test must use the streaming boundary"); } };
}
function stream(parts: LanguageModelV3StreamPart[]) {
  return { stream: new ReadableStream<LanguageModelV3StreamPart>({ start(controller) {
    for (const part of parts) controller.enqueue(part);
    controller.close();
  } }) };
}
async function drain(result: { stream: ReadableStream<LanguageModelV3StreamPart> }) {
  const reader = result.stream.getReader();
  while (!(await reader.read()).done) { /* consume the provider stream */ }
}
