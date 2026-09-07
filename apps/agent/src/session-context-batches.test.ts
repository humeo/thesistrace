import type { MastraDBMessage } from "@mastra/core/agent";
import { expect, test } from "vitest";
import { ContextEvidenceBatches } from "./session-context-batches.js";

function message(id: string, text: string): MastraDBMessage {
  return { id, role: "assistant", createdAt: new Date("2026-09-07T00:00:00Z"), content: { format: 2, parts: [{ type: "text", text }] } };
}

test("whole-message batches preserve cross-message tool pairs and exact ordered coverage", async () => {
  const call = message("call", "Prepare the read");
  call.content.parts.push({ type: "tool-invocation", toolInvocation: { state: "call", toolName: "read", toolCallId: "read-1", args: {} } });
  const result = message("result", "Read complete");
  result.content.parts.push({ type: "tool-invocation", toolInvocation: { state: "result", toolName: "read", toolCallId: "read-1", args: {}, result: { cursor: "exact" } } });
  const source = [message("first", "A"), call, message("between", "B"), result, message("last", "C")];
  const reader = new ContextEvidenceBatches(source);
  const batches: MastraDBMessage[][] = [];
  for (;;) {
    const batch = await reader.next(async (messages) => messages.length <= 3, AbortSignal.timeout(1000));
    if (!batch) break;
    batches.push(batch);
  }
  expect(batches.map((batch) => batch.map((message) => message.id))).toEqual([["first"], ["call", "between", "result"], ["last"]]);
  reader.assertComplete();
});

test("oversized Chinese text is covered by source-tagged fragments without changing raw messages", async () => {
  const source = [message("long", "中文😀数据".repeat(700))];
  const original = structuredClone(source);
  const reader = new ContextEvidenceBatches(source, [{ messageId: "long", partIndex: 7 }]);
  const fragments: { offset: number; end: number; total: number; content: string; sources: unknown }[] = [];
  for (;;) {
    const batch = await reader.next(async (messages) => JSON.stringify(messages).length <= 1500, AbortSignal.timeout(1000));
    if (!batch) break;
    const part = batch[0]!.content.parts[0]!;
    if (part.type !== "text") throw new Error("Expected fragment text");
    const fragment = JSON.parse(part.text);
    expect(fragment.sources).toEqual([{ messageId: "long", partIndex: 7 }]);
    expect(fragment.content.isWellFormed()).toBe(true);
    fragments.push(fragment);
  }
  expect(fragments.length).toBeGreaterThan(1);
  expect(fragments[0]!.offset).toBe(0);
  expect(fragments.at(-1)!.end).toBe(fragments[0]!.total);
  for (let i = 1; i < fragments.length; i++) expect(fragments[i]!.offset).toBe(fragments[i - 1]!.end);
  expect(fragments.map((fragment) => fragment.content).join("")).toBe(JSON.stringify(original));
  expect(source).toEqual(original);
  reader.assertComplete();
});

test("unaffordable fixed instructions and cancellation stop without advancing coverage", async () => {
  const reader = new ContextEvidenceBatches([message("first", "evidence")]);
  await expect(reader.next(async () => false, new AbortController().signal)).rejects.toThrow("CONTEXT_COMPACTION_FAILED");
  expect(() => reader.assertComplete()).toThrow();
  await expect(reader.next(async () => true, AbortSignal.abort())).rejects.toThrow();
  expect(() => reader.assertComplete()).toThrow();
});
