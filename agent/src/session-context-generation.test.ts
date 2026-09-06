import type { LanguageModelV3, LanguageModelV3CallOptions, LanguageModelV3StreamPart } from "@ai-sdk/provider";
import { Mastra } from "@mastra/core/mastra";
import { noopLogger } from "@mastra/core/logger";
import { RequestContext } from "@mastra/core/request-context";
import { InMemoryStore } from "@mastra/core/storage";
import type { MastraDBMessage } from "@mastra/core/agent";
import { expect, test } from "vitest";
import { GuardedLanguageModel, RunModelObservation } from "./guarded-language-model.js";
import { RunUsageCapture } from "./usage-capture.js";
import type { ResolvedModelSelection } from "./model-runtime.js";
import { generateInitialSessionContext } from "./session-context-generation.js";

const summary = ["## Goal", "Find run_exact.", "## Constraints and preferences", "Keep exact values.", "## Progress",
  "Completed: read the result. In progress: comparison. Blockers: none.", "## Key decisions", "Use the frozen result.",
  "## Next steps", "1. Read cursor_exact.", "## Critical context", "run_exact cursor_exact"].join("\n");
const removed: MastraDBMessage[] = [{ id: "history", role: "assistant", createdAt: new Date("2026-09-07T00:00:00Z"),
  threadId: "session", resourceId: "owner", content: { format: 2, parts: [{ type: "tool-invocation", toolInvocation: {
    state: "result", toolCallId: "call", toolName: "get_research_run_result", args: { run_id: "run_exact" },
    result: { next_cursor: "cursor_exact", evidence: "complete source" },
  } }] } }];

function fixture(responses: { text: string; reason?: "stop" | "length" }[], onRequest?: (index: number) => void) {
  const requests: LanguageModelV3CallOptions[] = [];
  const model: LanguageModelV3 = { specificationVersion: "v3", provider: "fixture", modelId: "context", supportedUrls: {},
    doGenerate: async () => { throw new Error("Stream required"); }, doStream: async (request) => {
      const index = requests.length;
      requests.push(request); onRequest?.(index);
      const response = responses[index];
      if (!response) throw new Error("Unexpected extra auxiliary call");
      const parts: LanguageModelV3StreamPart[] = [
        { type: "text-start", id: "text" }, { type: "text-delta", id: "text", delta: response.text }, { type: "text-end", id: "text" },
        { type: "finish", finishReason: { unified: response.reason ?? "stop", raw: response.reason ?? "stop" },
          usage: { inputTokens: { total: 100, noCache: 100, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 20, text: 20, reasoning: 0 } } },
      ];
      return { stream: new ReadableStream({ start(controller) { parts.forEach((part) => controller.enqueue(part)); controller.close(); } }) };
    } };
  const capacity = { contextWindow: 65_536, maxOutputTokens: 128_000 };
  const guarded = new GuardedLanguageModel(model, new RunModelObservation(new RunUsageCapture()), capacity, "memory");
  const selection: ResolvedModelSelection = { compactionEnabled: true, effort: "high", languageModel: guarded,
    memoryLanguageModel: guarded, providerOptions: { openai: { reasoningEffort: "high" } }, model: {
      ...capacity, credential: null, defaultReasoningEffort: "high", displayName: "Fixture", enabled: true,
      key: "fixture", providerAdapter: "scripted", providerModelId: "fixture", reasoningEfforts: ["high"],
    } };
  const storage = new InMemoryStore();
  const controller = new AbortController();
  return { requests, storage, controller, options: { removed, selection, storage, mastra: new Mastra({ logger: noopLogger }),
    requestContext: new RequestContext(), abortSignal: controller.signal, requiredReferences: ["run_exact", "cursor_exact"] } };
}

test("generates empty M and structured S with the Run model, bounded requests and no persistence", async () => {
  const { options, requests, storage } = fixture([{ text: "<observations></observations>" }, { text: summary }]);
  const candidate = await generateInitialSessionContext(options);
  expect(candidate).toEqual({ memory: "", summary, auxiliaryInputTokens: 200, auxiliaryOutputTokens: 40 });
  for (const request of requests) {
    expect(request.tools ?? []).toEqual([]);
    expect(request.maxOutputTokens).toBeGreaterThan(0);
    expect(request.maxOutputTokens).toBeLessThan(65_536 - 4096);
    expect(request.providerOptions?.openai?.reasoningEffort).toBe("high");
    expect(JSON.stringify(request.prompt)).toContain("complete source");
  }
  expect(await (await storage.getStore("memory"))!.getObservationalMemory("session", "owner")).toBeNull();
});

test.each([
  { text: "invalid summary" }, { text: summary.split("\n").filter((line) => line.startsWith("## ")).join("\n") }, { text: summary.replaceAll("cursor_exact", "lost") }, { text: summary, reason: "length" as const },
])("rejects an invalid S after M succeeds without publishing anything", async (response) => {
  const { options, storage } = fixture([{ text: "<observations>Stable fact</observations>" }, response]);
  await expect(generateInitialSessionContext(options)).rejects.toThrow();
  expect(await (await storage.getStore("memory"))!.getObservationalMemory("session", "owner")).toBeNull();
});

test("reflects oversized M in the same cycle before creating S", async () => {
  const { options, requests } = fixture([{ text: `<observations>${Array.from({ length: 1500 }, (_, index) => `- Observed stable fact ${index}: result_${index} uses dataset_${index} with parameter ${index + 100}.`).join("\n")}</observations>` },
    { text: "<observations>Retain the result reference.</observations>" }, { text: summary }]);
  expect((await generateInitialSessionContext(options)).memory).toContain("Retain the result reference");
  expect(JSON.stringify(requests[1]?.prompt)).toContain("stable fact");
  expect(JSON.stringify(requests[2]?.prompt)).toContain("Retain the result reference");
});

test("rejects a small-window selection or an already cancelled cycle without calling a model", async () => {
  const { options, requests, controller } = fixture([]);
  await expect(generateInitialSessionContext({ ...options, selection: { ...options.selection, compactionEnabled: false } })).rejects.toThrow();
  controller.abort();
  await expect(generateInitialSessionContext(options)).rejects.toThrow();
  expect(requests).toEqual([]);
});

test.each([true, false])("corrects an oversized summary once and publishes only a valid candidate: %s", async (corrected) => {
  const oversized = summary + "\n" + "additional detail ".repeat(6000);
  const { options, requests } = fixture([{ text: "<observations></observations>" }, { text: oversized },
    { text: corrected ? summary : oversized }]);
  if (corrected) expect((await generateInitialSessionContext(options)).summary).toBe(summary);
  else await expect(generateInitialSessionContext(options)).rejects.toThrow("CONTEXT_COMPACTION_FAILED");
  expect(requests).toHaveLength(3);
});

test("cancellation after Observer prevents summary generation", async () => {
  const controller = new AbortController();
  const { options, requests } = fixture([{ text: "<observations>Fact</observations>" }], () => controller.abort());
  await expect(generateInitialSessionContext({ ...options, abortSignal: controller.signal })).rejects.toThrow();
  expect(requests).toHaveLength(1);
});

test("oversized auxiliary input is refused before the provider without silently truncating source", async () => {
  const { options, requests } = fixture([]);
  const oversized = structuredClone(removed);
  oversized[0]!.content.parts.push({ type: "text", text: "source evidence ".repeat(100_000) });
  await expect(generateInitialSessionContext({ ...options, removed: oversized })).rejects.toThrow();
  expect(requests).toEqual([]);
});
