import { APICallError, type LanguageModelV3, type LanguageModelV3CallOptions, type LanguageModelV3StreamPart } from "@ai-sdk/provider";
import { createOpenAI } from "@ai-sdk/openai";
import { expect, test } from "vitest";
import { Agent } from "@mastra/core/agent";
import { createTool } from "@mastra/core/tools";
import { z } from "zod";

import { AGENT_LIMITS, GuardedLanguageModel, RunModelObservation } from "./guarded-language-model.js";
import { ScriptedLanguageModel } from "./scripted-language-model.js";
import { RunUsageCapture } from "./usage-capture.js";
import { SCRIPTED_FAILURE_PROMPTS } from "./scripted-failure-model.js";
import { researchA2UITool } from "./research-a2ui-tool.js";
import { projectResearchA2UIContent } from "../../contracts/research-a2ui.mjs";

const options: LanguageModelV3CallOptions = { prompt: [{ role: "user", content: [{ type: "text", text: "Alpha idea" }] }] };
const finish: LanguageModelV3StreamPart = {
  type: "finish", finishReason: { unified: "stop", raw: "stop" },
  usage: { inputTokens: { total: 5, noCache: 5, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 1, text: 1, reasoning: 0 } },
};
const textPart: LanguageModelV3StreamPart = { type: "text-delta", id: "text", delta: "An answer." };

test("Mastra completes a rendered A2UI answer without requiring a redundant final text", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const model = new GuardedLanguageModel(fake(async (input) => stream(
    input.prompt.some((message) => message.role === "tool")
      ? [{ type: "text-start", id: "empty" }, { type: "text-end", id: "empty" }, finish]
      : [{ type: "tool-call", toolCallId: "render-result", toolName: "render_a2ui", input: JSON.stringify({
        surfaceId: "research-result", components: [{ id: "root", component: "Text", text: "Research result available" }],
      }) }, { ...finish, finishReason: { unified: "tool-calls", raw: "tool_calls" } }],
  )), observation);
  const agent = new Agent({ id: "render-completion", name: "Render completion", instructions: "Show the result.",
    model, maxRetries: 0, tools: { render_a2ui: researchA2UITool } });
  const response = await agent.stream("Show a research result card.", { maxSteps: 2 });
  const surfaces: unknown[] = [];
  const errors: unknown[] = [];
  for await (const event of response.fullStream) {
    if (event.type === "tool-result") surfaces.push(projectResearchA2UIContent(event.payload.result));
    if (event.type === "error" || event.type === "tool-error") errors.push(event.type);
  }
  expect(surfaces).toEqual([expect.objectContaining({ valid: true, kind: "ready" })]);
  expect(errors).toEqual([]);
  expect(observation.terminalFailure()).toBeUndefined();
  expect(observation.usage.value()).toMatchObject({ inputTokens: { total: 10 }, outputTokens: { total: 2 } });
});

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

test("the measured Luna high trajectory has a three-minute Provider call budget", () => {
  expect(AGENT_LIMITS.providerCallMs).toBe(180_000);
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

test("Mastra preserves a bounded model-facing Tool result without counting its internal copies as context", async () => {
  const resultText = "context ".repeat(12_000);
  const observation = new RunModelObservation(new RunUsageCapture());
  let receivedResult: unknown;
  const model = new GuardedLanguageModel(fake(async (input) => {
    const result = input.prompt.flatMap((message) => message.role === "tool" ? message.content : [])
      .find((part) => part.type === "tool-result");
    if (result !== undefined) {
      receivedResult = result.output;
      return stream([{ type: "text-start", id: "text" }, textPart, { type: "text-end", id: "text" }, finish]);
    }
    return stream([
      { type: "tool-call", toolCallId: "read-known-result", toolName: "read_result", input: "{}" },
      { ...finish, finishReason: { unified: "tool-calls", raw: "tool_calls" } },
    ]);
  }), observation);
  const agent = new Agent({
    id: "bounded-tool-result", name: "Bounded Tool result", instructions: "Read the result.", model, maxRetries: 0,
    tools: { read_result: createTool({
      id: "read_result", description: "Read a known result.",
      inputSchema: z.object({}), outputSchema: z.object({ text: z.string() }),
      execute: async () => ({ text: resultText }),
      toModelOutput: (output) => ({ type: "text", value: output.text }),
    }) },
  });
  const response = await agent.stream("Read the result and explain it.", { maxSteps: 2 });
  const errors: string[] = [];
  for await (const event of response.fullStream) {
    if (event.type === "error" || event.type === "tool-error") errors.push(event.type);
  }
  expect(errors).toEqual([]);
  expect(await response.text).toBe("An answer.");
  expect(receivedResult).toEqual({ type: "text", value: resultText });
  expect(observation.terminalFailure()).toBeUndefined();
});

test.each(["input", "output"] as const)("Tool %s fields named like metadata still count toward the context limit", async (location) => {
  const payload = { providerOptions: { mastra: { modelOutput: "context ".repeat(40_000) } } };
  const prompt: LanguageModelV3CallOptions["prompt"] = location === "input"
    ? [{ role: "assistant", content: [{ type: "tool-call", toolName: "read_result", toolCallId: "large-input", input: payload }] }]
    : [{ role: "tool", content: [{ type: "tool-result", toolName: "read_result", toolCallId: "large-output", output: { type: "json", value: payload } }] }];
  let invoked = false;
  const observation = new RunModelObservation(new RunUsageCapture());
  const model = new GuardedLanguageModel(fake(async () => { invoked = true; return stream([textPart, finish]); }), observation);
  await expect(model.doStream({ prompt })).rejects.toMatchObject({ code: "AGENT_LIMIT" });
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

test("a timed-out Provider stream that closes without finish remains a timeout", async () => {
  const controller = new AbortController();
  const timeout = Object.assign(new Error("private-timeout-canary"), {
    name: "MastraTimeoutError",
    timeoutType: "step",
  });
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async () => {
    controller.abort(timeout);
    return stream([]);
  }), observation);

  const failure = await drain(await guarded.doStream({ ...options, abortSignal: controller.signal }))
    .catch((error: unknown) => error);

  expect(failure).toMatchObject({ code: "PROVIDER_TIMEOUT", message: "PROVIDER_TIMEOUT" });
  expect(failure).not.toHaveProperty("cause");
  expect(observation.failure).toBe("PROVIDER_TIMEOUT");
  expect(observation.usage.value()).toBeUndefined();
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

test("native SDK socket interruption is a Provider failure with unknown final usage", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  let source: ReadableStreamDefaultController<Uint8Array> | undefined;
  const native = createOpenAI({
    apiKey: "synthetic-only",
    fetch: async () => new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        source = controller;
        for (const event of [
          { type: "response.created", response: { id: "synthetic", model: "synthetic", created_at: 1 } },
          { type: "response.output_item.added", output_index: 0, item: { type: "message", id: "synthetic-message" } },
        ]) controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
      },
    }), { headers: { "content-type": "text/event-stream" } }),
  }).responses("synthetic");
  const reader = (await new GuardedLanguageModel(native, observation).doStream(options)).stream.getReader();
  expect((await reader.read()).value?.type).toBe("stream-start");
  source!.error(new TypeError("private-stream-canary", {
    cause: Object.assign(new Error("private-socket-canary"), { code: "UND_ERR_SOCKET" }),
  }));
  const failure = await (async () => {
    while (!(await reader.read()).done) { /* consume the interrupted native stream */ }
  })().catch((error: unknown) => error);
  expect(failure).toMatchObject({ code: "PROVIDER_UNAVAILABLE", message: "PROVIDER_UNAVAILABLE" });
  expect(failure).not.toHaveProperty("cause");
  expect(observation.usage.value()).toBeUndefined();
});

test.each([
  { name: "error", code: "PROVIDER_UNAVAILABLE", event: { type: "error", sequence_number: 2, code: "server_error", message: "private-provider-canary", param: null } },
  { name: "response.failed", code: "PROVIDER_UNAVAILABLE", event: { type: "response.failed", sequence_number: 2,
    response: { error: { code: "server_error", message: "private-provider-canary" } } } },
  { name: "error without code", code: "PROVIDER_UNAVAILABLE", event: { type: "error", sequence_number: 2,
    message: "private-provider-canary", param: null } },
  { name: "response.failed without code", code: "PROVIDER_UNAVAILABLE", event: { type: "response.failed", sequence_number: 2,
    response: { error: { message: "private-provider-canary" } } } },
  { name: "error with null code", code: "PROVIDER_UNAVAILABLE", event: { type: "error", sequence_number: 2,
    code: null, message: "private-provider-canary", param: null } },
  { name: "response.failed with null code", code: "PROVIDER_UNAVAILABLE", event: { type: "response.failed", sequence_number: 2,
    response: { error: { code: null, message: "private-provider-canary" } } } },
  { name: "rate limit", code: "PROVIDER_RATE_LIMIT", event: { type: "error", sequence_number: 2,
    code: "rate_limit_exceeded", message: "private-provider-canary", param: null } },
  { name: "quota error", code: "PROVIDER_RATE_LIMIT", event: { type: "error", sequence_number: 2,
    error: { type: "insufficient_quota", code: "insufficient_quota", message: "private-provider-canary", param: null } } },
])("native SDK $name after output remains a Provider failure", async ({ event, code }) => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const events = [
    { type: "response.created", response: { id: "synthetic", model: "synthetic", created_at: 1 } },
    { type: "response.output_item.added", output_index: 0, item: { type: "message", id: "synthetic-message" } },
    event,
  ];
  const native = createOpenAI({
    apiKey: "synthetic-only",
    fetch: async () => new Response(events.map((value) => `data: ${JSON.stringify(value)}\n\n`).join(""), {
      headers: { "content-type": "text/event-stream" },
    }),
  }).responses("synthetic");
  const failure = await drain(await new GuardedLanguageModel(native, observation).doStream(options))
    .catch((error: unknown) => error);
  expect(failure).toMatchObject({ code, message: code });
  expect(failure).not.toHaveProperty("cause");
  expect(observation.usage.value()).toBeUndefined();
});

test.each([
  [[], "PROVIDER_MALFORMED_STREAM"],
  [[{ ...finish, finishReason: { unified: "tool-calls", raw: "tool_calls" } }], "PROVIDER_MALFORMED_STREAM"],
  [[{ ...finish, finishReason: { unified: "length", raw: "length" } }], "AGENT_LIMIT"],
  [[{ ...finish, finishReason: { unified: "content-filter", raw: "content_filter" } }], "PROVIDER_REFUSAL"],
  [[finish, textPart], "PROVIDER_MALFORMED_STREAM"],
])("a previous answer does not mask an invalid continuation %#", async (parts, code) => {
  const observation = new RunModelObservation(new RunUsageCapture());
  await drain(await new GuardedLanguageModel(fake(async () => stream([textPart, finish])), observation).doStream(options));
  const continuation = new GuardedLanguageModel(fake(async () => stream(parts as LanguageModelV3StreamPart[])), observation);
  await expect(drain(await continuation.doStream(options))).rejects.toMatchObject({ code });
});

test("non-streaming generation also permits an empty stop only after output in this Run", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const generate = (content: import("@ai-sdk/provider").LanguageModelV3GenerateResult["content"]) => ({
    ...fake(async () => stream([])),
    doGenerate: async () => ({ content, finishReason: finish.finishReason, usage: finish.usage, warnings: [] }),
  });
  await new GuardedLanguageModel(generate([{ type: "text", text: "Answer already delivered." }]), observation).doGenerate(options);
  await expect(new GuardedLanguageModel(generate([]), observation).doGenerate(options)).resolves.toMatchObject({ content: [] });
  expect(observation.usage.value()).toMatchObject({ inputTokens: { total: 10 }, outputTokens: { total: 2 } });
  await expect(new GuardedLanguageModel(generate([]), new RunModelObservation(new RunUsageCapture())).doGenerate(options))
    .rejects.toMatchObject({ code: "PROVIDER_MALFORMED_STREAM" });
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
