import { Agent } from "@mastra/core/agent";
import { noopLogger } from "@mastra/core/logger";
import { createTool } from "@mastra/core/tools";
import { z } from "zod";
import { APICallError, type LanguageModelV3, type LanguageModelV3StreamPart } from "@ai-sdk/provider";
import { expect, test, vi } from "vitest";
import { GuardedLanguageModel, RunModelObservation } from "./guarded-language-model.js";
import { providerRetryProcessor } from "./provider-retry.js";
import { RunUsageCapture } from "./usage-capture.js";

test("a transient model timeout recovers on its third attempt without failing the Run", async () => {
  const attempts: string[] = [];
  const observation = new RunModelObservation(new RunUsageCapture());
  const model: LanguageModelV3 = {
    specificationVersion: "v3", modelId: "retry-fixture", provider: "fixture", supportedUrls: {},
    doGenerate: async () => { throw new Error("stream only"); },
    doStream: async () => {
      attempts.push("attempt");
      if (attempts.length < 3) throw new DOMException("fixture", "TimeoutError");
      return response();
    },
  };
  const agent = new Agent({ id: "provider-retry", name: "Provider retry", instructions: "Answer.",
    model: new GuardedLanguageModel(model, observation, { contextWindow: 65_536, maxOutputTokens: 1000 }),
    maxRetries: 0, maxProcessorRetries: 2,
    errorProcessors: [providerRetryProcessor(async () => { observation.retryProviderCall(); })],
  });
  agent.__setLogger(noopLogger);
  const output = await agent.stream("Answer.");
  const errors: unknown[] = [];
  for await (const event of output.fullStream) if (event.type === "error") errors.push(event.payload.error);
  expect(errors).toEqual([]);
  expect(await output.text).toBe("Recovered answer.");
  expect(attempts).toHaveLength(3);
  expect(observation.terminalFailure()).toBeUndefined();
});

function response() {
  const parts: LanguageModelV3StreamPart[] = [
    { type: "text-start", id: "answer" },
    { type: "text-delta", id: "answer", delta: "Recovered answer." },
    { type: "text-end", id: "answer" },
    { type: "finish", finishReason: { unified: "stop", raw: "stop" },
      usage: { inputTokens: { total: 5, noCache: 5, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 2, text: 2, reasoning: 0 } } },
  ];
  return { stream: new ReadableStream<LanguageModelV3StreamPart>({ start(controller) {
    for (const part of parts) controller.enqueue(part);
    controller.close();
  } }), warnings: [] };
}

function retryAgent(doStream: LanguageModelV3["doStream"]) {
  const observation = new RunModelObservation(new RunUsageCapture());
  const model: LanguageModelV3 = { specificationVersion: "v3", modelId: "retry-fixture", provider: "fixture", supportedUrls: {},
    doGenerate: async () => { throw new Error("stream only"); }, doStream };
  const agent = new Agent({ id: "retry-boundary", name: "Retry boundary", instructions: "Answer.",
    model: new GuardedLanguageModel(model, observation, { contextWindow: 65_536, maxOutputTokens: 1000 }),
    maxRetries: 0, maxProcessorRetries: 3,
    errorProcessors: [providerRetryProcessor(async () => { observation.retryProviderCall(); })],
    tools: { write: createTool({ id: "write", description: "Fixture operation", inputSchema: z.object({}), execute: async () => ({ status: "ok" }) }) },
  });
  agent.__setLogger(noopLogger);
  return { agent, observation };
}

async function errorsFrom(output: Awaited<ReturnType<Agent["stream"]>>) {
  const errors: unknown[] = [];
  for await (const event of output.fullStream) if (event.type === "error") errors.push(event.payload.error);
  return errors;
}

test("persistent timeouts exhaust exactly three attempts and emit one final error", async () => {
  let attempts = 0;
  const { agent, observation } = retryAgent(async () => { attempts++; throw new DOMException("private-timeout", "TimeoutError"); });
  expect(await errorsFrom(await agent.stream("Answer."))).toHaveLength(1);
  expect(attempts).toBe(3);
  expect(observation.terminalFailure()).toBe("PROVIDER_TIMEOUT");
});

test.each([400, 401, 403])("HTTP %s is not retried", async (statusCode) => {
  let attempts = 0;
  const { agent } = retryAgent(async () => {
    attempts++;
    throw new APICallError({ message: "private-provider-detail", url: "https://fixture.invalid", requestBodyValues: {}, statusCode });
  });
  const errors = await errorsFrom(await agent.stream("Answer."));
  expect(errors).toHaveLength(1);
  expect(attempts).toBe(1);
  expect(JSON.stringify(errors)).not.toContain("private-provider-detail");
});

test("the framework step deadline is renewed for a successful retry", async () => {
  let attempts = 0;
  const { agent, observation } = retryAgent(async () => {
    attempts++;
    if (attempts === 1) return { stream: new ReadableStream<LanguageModelV3StreamPart>(), warnings: [] };
    return response();
  });
  const output = await agent.stream("Answer.", { modelSettings: { timeout: { stepMs: 100 } } });
  expect(await errorsFrom(output)).toEqual([]);
  expect(await output.text).toBe("Recovered answer.");
  expect(attempts).toBe(2);
  expect(observation.terminalFailure()).toBeUndefined();
});

test("stopping an interrupted call cancels any further retry", async () => {
  let attempts = 0;
  const stop = new AbortController();
  const { agent } = retryAgent(async () => { attempts++; throw new DOMException("fixture", "TimeoutError"); });
  const output = await agent.stream("Answer.", { abortSignal: stop.signal });
  const finished = errorsFrom(output);
  await vi.waitFor(() => expect(attempts).toBe(1));
  stop.abort();
  await finished;
  expect(attempts).toBe(1);
});

test("the total run deadline also stops retries during backoff", async () => {
  let attempts = 0;
  const { agent } = retryAgent(async () => { attempts++; throw new DOMException("fixture", "TimeoutError"); });
  const output = await agent.stream("Answer.", { modelSettings: { timeout: { totalMs: 150 } } });
  await errorsFrom(output);
  expect(attempts).toBe(1);
});

test("each subsequent model step receives its own bounded retry allowance", async () => {
  let attempts = 0;
  const { agent } = retryAgent(async () => {
    attempts++;
    if (attempts % 3 !== 0) throw new DOMException("fixture", "TimeoutError");
    if (attempts === 3) return { warnings: [], stream: new ReadableStream<LanguageModelV3StreamPart>({ start(controller) {
      controller.enqueue({ type: "tool-call", toolCallId: "operation", toolName: "write", input: "{}" });
      controller.enqueue({ type: "finish", finishReason: { unified: "tool-calls", raw: "tool_calls" },
        usage: { inputTokens: { total: 5, noCache: 5, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 2, text: 2, reasoning: 0 } } });
      controller.close();
    } }) };
    return response();
  });
  const output = await agent.stream("Answer.", { maxSteps: Number.POSITIVE_INFINITY });
  expect(await errorsFrom(output)).toEqual([]);
  expect(attempts).toBe(6);
  expect(await output.text).toBe("Recovered answer.");
}, 10_000);

test("a transport failure after a validated finish cannot replay released tool calls", async () => {
  let attempts = 0;
  const { agent, observation } = retryAgent(async () => {
    attempts++;
    let part = 0;
    return { warnings: [], stream: new ReadableStream<LanguageModelV3StreamPart>({ pull(controller) {
      if (part++ === 0) controller.enqueue({ type: "tool-call", toolCallId: "operation", toolName: "write", input: "{}" });
      else if (part === 2) controller.enqueue({ type: "finish", finishReason: { unified: "tool-calls", raw: "tool_calls" },
        usage: { inputTokens: { total: 5, noCache: 5, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 2, text: 2, reasoning: 0 } } });
      else controller.error(new TypeError("private-network-detail", { cause: Object.assign(new Error("socket"), { code: "UND_ERR_SOCKET" }) }));
    } }) };
  });
  expect(await errorsFrom(await agent.stream("Answer."))).toHaveLength(1);
  expect(attempts).toBe(1);
  expect(observation.terminalFailure()).toBe("PROVIDER_MALFORMED_STREAM");
});
