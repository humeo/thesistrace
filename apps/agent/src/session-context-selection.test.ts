import type { MastraDBMessage } from "@mastra/core/agent";
import { expect, test } from "vitest";
import { freezeContextSource } from "./session-context-state.js";
import { restoreContextTail, selectContextHistory } from "./session-context-selection.js";

function message(id: string, role: "user" | "assistant", text: string): MastraDBMessage {
  return { id, role, createdAt: new Date("2026-09-07T00:00:00Z"), content: { format: 2, parts: [{ type: "text", text }] } };
}

test("incremental cycles keep original sparse part identities and process a released request only once", () => {
  const history = [message("processed", "user", "already summarized"), message("prior-request", "user", "previous goal"),
    message("long-turn", "assistant", "already summarized prefix")];
  history[2]!.content.parts.push({ type: "text", text: "retained work ".repeat(100) });
  const previous = { sourceWatermark: freezeContextSource(history), retainedParts: [
    { messageId: "prior-request", partIndex: 0 }, { messageId: "long-turn", partIndex: 1 },
  ] };
  history[2]!.content.parts.push({ type: "text", text: "latest work" });
  history.push(message("next-request", "user", "new goal"));
  const second = selectContextHistory(history, { recentTokens: 35, currentRequestId: "next-request", previous });
  expect(second.retainedParts).toEqual([{ messageId: "long-turn", partIndex: 2 }, { messageId: "next-request", partIndex: 0 }]);
  expect(second.removed.map((item) => item.id)).toEqual(["prior-request", "long-turn"]);
  expect(second.removed[1]?.content.parts).toEqual([history[2]!.content.parts[1]]);
  const published = { retainedParts: second.retainedParts, sourceWatermark: freezeContextSource(history) };
  expect(restoreContextTail(history, published)).toEqual(second.retained);
  const third = selectContextHistory(history, { recentTokens: 35, currentRequestId: "next-request", previous: published });
  expect(third.removed).toEqual([]);
  expect(third.retainedParts).toEqual(second.retainedParts);
});

test("keeps the current request and a continuous recent tail while covering all removed parts exactly once", () => {
  const history = [message("old", "user", "archived fact ".repeat(100)), message("request", "user", "Find the exact result"),
    message("long-turn", "assistant", "early work ".repeat(100))];
  history[2]!.content.parts.push({ type: "text", text: "recent progress" });
  const selected = selectContextHistory(history, { recentTokens: 40, currentRequestId: "request" });
  expect(selected.retainedParts).toEqual([{ messageId: "request", partIndex: 0 }, { messageId: "long-turn", partIndex: 1 }]);
  expect(selected.removed.map((m) => m.id)).toEqual(["old", "long-turn"]);
  expect(selected.removed[1]!.content.parts).toEqual([history[2]!.content.parts[0]]);
  expect(history[2]!.content.parts).toHaveLength(2);
});

test("retains complete tool and reasoning steps and all pending interactions", () => {
  const history = [message("old", "user", "old fact ".repeat(1000)), message("pending", "assistant", "reasoning")];
  history[1]!.content.parts.push({ type: "tool-invocation", toolInvocation: {
    toolCallId: "waiting", toolName: "ask_user", args: { question: "Choose" }, state: "call",
  } });
  const completed = message("tool-step", "assistant", "explained decision");
  completed.content.parts.push({ type: "tool-invocation", toolInvocation: {
    toolCallId: "read", toolName: "read", args: { cursor: "exact" }, state: "result", result: { next_cursor: "next" },
  } });
  history.push(completed);
  const selected = selectContextHistory(history, { recentTokens: 120 });
  expect(selected.retained.map((m) => m.id)).toEqual(["pending", "tool-step"]);
  expect(selected.retained.at(-1)?.content.parts).toEqual(completed.content.parts);
  expect(selected.removed.map((m) => m.id)).toEqual(["old"]);
});

test("restores the same retained prefix and only appends messages and parts after the frozen watermark", () => {
  const history = [message("old", "user", "old"), message("keep", "assistant", "stable")];
  const sourceWatermark = freezeContextSource(history);
  const retainedParts = [{ messageId: "keep", partIndex: 0 }];
  const appended = structuredClone(history);
  appended[1]!.content.parts.push({ type: "text", text: "new part" });
  appended.push(message("new", "user", "next question"));
  const restored = restoreContextTail(appended, { sourceWatermark, retainedParts });
  expect(restored.map((m) => m.id)).toEqual(["keep", "new"]);
  expect(restored[0]?.content.parts).toEqual(appended[1]!.content.parts);
  expect(restored[0]?.content.parts[0]).toEqual(history[1]!.content.parts[0]);
  appended[0]!.content.parts[0] = { type: "text", text: "rewritten" };
  expect(() => restoreContextTail(appended, { sourceWatermark, retainedParts })).toThrow("CONTEXT_SOURCE_CHANGED");
});

test("a completed last tool larger than the tail budget goes entirely into E", () => {
  const request = message("request", "user", "Continue reading");
  const tool = message("tool", "assistant", "A completed call");
  tool.content.parts.push({ type: "tool-invocation", toolInvocation: { state: "result", toolCallId: "large",
    toolName: "read", args: { cursor: "exact" }, result: { evidence: "large evidence ".repeat(20_000) } } });
  const selected = selectContextHistory([request, tool], { recentTokens: 20_000, currentRequestId: "request" });
  expect(selected.retained).toEqual([request]);
  expect(selected.removed).toEqual([tool]);
});
