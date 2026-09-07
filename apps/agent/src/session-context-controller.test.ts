import { ModelRequestFailure } from "./guarded-language-model.js";
import type { ModelStepRecovery } from "./model-step-recovery.js";
import { MessageList, type MastraDBMessage } from "@mastra/core/agent";
import { Mastra } from "@mastra/core/mastra";
import { noopLogger } from "@mastra/core/logger";
import { RequestContext } from "@mastra/core/request-context";
import { InMemoryStore } from "@mastra/core/storage";
import type { LanguageModelV3 } from "@ai-sdk/provider";
import { expect, test, vi } from "vitest";
import { modelRequestBudget } from "./model-context.js";
import { SessionContextController } from "./session-context-controller.js";
import { freezeContextSource, type SessionContextCheckpoint, type SessionContextSnapshot, type SessionContextCycle } from "./session-context-state.js";
import type { ResolvedModelSelection } from "./model-runtime.js";
import { ContextCheckpointConflictError } from "./session-repository.js";

test.each(["candidate", "claim", "commit"] as const)("%s failure reports compaction failure without publishing", async (phase) => {
  const f = await fixture();
  if (phase === "claim") f.options.repository.beginContextCycle = async () => { throw new ContextCheckpointConflictError(); };
  if (phase === "commit") f.options.repository.commitContextCycle = async () => { throw new ContextCheckpointConflictError(); };
  const controller = new SessionContextController(f.options, async () => {
    if (phase === "candidate") throw new Error("OM_CANDIDATE_INVALID");
    return candidate;
  });
  await expect(controller.prepare(f.request, "request")).rejects.toMatchObject({ code: "CONTEXT_COMPACTION_FAILED" });
  expect(f.published()).toBeNull();
});

async function fixture() {
  const raw: MastraDBMessage[] = [{ id: "old", role: "assistant", threadId: "session", resourceId: "owner",
    createdAt: new Date("2026-09-07T00:00:00Z"), content: { format: 2, parts: [{ type: "text", text: "historical evidence ".repeat(40_000) }] } },
  { id: "request", role: "user", threadId: "session", resourceId: "owner", createdAt: new Date("2026-09-07T00:00:01Z"),
    content: { format: 2, parts: [{ type: "text", text: "Continue the research" }] } }];
  const list = new MessageList(); list.add(raw, "memory");
  const prompt = await list.get.all.aiV6.llmPrompt();
  const model: LanguageModelV3 = { specificationVersion: "v3", provider: "fixture", modelId: "fixture", supportedUrls: {},
    doGenerate: async () => { throw new Error("No main model expected"); }, doStream: async () => { throw new Error("No main model expected"); } };
  const selection: ResolvedModelSelection = { compactionEnabled: true, effort: "none", languageModel: model, memoryLanguageModel: model,
    providerOptions: {}, model: { contextWindow: 65_536, maxOutputTokens: 128_000, credential: null, defaultReasoningEffort: "none",
      displayName: "Fixture", enabled: true, key: "fixture", providerAdapter: "scripted", providerModelId: "fixture", reasoningEfforts: ["none"] } };
  let checkpoint: SessionContextCheckpoint | null = null;
  let claimed = false;
  const recoveries: ModelStepRecovery[] = [];
  const repository = {
    modelStepRecoveries: async () => recoveries,
    contextCheckpoint: async () => checkpoint,
    rawContextMessages: async () => structuredClone(raw),
    beginContextCycle: async (): Promise<SessionContextCycle> => {
      if (claimed) throw new Error("Concurrent claim"); claimed = true;
      return { id: "cycle", threadId: "session", researcherId: "owner", runId: "run", revision: 0,
        checkpoint, sourceWatermark: freezeContextSource(raw) };
    },
    commitContextCycle: async (_cycle: SessionContextCycle, snapshot: SessionContextSnapshot) => {
      checkpoint = { revision: 1, snapshot }; return checkpoint;
    },
    releaseContextCycle: async () => { claimed = false; },
  };
  const abort = new AbortController();
  const options = { repository, threadId: "session", researcherId: "owner", runId: "run", selection, storage: new InMemoryStore(),
    mastra: new Mastra({ logger: noopLogger }), requestContext: new RequestContext(), abortSignal: abort.signal };
  return { options, recoveries, request: { prompt, maxOutputTokens: 128_000 }, raw, abort, published: () => checkpoint, claimed: () => claimed };
}
const candidate = { memory: "A stable fact.", summary: "Continue the research using the retained request.", auxiliaryInputTokens: 100, auxiliaryOutputTokens: 20 };

test("publishes an affordable complete snapshot and reuses its exact prefix on the next request", async () => {
  const f = await fixture();
  // Keep a small recent tail: the oldest large message is outside it.
  for (let index = 0; index < 25; index++) f.raw.splice(1, 0, { ...f.raw[0]!, id: `recent-${index}`,
    createdAt: new Date(Date.parse("2026-09-07T00:00:00Z") + index + 1),
    content: { format: 2, parts: [{ type: "text", text: "recent record ".repeat(500) }] } });
  const controller = new SessionContextController(f.options, async () => candidate);
  const prepared = await controller.prepare(f.request, "request");
  expect(f.published()?.snapshot.memory).toBe(candidate.memory);
  expect(f.published()?.snapshot.summary).toBe(candidate.summary);
  expect(f.published()?.snapshot.statistics.inputTokensAfter).toBeLessThan(58_982);
  expect(prepared.maxOutputTokens).toBe(128_000); // The provider guard retains the desired allowance before deriving D.
  expect(JSON.stringify(prepared.prompt)).not.toContain("historical evidence");
  const repeated = await controller.prepare(f.request, "request");
  expect(repeated.prompt).toEqual(prepared.prompt);
  expect(f.claimed()).toBe(false);
});

test("a second cycle consumes only effective source and atomically replaces M and S", async () => {
  const f = await fixture();
  const generated: Array<Parameters<NonNullable<ConstructorParameters<typeof SessionContextController>[1]>>[0]> = [];
  const controller = new SessionContextController(f.options, async (options) => {
    generated.push(options);
    return { ...candidate, memory: `Memory cycle ${generated.length}`, summary: `Summary cycle ${generated.length}` };
  });
  await controller.prepare(f.request, "request");
  f.raw.push({ ...f.raw[0]!, id: "new-large", content: { format: 2, parts: [{ type: "text", text: "new evidence ".repeat(40_000) }] } });
  f.raw.push({ ...f.raw[1]!, id: "next-request" });
  const prepared = await controller.prepare(f.request, "next-request");
  expect(generated).toHaveLength(2);
  expect(generated[1]?.previous).toEqual({ memory: "Memory cycle 1", summary: "Summary cycle 1" });
  expect(generated[1]?.removed.map((message) => message.id)).toEqual(["request", "new-large"]);
  expect(JSON.stringify(prepared.prompt)).toContain("Memory cycle 2");
  expect(f.published()?.snapshot.summary).toBe("Summary cycle 2");
});

test("candidate validation receives exact data versions, batch, track and folder continuation references", async () => {
  const f = await fixture();
  f.raw[0]!.content.parts.push({ type: "tool-invocation", toolInvocation: { state: "result", toolCallId: "read",
    toolName: "get_research_context", args: { folder_cursor: "folder-cursor-exact" },
    result: { data_generation_id: "generation-exact", research_run_id: "research-exact", batch_id: "batch-exact",
      track_id: "track-exact", folder_id: "folder-exact" } } });
  let references: readonly string[] = [];
  const controller = new SessionContextController(f.options, async (options) => {
    references = options.requiredReferences;
    throw new Error("Do not publish fixture");
  });
  await expect(controller.prepare(f.request, "request")).rejects.toThrow("CONTEXT_COMPACTION_FAILED");
  expect(references).toEqual(expect.arrayContaining(["folder-cursor-exact", "generation-exact", "research-exact", "batch-exact", "track-exact", "folder-exact"]));
});

test("a later date and a small-window model reuse the fixed snapshot even above 90 percent", async () => {
  const f = await fixture();
  const original = await new SessionContextController(f.options, async () => candidate).prepare(f.request, "request");
  const checkpoint = structuredClone(f.published());
  const smallSelection = { ...f.options.selection, compactionEnabled: false, model: { ...f.options.selection.model, contextWindow: 60_000 } };
  const controller = new SessionContextController({ ...f.options, selection: smallSelection }, async () => { throw new Error("Unexpected auxiliary request"); });
  const full = await requestAtTokens({ prompt: original.prompt }, 55_000);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-01T00:00:00Z"));
  try {
    const request = { prompt: [full.prompt[0]!] };
    const prepared = await controller.prepare(request, "request");
    expect(prepared.prompt).toEqual(full.prompt);
    const budget = modelRequestBudget(prepared, smallSelection.model);
    expect(budget.inputTokens).toBe(55_000);
    expect(budget.outputTokens).toBeGreaterThan(0);
    expect(f.published()).toEqual(checkpoint);
    await expect(controller.prepare({ prompt: [{ role: "system", content: "oversized fixed instructions ".repeat(60_000) }] })).rejects.toMatchObject({ code: "CONTEXT_TOO_LARGE" });
    expect(f.published()).toEqual(checkpoint);
  } finally { vi.useRealTimers(); }
});

test.each(["failure", "cancel", "oversized"] as const)("leaves the previous publication untouched after %s", async (failure) => {
  const f = await fixture();
  const controller = new SessionContextController(f.options, async () => {
    if (failure === "failure") throw new Error("Candidate failed");
    if (failure === "cancel") f.abort.abort();
    return { ...candidate, summary: "oversized summary ".repeat(50_000) };
  });
  await expect(controller.prepare(f.request, "request")).rejects.toThrow();
  expect(f.published()).toBeNull();
  expect(f.claimed()).toBe(false);
  expect(f.raw[0]?.content.parts).toHaveLength(1);
});

test("small-window mode never generates candidates and refuses an input that cannot fit", async () => {
  const f = await fixture();
  const controller = new SessionContextController({ ...f.options,
    selection: { ...f.options.selection, compactionEnabled: false } }, async () => { throw new Error("Unexpected generation"); });
  await expect(controller.prepare(f.request, "request")).rejects.toThrow("CONTEXT_TOO_LARGE");
  expect(f.published()).toBeNull();
  expect(f.claimed()).toBe(false);
});

test("Mastra's V3 prompt conversion preserves image and file tool results in the provider format", async () => {
  const list = new MessageList();
  list.add([{ id: "media-message", role: "assistant", createdAt: new Date("2026-09-07T00:00:00Z"), content: { format: 2,
    parts: [{ type: "tool-invocation", toolInvocation: { state: "result", toolCallId: "media", toolName: "read", args: {}, result: {} },
      providerMetadata: { mastra: { modelOutput: { type: "content", value: [
        { type: "media", data: "aW1hZ2U=", mediaType: "image/png" },
        { type: "media", data: "ZmlsZQ==", mediaType: "application/pdf" },
      ] } } } }],
  } }], "memory");
  const prompt: import("@ai-sdk/provider").LanguageModelV3Prompt = await list.get.all.aiV6.llmPrompt();
  const tool = prompt.find((message) => message.role === "tool");
  expect(tool?.content[0]).toMatchObject({ type: "tool-result", toolCallId: "media", output: {
    type: "content", value: [{ type: "image-data", data: "aW1hZ2U=", mediaType: "image/png" },
      { type: "file-data", data: "ZmlsZQ==", mediaType: "application/pdf" }],
  } });
});

test("an affordable request passes unchanged without creating a compression cycle", async () => {
  const f = await fixture();
  const request: import("@ai-sdk/provider").LanguageModelV3CallOptions = { prompt: [{ role: "user", content: [{ type: "text", text: "Hello" }] }] };
  const controller = new SessionContextController(f.options, async () => { throw new Error("Unexpected generation"); });
  expect(await controller.prepare(request)).toBe(request);
  expect(f.published()).toBeNull();
  expect(f.claimed()).toBe(false);
});

test("tool definitions count toward the compression trigger and cannot be hidden by a short message list", async () => {
  const f = await fixture();
  let attempted = false;
  const controller = new SessionContextController(f.options, async () => { attempted = true; throw new Error("Candidate failed"); });
  await expect(controller.prepare({ prompt: [{ role: "user", content: [{ type: "text", text: "Hello" }] }], tools: [
    { type: "function", name: "large-schema", description: "tool definition ".repeat(50_000), inputSchema: { type: "object" } },
  ] })).rejects.toThrow();
  expect(attempted).toBe(true);
  expect(f.published()).toBeNull();
  expect(f.claimed()).toBe(false);
});

async function requestAtTokens(base: import("@ai-sdk/provider").LanguageModelV3CallOptions, target: number) {
  const { estimateModelInput } = await import("./model-context.js");
  const build = (words: number): import("@ai-sdk/provider").LanguageModelV3CallOptions => ({ ...base,
    prompt: [{ role: "system", content: "a ".repeat(words) }, ...base.prompt] });
  let lower = 0, upper = target;
  while (lower < upper) {
    const middle = Math.floor((lower + upper) / 2);
    if (estimateModelInput(build(middle)) < target) lower = middle + 1; else upper = middle;
  }
  const request = build(lower);
  expect(estimateModelInput(request)).toBe(target);
  return request;
}

// Full-window fixture tokenization shares CPU with the complete unit suite.
test.each([232_199, 232_200, 232_201])("Luna's complete %s-token request obeys the exact 90 percent boundary", async (tokens) => {
  const f = await fixture();
  let attempted = false;
  const controller = new SessionContextController({ ...f.options, selection: { ...f.options.selection,
    model: { ...f.options.selection.model, contextWindow: 258_000 } } }, async () => {
    attempted = true; throw new Error("Compaction attempted");
  });
  const request = await requestAtTokens(f.request, tokens);
  if (tokens < 232_200) expect(await controller.prepare(request)).toBe(request);
  else await expect(controller.prepare(request)).rejects.toThrow("CONTEXT_COMPACTION_FAILED");
  expect(attempted).toBe(tokens >= 232_200);
  expect(f.published()).toBeNull();
}, 30_000);

test("no output room permits one protective cycle below 90 percent when the configured gate allows that model", async () => {
  const f = await fixture();
  let attempts = 0;
  const controller = new SessionContextController({ ...f.options, selection: { ...f.options.selection,
    model: { ...f.options.selection.model, contextWindow: 32_768 } } }, async () => {
    attempts++; throw new Error("Compaction attempted");
  });
  const request = await requestAtTokens({ prompt: [] }, 28_672);
  await expect(controller.prepare(request)).rejects.toThrow("CONTEXT_COMPACTION_FAILED");
  expect(attempts).toBe(1);
  expect(f.published()).toBeNull();
});

test("forced recovery below 90 percent excludes truncated evidence and requires budget improvement", async () => {
  const f = await fixture();
  f.raw[0]!.content.parts = [{ type: "text", text: "historical evidence ".repeat(12000) }];
  const list = new MessageList(); list.add(f.raw, "memory");
  const request = { prompt: await list.get.all.aiV6.llmPrompt(), maxOutputTokens: 128000 };
  const generated: string[] = [];
  const controller = new SessionContextController(f.options, async (input) => {
    generated.push(JSON.stringify(input.removed)); return candidate;
  });
  const prepared = await controller.prepare(request, "request");
  const before = modelRequestBudget(prepared, f.options.selection.model);
  expect(before.inputTokens).toBeLessThan(58982);
  expect(generated).toEqual([]);
  f.raw.push({ ...f.raw[0]!, id: "partial", content: { format: 2, parts: [{ type: "text", text: "INVALID_TRUNCATED_FACT" }] } });
  f.recoveries.push({ runId: "run", originalMessageId: "partial", replacementMessageId: "replacement", attempts: 1, invalidReplacement: false,
    cause: "OUTPUT_LIMIT", status: "recovering", beforeBudget: before, afterBudget: null, errorCode: null });
  const after = await controller.recover(new ModelRequestFailure("OUTPUT_LIMIT", before), "request");
  expect(after.budget.inputTokens).toBeLessThan(before.inputTokens);
  expect(after.budget.outputTokens).toBeGreaterThan(before.outputTokens);
  expect(JSON.stringify(after.request.prompt)).not.toContain("INVALID_TRUNCATED_FACT");
  expect(generated.join("")).not.toContain("INVALID_TRUNCATED_FACT");
  expect(f.raw.some((message) => message.id === "partial")).toBe(true);
  expect(f.published()).not.toBeNull();
});

test("forced recovery does not publish an otherwise affordable snapshot without improvement", async () => {
  const f = await fixture();
  const evidence = "historical evidence ".repeat(12000);
  f.raw[0]!.content.parts = [{ type: "text", text: evidence }];
  const list = new MessageList(); list.add(f.raw, "memory");
  const request = { prompt: await list.get.all.aiV6.llmPrompt(), maxOutputTokens: 128000 };
  const controller = new SessionContextController(f.options, async () => ({ ...candidate, summary: evidence + " extra ".repeat(1000) }));
  const before = modelRequestBudget(await controller.prepare(request, "request"), f.options.selection.model);
  await expect(controller.recover(new ModelRequestFailure("OUTPUT_LIMIT", before), "request")).rejects.toThrow();
  expect(f.published()).toBeNull();
  expect(f.claimed()).toBe(false);
});

test.each(["small-window", "full-allowance"] as const)("forced recovery cannot bypass the %s gate", async (mode) => {
  const f = await fixture();
  const selection = { ...f.options.selection, compactionEnabled: mode !== "small-window" };
  const controller = new SessionContextController({ ...f.options, selection }, async () => { throw new Error("Unexpected compression"); });
  const request = { prompt: [{ role: "user" as const, content: [{ type: "text" as const, text: "Short request" }] }], maxOutputTokens: 1000 };
  const before = modelRequestBudget(await controller.prepare(request), selection.model);
  const cause = mode === "small-window" ? "CONTEXT_TOO_LARGE" : "OUTPUT_LIMIT";
  await expect(controller.recover(new ModelRequestFailure(cause, before))).rejects.toMatchObject({ code: cause });
  expect(f.published()).toBeNull();
  expect(f.claimed()).toBe(false);
});
