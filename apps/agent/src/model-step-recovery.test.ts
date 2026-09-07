import { APICallError, type LanguageModelV3, type LanguageModelV3StreamPart } from "@ai-sdk/provider";
import { Agent } from "@mastra/core/agent";
import { noopLogger } from "@mastra/core/logger";
import { createTool } from "@mastra/core/tools";
import { expect, test } from "vitest";
import { z } from "zod";
import { GuardedLanguageModel, ModelRequestFailure, RunModelObservation } from "./guarded-language-model.js";
import { RunUsageCapture } from "./usage-capture.js";

const usage = { inputTokens: { total: 20, noCache: 20, cacheRead: 0, cacheWrite: 0 },
  outputTokens: { total: 10, text: 10, reasoning: 0 } };

test.each(["length", "context"] as const)("native error processing receives the guarded %s stop before executing tools", async (reason) => {
  let operations = 0;
  const failures: unknown[] = [], messageIds: (string | undefined)[] = [];
  const model: LanguageModelV3 = { specificationVersion: "v3", provider: "fixture", modelId: "recovery", supportedUrls: {},
    doGenerate: async () => { throw new Error("Stream required"); },
    doStream: async () => {
      if (reason === "context") throw new APICallError({ message: "private-context", url: "https://fixture.invalid",
        requestBodyValues: {}, statusCode: 400, data: { error: { code: "context_length_exceeded" } }, isRetryable: false });
      const parts: LanguageModelV3StreamPart[] = [
        { type: "text-start", id: "partial" }, { type: "text-delta", id: "partial", delta: "Partial answer." },
        { type: "text-end", id: "partial" },
        { type: "tool-input-start", id: "write-call", toolName: "write" },
        { type: "tool-input-delta", id: "write-call", delta: "{}" }, { type: "tool-input-end", id: "write-call" },
        { type: "tool-call", toolCallId: "write-call", toolName: "write", input: "{}" },
        { type: "finish", finishReason: { unified: "length", raw: "length" }, usage },
      ];
      return { stream: new ReadableStream({ start(controller) { parts.forEach((part) => controller.enqueue(part)); controller.close(); } }) };
    } };
  const observation = new RunModelObservation(new RunUsageCapture());
  const agent = new Agent({ id: "recovery-seam", name: "Recovery seam", instructions: "Answer the request.",
    model: new GuardedLanguageModel(model, observation, { contextWindow: 65536, maxOutputTokens: 128000 }),
    maxRetries: 0,
    tools: { write: createTool({ id: "write", description: "Write an operation", inputSchema: z.object({}),
      execute: async () => { operations++; return { accepted: true }; } }) },
    errorProcessors: [{ id: "capture-recovery", processAPIError: async ({ error, messageId }) => {
      failures.push(error); messageIds.push(messageId); return { retry: false };
    } }],
  });
  agent.__setLogger(noopLogger);
  const response = await agent.stream("Answer and perform the operation", { maxSteps: 3, maxProcessorRetries: 1 });
  for await (const _event of response.fullStream) { /* Drain the native loop, including failure. */ }
  expect(failures).toHaveLength(1);
  expect(failures[0]).toBeInstanceOf(ModelRequestFailure);
  expect(failures[0]).toMatchObject({ code: reason === "length" ? "OUTPUT_LIMIT" : "CONTEXT_TOO_LARGE" });
  expect(messageIds[0]).toEqual(expect.any(String));
  expect(operations).toBe(0);
});

import { invalidRecoveryMessageIds, mayRecoverModelStep, recoveryImprovesBudget, type ModelStepRecovery } from "./model-step-recovery.js";
import { modelRequestBudget, type ModelRequestBudget } from "./model-context.js";

const budget: ModelRequestBudget = { contextWindow: 258000, inputTokens: 220000, desiredOutputTokens: 128000, outputTokens: 33904, safetyTokens: 4096 };

test("length recovery requires a reduced allowance and is disabled on small models", () => {
  expect(mayRecoverModelStep(true, "OUTPUT_LIMIT", budget)).toBe(true);
  expect(mayRecoverModelStep(false, "OUTPUT_LIMIT", budget)).toBe(false);
  expect(mayRecoverModelStep(false, "CONTEXT_TOO_LARGE", budget)).toBe(false);
  expect(mayRecoverModelStep(true, "CONTEXT_TOO_LARGE", budget)).toBe(true);
  expect(mayRecoverModelStep(true, "OUTPUT_LIMIT", { ...budget, inputTokens: 10000, outputTokens: 128000 })).toBe(false);
  expect(mayRecoverModelStep(true, "OUTPUT_LIMIT", { ...budget, desiredOutputTokens: 8000, outputTokens: 8000 })).toBe(false);
});

test("a replacement must shrink input and improve the constrained output allowance", () => {
  const improved = { ...budget, inputTokens: 20000, outputTokens: 128000 };
  expect(recoveryImprovesBudget("OUTPUT_LIMIT", budget, improved)).toBe(true);
  expect(recoveryImprovesBudget("OUTPUT_LIMIT", budget, { ...improved, inputTokens: budget.inputTokens })).toBe(false);
  expect(recoveryImprovesBudget("OUTPUT_LIMIT", budget, { ...improved, outputTokens: budget.outputTokens })).toBe(false);
  expect(recoveryImprovesBudget("CONTEXT_TOO_LARGE", budget, { ...improved, outputTokens: budget.outputTokens })).toBe(true);
  expect(recoveryImprovesBudget("CONTEXT_TOO_LARGE", budget, { ...improved, outputTokens: 0 })).toBe(false);
  expect(recoveryImprovesBudget("OUTPUT_LIMIT", budget, { ...improved, contextWindow: 1000000 })).toBe(false);
});

test("only the same pending failure with an improved request can be acknowledged", async () => {
  const observation = new RunModelObservation(new RunUsageCapture());
  const request = { prompt: [{ role: "user" as const, content: [{ type: "text" as const, text: "history ".repeat(4000) }] }] };
  observation.begin(request, { contextWindow: 65536, maxOutputTokens: 128000 });
  const pending = observation.fail("OUTPUT_LIMIT");
  if (!(pending instanceof ModelRequestFailure)) throw new Error("Expected bounded failure");
  expect(() => observation.acknowledgeRecovery(pending, pending.budget)).toThrow();
  expect(observation.terminalFailure()).toBe("OUTPUT_LIMIT");
  const better = { ...pending.budget, inputTokens: 100, outputTokens: 61340 };
  expect(() => observation.acknowledgeRecovery(new ModelRequestFailure("OUTPUT_LIMIT", pending.budget), better)).toThrow();
  // Auxiliary work shares accounting without clearing the rejected main request.
  expect(() => observation.begin({ prompt: [] }, { contextWindow: 65536, maxOutputTokens: 128000 }, "memory")).not.toThrow();
  expect(observation.terminalFailure()).toBe("OUTPUT_LIMIT");
  observation.acknowledgeRecovery(pending, better);
  expect(observation.terminalFailure()).toBeUndefined();
  expect(() => observation.acknowledgeRecovery(pending, better)).toThrow();
  expect(observation.steps).toBe(2);
});

test("native retry separates the replacement and retains earlier successful tool evidence", async () => {
  let operations = 0;
  const prompts: unknown[] = [], failures: ModelRequestFailure[] = [], responseIds: string[] = [];
  const observation = new RunModelObservation(new RunUsageCapture());
  const capacity = { contextWindow: 65536, maxOutputTokens: 128000 };
  const model: LanguageModelV3 = { specificationVersion: "v3", provider: "fixture", modelId: "retry", supportedUrls: {},
    doGenerate: async () => { throw new Error("Stream required"); }, doStream: async (request) => {
      prompts.push(request.prompt);
      const index = prompts.length;
      const parts: LanguageModelV3StreamPart[] = index === 3 ? [
        { type: "text-start", id: "complete" }, { type: "text-delta", id: "complete", delta: "Complete replacement answer." },
        { type: "text-end", id: "complete" }, { type: "finish", finishReason: { unified: "stop", raw: "stop" }, usage },
      ] : [
        ...(index === 2 ? [{ type: "text-start", id: "partial" }, { type: "text-delta", id: "partial", delta: "INVALID_PARTIAL_BODY" },
          { type: "text-end", id: "partial" }] as LanguageModelV3StreamPart[] : []),
        { type: "tool-call", toolCallId: `call-${index}`, toolName: "write", input: '{}' },
        { type: "finish", finishReason: { unified: index === 1 ? "tool-calls" : "length", raw: index === 1 ? "tool-calls" : "length" }, usage },
      ];
      return { stream: new ReadableStream({ start(controller) { parts.forEach((part) => controller.enqueue(part)); controller.close(); } }) };
    } };
  const agent = new Agent({ id: "retry-seam", name: "Retry seam", instructions: "Complete the task.", maxRetries: 0,
    model: new GuardedLanguageModel(model, observation, capacity),
    tools: { write: createTool({ id: "write", description: "Write once", inputSchema: z.object({}),
      execute: async () => { operations++; return { receipt: "SUCCESSFUL_RECEIPT", request_id: "original-request" }; } }) },
    inputProcessors: [{ id: "step-boundary", processInputStep: ({ rotateResponseMessageId }) => {
      if (!rotateResponseMessageId) throw new Error("Response boundary unavailable");
      responseIds.push(rotateResponseMessageId());
    } }],
    errorProcessors: [{ id: "retry-once", processAPIError: async ({ error, messageList, messageId }) => {
      if (!(error instanceof ModelRequestFailure) || !messageId || failures.length) throw error;
      failures.push(error);
      // Fixture stands in for a successfully committed compaction of this old evidence.
      messageList.removeByIds(["old-evidence", messageId]);
      const prompt = await messageList.get.all.aiV6.llmPrompt();
      observation.acknowledgeRecovery(error, modelRequestBudget({ prompt }, capacity));
      return { retry: true };
    } }],
  });
  agent.__setLogger(noopLogger);
  const response = await agent.stream([
    { id: "old-evidence", role: "assistant", content: "OLD_EVIDENCE ".repeat(2000) },
    { id: "current-user", role: "user", content: "Write once and explain the result." },
  ], { maxSteps: 4, maxProcessorRetries: 1 });
  const errors: unknown[] = [];
  for await (const event of response.fullStream) if (event.type === "error") errors.push(event);
  expect(errors).toEqual([]);
  expect(failures).toHaveLength(1);
  expect(operations).toBe(1);
  expect(prompts).toHaveLength(3);
  expect(new Set(responseIds).size).toBe(3);
  expect(JSON.stringify(prompts[2])).toContain("SUCCESSFUL_RECEIPT");
  expect(JSON.stringify(prompts[2])).toContain("original-request");
  expect(JSON.stringify(prompts[2])).not.toContain("INVALID_PARTIAL_BODY");
  expect(JSON.stringify(prompts[2])).not.toContain("OLD_EVIDENCE");
  expect(observation.terminalFailure()).toBeUndefined();
});

test("a failed Run does not exclude its previously successful replacement tools", () => {
  const recovery: ModelStepRecovery = { runId: "run", originalMessageId: "partial", replacementMessageId: "successful-tools", attempts: 1,
    invalidReplacement: false, cause: "OUTPUT_LIMIT", status: "failed", beforeBudget: budget, afterBudget: budget, errorCode: "MCP_TRANSIENT" };
  expect(invalidRecoveryMessageIds([recovery])).toEqual(["partial"]);
  expect(invalidRecoveryMessageIds([{ ...recovery, invalidReplacement: true }])).toEqual(["partial", "successful-tools"]);
});
