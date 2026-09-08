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
import { generateSessionContext } from "./session-context-generation.js";

const summary = ["## Goal", "Find run_exact.", "## Constraints and preferences", "Keep exact values.", "## Progress",
  "Completed: read the result. In progress: comparison. Blockers: none.", "## Key decisions", "Use the frozen result.",
  "## Next steps", "1. Read cursor_exact.", "## Critical context", "run_exact cursor_exact"].join("\n");
const removed: MastraDBMessage[] = [{ id: "history", role: "assistant", createdAt: new Date("2026-09-07T00:00:00Z"),
  threadId: "session", resourceId: "owner", content: { format: 2, parts: [{ type: "tool-invocation", toolInvocation: {
    state: "result", toolCallId: "call", toolName: "get_research_run_result", args: { run_id: "run_exact" },
    result: { next_cursor: "cursor_exact", evidence: "complete source" },
} }] } }];

test("incremental generation retains old M and updates S from new raw evidence", async () => {
  const previous = { memory: "Stable prior constraint: preserve PIT.", summary: summary.replace("comparison", "old pending comparison") };
  const { options, requests } = fixture([{ text: "<observations>New authoritative fact.</observations>" }, { text: summary }]);
  const candidate = await generateSessionContext({ ...options, previous });
  expect(candidate.memory).toContain(previous.memory);
  expect(candidate.memory).toContain("New authoritative fact.");
  expect(JSON.stringify(requests[0]?.prompt)).toContain(previous.memory);
  const summaryPrompt = JSON.stringify(requests[1]?.prompt);
  expect(summaryPrompt).toContain("old pending comparison");
  expect(summaryPrompt).toContain("complete source");
  expect(summaryPrompt).toContain("Update the previous summary");
});

test("a long turn summarizes earlier history and its prefix separately before merging S", async () => {
  const { options, requests } = fixture((request) => ({ text: JSON.stringify(request.prompt).includes("Produce a structured handoff summary")
    ? summary : "<observations>Stable observation.</observations>" }));
  const earlier: MastraDBMessage = { ...removed[0]!, id: "earlier", content: { format: 2, parts: [{ type: "text", text: "EARLIER_HISTORY_ONLY" }] } };
  const currentRequest: MastraDBMessage = { ...earlier, id: "current-request", role: "user",
    content: { format: 2, parts: [{ type: "text", text: "CURRENT_GOAL_REFERENCE" }] } };
  expect((await generateSessionContext({ ...options, removed: [earlier, ...removed], currentRequest,
    turnPrefixMessageIds: ["history"] })).summary).toBe(summary);
  const summaries = requests.filter((request) => JSON.stringify(request.prompt).includes("Produce a structured handoff summary"));
  expect(summaries).toHaveLength(3);
  expect(JSON.stringify(summaries[0]?.prompt)).toContain("EARLIER_HISTORY_ONLY");
  expect(JSON.stringify(summaries[0]?.prompt)).not.toContain("complete source");
  expect(JSON.stringify(summaries[1]?.prompt)).toContain("complete source");
  expect(JSON.stringify(summaries[1]?.prompt)).toContain("CURRENT_GOAL_REFERENCE");
  expect(JSON.stringify(summaries[1]?.prompt)).not.toContain("EARLIER_HISTORY_ONLY");
  expect(JSON.stringify(summaries[2]?.prompt)).toContain("historySummary");
  expect(JSON.stringify(summaries[2]?.prompt)).toContain("turnPrefixSummary");
});

type Response = { text: string; reason?: "stop" | "length" };
function fixture(responses: Response[] | ((request: LanguageModelV3CallOptions, index: number) => Response), onRequest?: (index: number) => void) {
  const requests: LanguageModelV3CallOptions[] = [];
  const model: LanguageModelV3 = { specificationVersion: "v3", provider: "fixture", modelId: "context", supportedUrls: {},
    doGenerate: async () => { throw new Error("Stream required"); }, doStream: async (request) => {
      const index = requests.length;
      requests.push(request); onRequest?.(index);
      const response = typeof responses === "function" ? responses(request, index) : responses[index];
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
      ...capacity, pricing: { input: 0, cacheRead: 0, cacheWrite: 0, output: 0 }, credential: null, defaultReasoningEffort: "high", displayName: "Fixture", enabled: true,
      key: "fixture", providerAdapter: "scripted", providerModelId: "fixture", reasoningEfforts: ["high"],
    } };
  const storage = new InMemoryStore();
  const controller = new AbortController();
  return { requests, storage, controller, options: { removed, selection, storage, mastra: new Mastra({ logger: noopLogger }),
    requestContext: new RequestContext(), abortSignal: controller.signal, requiredReferences: ["run_exact", "cursor_exact"] } };
}

test("generates empty M and structured S with the Run model, bounded requests and no persistence", async () => {
  const { options, requests, storage } = fixture([{ text: "<observations></observations>" }, { text: summary }]);
  const candidate = await generateSessionContext(options);
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
  await expect(generateSessionContext(options)).rejects.toThrow();
  expect(await (await storage.getStore("memory"))!.getObservationalMemory("session", "owner")).toBeNull();
});

test("reflects oversized M in the same cycle before creating S", async () => {
  const { options, requests } = fixture([{ text: `<observations>${Array.from({ length: 1500 }, (_, index) => `- Observed stable fact ${index}: result_${index} uses dataset_${index} with parameter ${index + 100}.`).join("\n")}</observations>` },
    { text: "<observations>Retain the result reference.</observations>" }, { text: summary }]);
  expect((await generateSessionContext(options)).memory).toContain("Retain the result reference");
  expect(JSON.stringify(requests[1]?.prompt)).toContain("stable fact");
  expect(JSON.stringify(requests[2]?.prompt)).toContain("Retain the result reference");
});

test("rejects a small-window selection or an already cancelled cycle without calling a model", async () => {
  const { options, requests, controller } = fixture([]);
  await expect(generateSessionContext({ ...options, selection: { ...options.selection, compactionEnabled: false } })).rejects.toThrow();
  controller.abort();
  await expect(generateSessionContext(options)).rejects.toThrow();
  expect(requests).toEqual([]);
});

test.each([true, false])("corrects an oversized summary once and publishes only a valid candidate: %s", async (corrected) => {
  const oversized = summary + "\n" + "additional detail ".repeat(6000);
  const { options, requests } = fixture([{ text: "<observations></observations>" }, { text: oversized },
    { text: corrected ? summary : oversized }]);
  if (corrected) expect((await generateSessionContext(options)).summary).toBe(summary);
  else await expect(generateSessionContext(options)).rejects.toThrow("CONTEXT_COMPACTION_FAILED");
  expect(requests).toHaveLength(3);
});

test("cancellation after Observer prevents summary generation", async () => {
  const controller = new AbortController();
  const { options, requests } = fixture([{ text: "<observations>Fact</observations>" }], () => controller.abort());
  await expect(generateSessionContext({ ...options, abortSignal: controller.signal })).rejects.toThrow();
  expect(requests).toHaveLength(1);
});

test("oversized original evidence is fully covered in bounded Observer and summary batches", async () => {
  const { options, requests } = fixture((request, index) => ({ text: JSON.stringify(request.prompt).includes("Produce a structured handoff summary")
    ? summary : `<observations>Batch ${index} retains source facts.</observations>` }));
  const oversized = structuredClone(removed);
  oversized[0]!.content.parts.push({ type: "text", text: "中文😀完整证据 ".repeat(20_000) });
  const original = JSON.stringify(oversized);
  const result = await generateSessionContext({ ...options, removed: oversized });
  expect(result.summary).toBe(summary);
  const observations = requests.filter((request) => !JSON.stringify(request.prompt).includes("Produce a structured handoff summary"));
  const summaries = requests.filter((request) => JSON.stringify(request.prompt).includes("Produce a structured handoff summary"));
  expect(observations.length).toBeGreaterThan(1);
  expect(summaries.length).toBeGreaterThan(1);
  for (const batchRequests of [observations, summaries]) {
    const fragments = batchRequests.map((request) => {
      const text = request.prompt.flatMap((message) => typeof message.content === "string" ? [message.content]
        : message.content.flatMap((part) => part.type === "text" ? [part.text] : [])).at(-1)!;
      const input = text.includes('"history":') ? JSON.parse(text.slice(text.indexOf('{"history":'))).history
        : JSON.parse(text.slice(text.indexOf("\n\n") + 2));
      return JSON.parse(input[0].content.parts[0].text);
    });
    expect(fragments[0].offset).toBe(0);
    for (let i = 1; i < fragments.length; i++) expect(fragments[i].offset).toBe(fragments[i - 1].end);
    expect(fragments.at(-1).end).toBe(original.length);
    expect(fragments.map((fragment) => fragment.content).join("")).toBe(original);
  }
  expect(JSON.stringify(oversized)).toBe(original);
  expect(requests.every((request) => (request.maxOutputTokens ?? 0) > 0)).toBe(true);
});

test.each(["cancel", "summary-failure"] as const)("a later batch %s never yields a partial candidate", async (failure) => {
  const abort = new AbortController();
  let observed = 0;
  const { options, requests, storage } = fixture((request) => {
    const isSummary = JSON.stringify(request.prompt).includes("Produce a structured handoff summary");
    if (isSummary) return { text: "invalid late summary" };
    observed++;
    if (failure === "cancel" && observed === 2) abort.abort();
    return { text: `<observations>Source batch ${observed}.</observations>` };
  });
  const source = structuredClone(removed);
  source[0]!.content.parts.push({ type: "text", text: "完整数据😀 ".repeat(30_000) });
  await expect(generateSessionContext({ ...options, removed: source, abortSignal: abort.signal })).rejects.toThrow();
  expect(observed).toBeGreaterThan(1);
  expect(requests.length).toBeGreaterThan(1);
  expect(await (await storage.getStore("memory"))!.getObservationalMemory("session", "owner")).toBeNull();
});

test("reflects only after accumulated observations cross the budget on a later batch", async () => {
  let observed = 0;
  const phases: string[] = [];
  const additions = Array.from({ length: 300 }, (_, i) => `- Stable constraint ${i}: preserve the frozen dataset and exact result reference.`).join("\n");
  const { options, requests } = fixture((request) => {
    const prompt = JSON.stringify(request.prompt);
    if (prompt.includes("Produce a structured handoff summary")) {
      phases.push("summary"); return { text: summary };
    }
    if (prompt.includes("Your memory observation reflections")) {
      phases.push("reflector"); return { text: "<observations>Preserve frozen dataset and exact references.</observations>" };
    }
    phases.push("observer"); observed++;
    return { text: `<observations>${observed <= 2 ? additions : "Later evidence remains consistent."}</observations>` };
  });
  const source = structuredClone(removed);
  source[0]!.content.parts.push({ type: "text", text: "中文😀完整证据 ".repeat(20_000) });
  const candidate = await generateSessionContext({ ...options, removed: source });
  expect(phases.slice(0, 3)).toEqual(["observer", "observer", "reflector"]);
  expect(phases.filter((phase) => phase === "reflector")).toHaveLength(1);
  expect(candidate.memory).toContain("Preserve frozen dataset and exact references.");
  expect(JSON.stringify(requests[1]?.prompt)).toContain("Stable constraint 299");
  expect(JSON.stringify(requests[3]?.prompt)).toContain("Preserve frozen dataset and exact references.");
});

test("an enabled model cannot silently rearrange oversized existing memory to make it fit", async () => {
  const { options, requests } = fixture([]);
  await expect(generateSessionContext({ ...options, previous: { memory: "Prior fixed memory ".repeat(50_000), summary } })).rejects.toThrow();
  expect(requests).toEqual([]);
});
