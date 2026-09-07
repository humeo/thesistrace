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
import { projectResearchA2UIContent } from "@thesistrace/contracts/research-a2ui";

const capacity = (contextWindow: number) => ({ contextWindow, maxOutputTokens: 128_000 });

const options: LanguageModelV3CallOptions = { prompt: [{ role: "user", content: [{ type: "text", text: "Alpha idea" }] }] };
const finish: LanguageModelV3StreamPart = {
  type: "finish", finishReason: { unified: "stop", raw: "stop" },
  usage: { inputTokens: { total: 5, noCache: 5, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 1, text: 1, reasoning: 0 } },
};
const textPart: LanguageModelV3StreamPart = { type: "text-delta", id: "text", delta: "An answer." };

test.each(["tool-calls", "length"] as const)("consecutive buffered calls reach the %s completion", async (reason) => {
  const guarded = new GuardedLanguageModel(fake(async () => stream([
    { type: "tool-call", toolCallId: "first", toolName: "read", input: "{}" },
    { type: "tool-call", toolCallId: "second", toolName: "read", input: "{}" },
    { ...finish, finishReason: { unified: reason, raw: reason } },
  ])), new RunModelObservation(new RunUsageCapture()), capacity(65_536));
  const output = await guarded.doStream(options);
  const delivered: string[] = [];
  const consume = async () => {
    const reader = output.stream.getReader();
    for (;;) {
      const next = await reader.read();
      if (next.done) break;
      if (next.value.type === "error") throw next.value.error;
      if (next.value.type === "tool-call") delivered.push(next.value.toolCallId);
    }
  };
  if (reason === "length") {
    await expect(consume()).rejects.toMatchObject({ code: "OUTPUT_LIMIT" });
    expect(delivered).toEqual([]);
  } else {
    await consume();
    expect(delivered).toEqual(["first", "second"]);
  }
}, 1000);

test("the native Responses HTTP payload receives the dynamic output allowance", async () => {
  const requests: Record<string, unknown>[] = [];
  const native = createOpenAI({ apiKey: "synthetic", fetch: async (_url, init) => {
    requests.push(JSON.parse(String(init?.body)));
    return Response.json({ id: "response_fixture", created_at: 1, model: "fixture", status: "completed",
      output: [{ type: "message", id: "message_fixture", role: "assistant", status: "completed",
        content: [{ type: "output_text", text: "Answer", annotations: [] }] }],
      usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 } });
  } }).responses("fixture");
  const guarded = new GuardedLanguageModel(native, new RunModelObservation(new RunUsageCapture()), capacity(258_000));
  await guarded.doGenerate(options);
  expect(requests[0]?.max_output_tokens).toBe(128_000);
  const longText = "context ".repeat(80_000);
  await guarded.doGenerate({ prompt: [{ role: "user", content: [{ type: "text", text: longText }] }] });
  expect(requests[1]?.max_output_tokens).toBeGreaterThan(0);
  expect(requests[1]?.max_output_tokens).toBeLessThan(128_000);
  expect(JSON.stringify(requests[1]?.input)).toContain(longText);
  await guarded.doGenerate({ ...options, maxOutputTokens: 1000 });
  expect(requests[2]?.max_output_tokens).toBe(1000);
});

test("a no-space rejection retains structured budget information without invoking the provider", async () => {
  let calls = 0;
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async () => { calls++; return stream([textPart, finish]); }), observation, capacity(16_384));
  const failure = await guarded.doStream({ prompt: [{ role: "user", content: [{ type: "text", text: "context ".repeat(20_000) }] }] })
    .catch((error: unknown) => error);
  expect(failure).toMatchObject({ code: "CONTEXT_TOO_LARGE", budget: {
    contextWindow: 16_384, desiredOutputTokens: 128_000, safetyTokens: 4096,
  } });
  expect(calls).toBe(0);
  expect(observation.failure).toBeUndefined();
  expect(observation.terminalFailure()).toBe("CONTEXT_TOO_LARGE");
});

test("a configured long output is not capped at 8192 tokens or 256 KiB", async () => {
  let received: LanguageModelV3CallOptions | undefined;
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async (input) => {
    received = input;
    return stream([{ ...textPart, delta: "long answer ".repeat(25_000) },
      { ...finish, usage: { ...finish.usage, outputTokens: { total: 25_000, text: 25_000, reasoning: 0 } } }]);
  }), observation, capacity(258_000));
  await drain(await guarded.doStream({ ...options, maxOutputTokens: 128_000 }));
  expect(received?.maxOutputTokens).toBe(128_000);
  expect(observation.outputBytes).toBeGreaterThan(256 * 1024);
});

test("a length stop carrying complete tool arguments never executes that operation", async () => {
  let executions = 0;
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async () => stream([
    { type: "tool-call", toolCallId: "must-not-execute", toolName: "submit", input: "{}" },
    { ...finish, finishReason: { unified: "length", raw: "max_output_tokens" } },
  ])), observation, capacity(65_536));
  const agent = new Agent({ id: "length-execution-barrier", name: "Length execution barrier", instructions: "Submit once.",
    model: guarded, maxRetries: 0, tools: { submit: createTool({ id: "submit", description: "Submit research",
      inputSchema: z.object({}), execute: async () => { executions++; return { accepted: true }; } }) } });
  const response = await agent.stream("Submit.", { maxSteps: 2 });
  for await (const _ of response.fullStream) { /* consume failed step */ }
  expect(executions).toBe(0);
  expect(observation.terminalFailure()).toBe("OUTPUT_LIMIT");
});

test("the same long prompt fits Luna's configured window and fails a smaller model's window", async () => {
  const prompt = [{ role: "user" as const, content: [{ type: "text" as const, text: "context ".repeat(40_000) }] }];
  let received: LanguageModelV3CallOptions | undefined;
  const provider = fake(async (input) => { received = input; return stream([textPart, finish]); });
  const luna = new GuardedLanguageModel(provider, new RunModelObservation(new RunUsageCapture()), capacity(258_000));
  await drain(await luna.doStream({ prompt }));
  expect(received?.prompt).toEqual(prompt);
  const smaller = new GuardedLanguageModel(provider, new RunModelObservation(new RunUsageCapture()), capacity(65_536));
  await expect(smaller.doStream({ prompt })).rejects.toMatchObject({ code: "CONTEXT_TOO_LARGE" });
});

test("rejects an input that leaves no safe output space", async () => {
  const guarded = new GuardedLanguageModel(fake(async () => stream([textPart, finish])),
    new RunModelObservation(new RunUsageCapture()), capacity(16_384));
  await expect(guarded.doStream({ prompt: [{ role: "user", content: [{ type: "text", text: "context ".repeat(20_000) }] }] }))
    .rejects.toMatchObject({ code: "CONTEXT_TOO_LARGE" });
});

test("memory compression is metered but cannot substitute for an answer to the user", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  await drain(await new GuardedLanguageModel(fake(async () => stream([textPart, finish])), observation, capacity(65_536), "memory")
    .doStream(options));
  expect(observation.usage.value()?.outputTokens.total).toBe(1);
  expect(observation.outputBytes).toBeGreaterThan(0);
  await expect(drain(await new GuardedLanguageModel(fake(async () => stream([finish])), observation, capacity(65_536))
    .doStream(options))).rejects.toMatchObject({ code: "PROVIDER_MALFORMED_STREAM" });
});

test("Mastra completes a rendered A2UI answer without requiring a redundant final text", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const model = new GuardedLanguageModel(fake(async (input) => stream(
    input.prompt.some((message) => message.role === "tool")
      ? [{ type: "text-start", id: "empty" }, { type: "text-end", id: "empty" }, finish]
      : [{ type: "tool-call", toolCallId: "render-result", toolName: "render_a2ui", input: JSON.stringify({
        surfaceId: "research-result", components: [{ id: "root", component: "Text", text: "Research result available" }],
      }) }, { ...finish, finishReason: { unified: "tool-calls", raw: "tool_calls" } }],
  )), observation, capacity(65_536));
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
  const model = new GuardedLanguageModel(new ScriptedLanguageModel("fixture"), observation, capacity(65_536));
  const run = async () => drain(await model.doStream({ prompt: [{ role: "user", content: [{ type: "text", text: prompt }] }] }));
  await expect(run()).rejects.toMatchObject({ code });
  expect(observation.terminalFailure()).toBe(code);
  expect(observation.steps).toBe(1);
});

test("the model receives an explicit output bound and reported usage stays safe", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  let received: LanguageModelV3CallOptions | undefined;
  const guarded = new GuardedLanguageModel(fake(async (input) => { received = input; return stream([textPart, finish]); }), observation, capacity(65_536));
  await drain(await guarded.doStream(options));
  expect(received?.maxOutputTokens).toBeGreaterThan(8192);
  expect(received?.maxOutputTokens).toBeLessThan(65_536 - 4096);
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
  const guarded = new GuardedLanguageModel(fake(async () => { invoked = true; return stream([finish]); }), observation, capacity(65_536));
  await expect(guarded.doStream({
    ...options,
    tools: [{ type: "function", name: "large_tool", inputSchema: { description: "context ".repeat(65_536 + 1) } }],
  })).rejects.toMatchObject({ code: "CONTEXT_TOO_LARGE" });
  expect(invoked).toBe(false);
  expect(observation.steps).toBe(0);
});

test("a structured-output schema is included before allowing a model request", async () => {
  let invoked = false;
  const guarded = new GuardedLanguageModel(fake(async () => { invoked = true; return stream([textPart, finish]); }),
    new RunModelObservation(new RunUsageCapture()), capacity(16_384));
  await expect(guarded.doStream({ ...options, responseFormat: { type: "json",
    schema: { type: "object", description: "context ".repeat(20_000) } },
  })).rejects.toMatchObject({ code: "CONTEXT_TOO_LARGE" });
  expect(invoked).toBe(false);
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
  }), observation, capacity(65_536));
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
  const model = new GuardedLanguageModel(fake(async () => { invoked = true; return stream([textPart, finish]); }), observation, capacity(65_536));
  await expect(model.doStream({ prompt })).rejects.toMatchObject({ code: "CONTEXT_TOO_LARGE" });
  expect(invoked).toBe(false);
  expect(observation.steps).toBe(0);
});

test.each([
  [[], "PROVIDER_MALFORMED_STREAM"],
  [[finish], "PROVIDER_MALFORMED_STREAM"],
  [[null], "PROVIDER_MALFORMED_STREAM"],
  [[{ type: "text-delta", id: "text", delta: "   " }, finish], "PROVIDER_MALFORMED_STREAM"],
  [[{ ...finish, finishReason: { unified: "content-filter", raw: "private" } }], "PROVIDER_REFUSAL"],
  [[{ ...finish, finishReason: { unified: "length", raw: "private" } }], "OUTPUT_LIMIT"],
  [[{ type: "not-a-provider-event", private: "canary" }], "PROVIDER_MALFORMED_STREAM"],
])("terminates unsafe provider stream %# without a success finish", async (parts, code) => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async () => stream(parts as LanguageModelV3StreamPart[])), observation, capacity(65_536));
  await expect(drain(await guarded.doStream(options))).rejects.toMatchObject({ code });
  expect(observation.terminalFailure()).toBe(code);
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
  }), observation, capacity(65_536));

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
  }), observation, capacity(65_536));
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
  const reader = (await new GuardedLanguageModel(native, observation, capacity(65_536)).doStream(options)).stream.getReader();
  expect((await reader.read()).value?.type).toBe("stream-start");
  source!.error(new TypeError("private-stream-canary", {
    cause: Object.assign(new Error("private-socket-canary"), { code: "UND_ERR_SOCKET" }),
  }));
  const failure = await (async () => {
    for (;;) { const next = await reader.read(); if (next.done) break; if (next.value.type === "error") throw next.value.error; }
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
  const failure = await drain(await new GuardedLanguageModel(native, observation, capacity(65_536)).doStream(options))
    .catch((error: unknown) => error);
  expect(failure).toMatchObject({ code, message: code });
  expect(failure).not.toHaveProperty("cause");
  expect(observation.usage.value()).toBeUndefined();
});

test.each([
  [[], "PROVIDER_MALFORMED_STREAM"],
  [[{ ...finish, finishReason: { unified: "tool-calls", raw: "tool_calls" } }], "PROVIDER_MALFORMED_STREAM"],
  [[{ ...finish, finishReason: { unified: "length", raw: "length" } }], "OUTPUT_LIMIT"],
  [[{ ...finish, finishReason: { unified: "content-filter", raw: "content_filter" } }], "PROVIDER_REFUSAL"],
  [[finish, textPart], "PROVIDER_MALFORMED_STREAM"],
])("a previous answer does not mask an invalid continuation %#", async (parts, code) => {
  const observation = new RunModelObservation(new RunUsageCapture());
  await drain(await new GuardedLanguageModel(fake(async () => stream([textPart, finish])), observation, capacity(65_536)).doStream(options));
  const continuation = new GuardedLanguageModel(fake(async () => stream(parts as LanguageModelV3StreamPart[])), observation, capacity(65_536));
  await expect(drain(await continuation.doStream(options))).rejects.toMatchObject({ code });
});

test("non-streaming generation also permits an empty stop only after output in this Run", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const generate = (content: import("@ai-sdk/provider").LanguageModelV3GenerateResult["content"]) => ({
    ...fake(async () => stream([])),
    doGenerate: async () => ({ content, finishReason: finish.finishReason, usage: finish.usage, warnings: [] }),
  });
  await new GuardedLanguageModel(generate([{ type: "text", text: "Answer already delivered." }]), observation, capacity(65_536)).doGenerate(options);
  await expect(new GuardedLanguageModel(generate([]), observation, capacity(65_536)).doGenerate(options)).resolves.toMatchObject({ content: [] });
  expect(observation.usage.value()).toMatchObject({ inputTokens: { total: 10 }, outputTokens: { total: 2 } });
  await expect(new GuardedLanguageModel(generate([]), new RunModelObservation(new RunUsageCapture()), capacity(65_536)).doGenerate(options))
    .rejects.toMatchObject({ code: "PROVIDER_MALFORMED_STREAM" });
});

test("model calls continue beyond sixteen steps", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(new ScriptedLanguageModel("fixture"), observation, capacity(65_536));
  for (let index = 0; index < 20; index++) await drain(await guarded.doStream(options));
  expect(observation.steps).toBe(20);
  expect(observation.terminalFailure()).toBeUndefined();
});

test("invalid usage stays unreported without failing a completed answer", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async () => stream([
    textPart, { ...finish, usage: undefined } as unknown as LanguageModelV3StreamPart,
  ])), observation, capacity(65_536));
  await drain(await guarded.doStream(options));
  expect(observation.failure).toBeUndefined();
  expect(observation.usage.value()).toBeUndefined();
});

test.each(["9000", Infinity, NaN, -9000, 9000.5, Number.MAX_SAFE_INTEGER + 1, null])(
  "invalid output accounting %s cannot turn a completed answer into a limit failure", async (total) => {
    const observation = new RunModelObservation(new RunUsageCapture());
    const guarded = new GuardedLanguageModel(fake(async () => stream([
      textPart, { ...finish, usage: { inputTokens: { total: 5 }, outputTokens: { total } } } as unknown as LanguageModelV3StreamPart,
    ])), observation, capacity(65_536));
    await drain(await guarded.doStream(options));
    expect(observation.failure).toBeUndefined();
    expect(observation.usage.value()?.outputTokens.total).toBeNull();
  },
);

test("reported usage is not a second hardcoded generation cap", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const guarded = new GuardedLanguageModel(fake(async () => stream([
    textPart, { ...finish, usage: { ...finish.usage, outputTokens: { ...finish.usage.outputTokens, total: 9000 } } },
  ])), observation, capacity(65_536));
  await drain(await guarded.doStream(options));
  expect(observation.terminalFailure()).toBeUndefined();
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
  for (;;) { const next = await reader.read(); if (next.done) break; if (next.value.type === "error") throw next.value.error; }
}

test("an auxiliary length stop is a compaction failure, not a truncated user answer", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const model = new GuardedLanguageModel(fake(async () => stream([textPart,
    { ...finish, finishReason: { unified: "length", raw: "length" } }])), observation, capacity(65_536), "memory");
  await expect(drain(await model.doStream(options))).rejects.toMatchObject({ code: "CONTEXT_COMPACTION_FAILED" });
  expect(observation.terminalFailure()).toBe("CONTEXT_COMPACTION_FAILED");
});

test("individual call observations preserve unknown usage and cannot fail model work", () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const calls: unknown[] = [];
  observation.onCallFinished = call => { calls.push(call); throw new Error("private-observer-canary"); };
  const capacity = { contextWindow: 65536, maxOutputTokens: 1000 };
  observation.begin({ prompt: [{ role: "user", content: [{ type: "text", text: "Private source" }] }] }, capacity, "memory");
  expect(() => observation.finish({ type: "finish", finishReason: { unified: "stop", raw: "private-reason" },
    usage: { inputTokens: { total: 10, noCache: 8, cacheRead: 2, cacheWrite: undefined }, outputTokens: { total: 5, text: 5, reasoning: 0 } },
  }, true, "memory")).not.toThrow();
  observation.begin({ prompt: [{ role: "user", content: [{ type: "text", text: "Next source" }] }] }, capacity);
  observation.fail("PROVIDER_TIMEOUT");
  expect(calls).toHaveLength(2);
  expect(calls[0]).toMatchObject({ purpose: "memory", finishReason: "stop", usage: { inputTokens: { total: 10, cacheRead: 2 } } });
  expect(calls[1]).toMatchObject({ purpose: "answer", finishReason: "error", usage: undefined });
  expect(JSON.stringify(calls)).not.toMatch(/Private source|Next source|private-reason/);
});
