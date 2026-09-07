import { createRequire } from "node:module";
import type { LanguageModelV3, LanguageModelV3CallOptions, LanguageModelV3StreamPart } from "@ai-sdk/provider";
import type { MastraDBMessage } from "@mastra/core/agent";
import { MessageList } from "@mastra/core/agent";
import { InMemoryStore } from "@mastra/core/storage";
import { Memory } from "@mastra/memory";
import { expect, test } from "vitest";
import { estimateModelInput } from "./model-context.js";

const commonJsMemory: typeof import("@mastra/memory") = createRequire(import.meta.url)("@mastra/memory");

test.each(["observer", "reflector"] as const)("%s rejects malformed and silently shortened candidates", async (phase) => {
  const longLine = Array.from({ length: 1800 }, (_, i) => String(i).padStart(6, "0")).join(" ");
  for (const text of ["Unable to summarize.", "- A fact without required tags", "<observations>unclosed",
    "<observations>first</observations><observations>second</observations>",
    `<observations>\n${longLine}\n</observations>`]) {
    const { memory, storage } = fixture("stop", text);
    const engine = (await memory.omEngine)!;
    await expect(phase === "observer"
      ? engine.observer.callCandidate(undefined, messages, { maxOutputTokens: 20000 })
      : engine.reflector.callCandidate("Existing memory", { maxOutputTokens: 20000 })).rejects.toThrow("OM_CANDIDATE_INVALID");
    expect(await (await storage.getStore("memory"))!.getObservationalMemory("session", "owner")).toBeNull();
  }
});

function fixture(reason: "stop" | "length" = "stop", text = "<observations>\nDate: 2026-09-07\n- User requires exact Result references.\n</observations>", MemoryConstructor = Memory) {
  const requests: LanguageModelV3CallOptions[] = [];
  const model: LanguageModelV3 = {
    specificationVersion: "v3", provider: "fixture", modelId: "candidate", supportedUrls: {},
    doGenerate: async () => { throw new Error("stream expected"); },
    doStream: async (request) => {
      requests.push(request);
      const parts: LanguageModelV3StreamPart[] = [
        { type: "text-start", id: "candidate" },
        { type: "text-delta", id: "candidate", delta: text },
        { type: "text-end", id: "candidate" },
        { type: "finish", finishReason: { unified: reason, raw: reason }, usage: {
          inputTokens: { total: 100, noCache: 100, cacheRead: 0, cacheWrite: 0 },
          outputTokens: { total: 20, text: 20, reasoning: 0 },
        } },
      ];
      return { stream: new ReadableStream({ start(controller) {
        for (const part of parts) controller.enqueue(part);
        controller.close();
      } }) };
    },
  };
  const storage = new InMemoryStore();
  const memory = new MemoryConstructor({ storage, options: { observationalMemory: {
    model, observation: { bufferTokens: false, continuationHints: false },
  } } });
  return { memory, storage, requests };
}

const messages: MastraDBMessage[] = [{
  id: "complete-tool", threadId: "session", resourceId: "owner", role: "assistant",
  createdAt: new Date("2026-09-07T00:00:00Z"), content: { format: 2, parts: [{
    type: "tool-invocation", toolInvocation: { state: "result", toolCallId: "read-1",
      toolName: "get_research_run_result", args: { run_id: "run_exact", cursor: "cursor_exact" },
      result: { content: "evidence ".repeat(30_000), next_cursor: "tail_cursor_exact" },
    },
  }] },
}];

test("Observer candidate covers complete tool arguments and result without persisting OM", async () => {
  const { memory, storage, requests } = fixture();
  await memory.createThread({ threadId: "session", resourceId: "owner" });
  const engine = (await memory.omEngine)!;
  const result = await engine.observer.callCandidate(undefined, messages, { maxOutputTokens: 2000 });
  const prompt = JSON.stringify(requests[0]?.prompt);
  expect(prompt).toContain("cursor_exact");
  expect(prompt).toContain("tail_cursor_exact");
  expect(prompt).not.toContain("[truncated");
  expect(result.finishReason).toBe("stop");
  expect(result.observations).toContain("exact Result references");
  expect(await (await storage.getStore("memory"))!.getObservationalMemory("session", "owner")).toBeNull();
  expect((await memory.recall({ threadId: "session", resourceId: "owner", perPage: false })).messages).toEqual([]);
  expect(requests[0]?.tools ?? []).toEqual([]);
});

test("Observer exposes the same complete prompt for budgeting as its actual provider request", async () => {
  const { memory, requests } = fixture();
  const engine = (await memory.omEngine)!;
  const source = structuredClone(messages);
  const tool = source[0]!.content.parts[0]!;
  if (tool.type !== "tool-invocation" || tool.toolInvocation.state !== "result") throw new Error("Expected source tool result");
  tool.toolInvocation.result = { content: "Complete tool evidence", next_cursor: "next_exact" };
  const original = structuredClone(source);
  const prepared = engine.observer.getCandidateInput("Prior exact fact", source);
  const list = new MessageList();
  list.addSystem(prepared.instructions);
  list.add(prepared.messages, "input");
  const expectedPrompt = await list.get.all.aiV6.llmPrompt();
  await engine.observer.callCandidate("Prior exact fact", source, { maxOutputTokens: 2000 });
  // Mastra stamps a local createdAt on conversion; that metadata is not sent to the Provider.
  const providerVisible = (prompt: unknown) => JSON.stringify(prompt, (key, value) => key === "mastra" ? undefined : value);
  expect(providerVisible(requests[0]?.prompt)).toEqual(providerVisible(expectedPrompt));
  expect(estimateModelInput({ prompt: requests[0]!.prompt })).toBe(estimateModelInput({ prompt: expectedPrompt }));
  expect(source).toEqual(original);
});

test.each(["observer", "reflector"] as const)("%s candidate exposes length without a retry or a marker", async (phase) => {
  const { memory, storage, requests } = fixture("length");
  const engine = (await memory.omEngine)!;
  const result = phase === "observer"
    ? await engine.observer.callCandidate(undefined, messages, { maxOutputTokens: 2000 })
    : await engine.reflector.callCandidate("Existing complete memory", { maxOutputTokens: 2000 });
  expect(result.finishReason).toBe("length");
  expect(requests).toHaveLength(1);
  expect(await (await storage.getStore("memory"))!.getObservationalMemory("session", "owner")).toBeNull();
});


test("an empty Observer memory is a valid candidate with preserved usage", async () => {
  const { memory } = fixture("stop", "<observations></observations>");
  const engine = (await memory.omEngine)!;
  const result = await engine.observer.callCandidate(undefined, messages, { maxOutputTokens: 2000 });
  expect(result.observations).toBe("");
  expect(result.usage).toMatchObject({ inputTokens: 100, outputTokens: 20 });
});

test.each(["observer", "reflector"] as const)("a cancelled %s candidate never starts a model request", async (phase) => {
  const { memory, requests } = fixture();
  const engine = (await memory.omEngine)!;
  const options = { maxOutputTokens: 2000, abortSignal: AbortSignal.abort() };
  await expect(phase === "observer"
    ? engine.observer.callCandidate(undefined, messages, options)
    : engine.reflector.callCandidate("Prior memory", options)).rejects.toThrow();
  expect(requests).toHaveLength(0);
});


test("CommonJS exposes the same pure Observer and Reflector candidates", async () => {
  const { memory, requests } = fixture("stop", "<observations>Retain exact IDs.</observations>", commonJsMemory.Memory);
  const engine = (await memory.omEngine)!;
  const observed = await engine.observer.callCandidate(undefined, messages, { maxOutputTokens: 2000 });
  const reflected = await engine.reflector.callCandidate(observed.observations, { maxOutputTokens: 2000 });
  expect(reflected.finishReason).toBe("stop");
  expect(reflected.observations).toContain("exact IDs");
  expect(JSON.stringify(requests[0]?.prompt)).toContain("tail_cursor_exact");
});
