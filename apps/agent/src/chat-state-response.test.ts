import { expect, test } from "vitest";
import { timelineResponse } from "./chat-state-response.js";
import type { ChatTimelineEntry } from "./chat-control.js";

test("public history excludes framework tool activity while preserving authored content and entry identities", () => {
  const createdAt = "2026-10-06T00:00:00Z";
  const turnId = "turn-1";
  const entries: ChatTimelineEntry[] = [
    { createdAt, turnId, entryId: "user-1", kind: "user_input", payload: { content: "Explain render_a2ui", inputId: "input-1", source: "prompt" } },
    { createdAt, turnId, entryId: "tool-1", kind: "tool_activity", payload: { name: "get_research_context", status: "complete" } },
    { createdAt, turnId, entryId: "tool-2", kind: "tool_activity", payload: { name: "render_a2ui", status: "complete" } },
    { createdAt, turnId, entryId: "outcome-1", kind: "turn_outcome", payload: { status: "completed" } },
  ];
  const publicPage = timelineResponse({ nextCursor: null, turns: [{ id: turnId, startedAt: createdAt, completedAt: createdAt, status: "completed", entries }] });
  expect(publicPage.turns[0]?.entries.map(entry => entry.entry_id)).toEqual(["user-1", "tool-1", "outcome-1"]);
  expect(publicPage.turns[0]?.entries[0]?.payload).toMatchObject({ content: "Explain render_a2ui" });
  expect(entries).toHaveLength(4);
});
