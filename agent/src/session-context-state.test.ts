import type { MastraDBMessage } from "@mastra/core/agent";
import { expect, test } from "vitest";
import { contextSourceMatches, freezeContextSource, sessionContextSnapshotSchema } from "./session-context-state.js";

const original: MastraDBMessage = { id: "first", role: "assistant", threadId: "session",
  createdAt: new Date("2026-09-07T00:00:00Z"), content: { format: 2, parts: [{ type: "text", text: "Preserve the exact reference" }] } };

test("JSON object key ordering on resume does not change the frozen source", () => {
  const frozen = freezeContextSource([original]);
  const reordered: MastraDBMessage = { ...original, content: { parts: [{ text: "Preserve the exact reference", type: "text" }], format: 2 } };
  expect(contextSourceMatches(frozen, freezeContextSource([reordered]))).toBe(true);
  reordered.content.parts = [{ text: "Changed reference", type: "text" }];
  expect(contextSourceMatches(frozen, freezeContextSource([reordered]))).toBe(false);
});

test("a frozen source allows appended messages and parts without accepting rewritten history", () => {
  const frozen = freezeContextSource([original]);
  const appended = structuredClone(original);
  appended.content.parts.push({ type: "text", text: "New continuation" });
  const next = { ...original, id: "next" };
  expect(contextSourceMatches(frozen, freezeContextSource([appended, next]))).toBe(true);
  const replaced = structuredClone(original);
  replaced.content.parts = [{ type: "text", text: "Different evidence" }];
  expect(contextSourceMatches(frozen, freezeContextSource([replaced]))).toBe(false);
  expect(contextSourceMatches(frozen, [])).toBe(false);
  expect(contextSourceMatches(frozen, freezeContextSource([next, original]))).toBe(false);
  expect(contextSourceMatches(freezeContextSource([original, next]), freezeContextSource([next, original]))).toBe(false);
  expect(JSON.stringify(frozen)).not.toContain("exact reference");
});

test("snapshots allow empty M but reject empty S and foreign or duplicate retained references", () => {
  const valid = { memory: "", summary: "Continue the original task", renderedMemory: "", renderedSummary: "Summary",
    retainedParts: [{ messageId: "first", partIndex: 0 }], sourceWatermark: freezeContextSource([original]),
    statistics: { inputTokensBefore: 59000, inputTokensAfter: 20000, outputTokensAfter: 40000, elapsedMs: 10,
      auxiliaryInputTokens: 100, auxiliaryOutputTokens: 20 } };
  expect(sessionContextSnapshotSchema.safeParse(valid).success).toBe(true);
  for (const invalid of [{ ...valid, summary: " " },
    { ...valid, retainedParts: [...valid.retainedParts, ...valid.retainedParts] },
    { ...valid, retainedParts: [{ messageId: "foreign", partIndex: 0 }] },
    { ...valid, retainedParts: [{ messageId: "first", partIndex: 1 }] }]) {
    expect(sessionContextSnapshotSchema.safeParse(invalid).success).toBe(false);
  }
});
