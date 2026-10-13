import { expect, test } from "vitest";
import { chatViewMessages, projectChatEntries, WORK_ACTIVITY } from "./chatViewMessages";
import type { TimelineEntry, TimelineTurn } from "./chatProtocol";

const time = "2026-09-30T14:23:00Z";
function entry(kind: TimelineEntry["kind"], id: string, payload: object): TimelineEntry {
  return { kind, entry_id: id, turn_id: "turn", created_at: time, payload } as TimelineEntry;
}
function turn(entries: TimelineEntry[], status: TimelineTurn["status"] = "completed"): TimelineTurn {
  return { id: "turn", entries, status, started_at: time, completed_at: status === "running" ? null : "2026-09-30T14:23:06Z" };
}
test("restores user input, process and final reply in order with server completion time", () => {
  const messages = chatViewMessages([turn([
    entry("user_input", "prompt", { content: "Research quality", inputId: "input", source: "prompt" }),
    entry("assistant_message", "process", { content: "Checking", status: "complete" }),
    entry("tool_activity", "call", { name: "run_factor", status: "complete" }),
    entry("assistant_message", "reply", { content: "Finished", status: "complete" }),
    entry("turn_outcome", "outcome", { status: "completed" }),
  ])]);
  expect(messages.map(message => message.role)).toEqual(["user", "activity", "assistant"]);
  expect(messages[0]?.timestamp).toBe(time);
  expect(messages[2]?.timestamp).toBe("2026-09-30T14:23:06Z");
  expect(messages[1]).toMatchObject({ activityType: WORK_ACTIVITY, content: { entries: [{ entry_id: "process" }, { entry_id: "call" }] } });
});
test("question answers are paired by timeline order even when timestamps are equal", () => {
  const question = { interrupt_id: "ask", options: null, selection_mode: "free_text", question: "Which?", status: "answered" };
  const messages = projectChatEntries([
    entry("question", "first", question),
    entry("user_input", "a1", { source: "answer", content: "Quality", inputId: "answer1" }),
    entry("question", "second", question),
    entry("user_input", "a2", { source: "answer", content: "Liquidity", inputId: "answer2" }),
  ]);
  expect(messages).toHaveLength(2);
  expect(messages[0]).toMatchObject({ content: { answer: { content: "Quality" } } });
  expect(messages[1]).toMatchObject({ content: { answer: { content: "Liquidity" } } });
});
test("accepted Steer stays below earlier work and above subsequent work in the same Turn", () => {
  const entries = [
    entry("user_input", "prompt", { content: "List my research", inputId: "prompt", source: "prompt" }),
    entry("tool_activity", "before", { name: "list_research_runs", status: "complete" }),
    entry("user_input", "steer", { content: "Sort by Sharpe instead", inputId: "steer", source: "steer" }),
    entry("tool_activity", "after", { name: "get_research_run", status: "complete" }),
    entry("assistant_message", "reply", { content: "Here are the candidates", status: "complete" }),
  ];
  const messages = chatViewMessages([turn(entries)]);
  expect(messages.map(message => message.role)).toEqual(["user", "activity", "user", "activity", "assistant"]);
  expect(messages[1]).toMatchObject({ activityType: WORK_ACTIVITY, content: { entries: [{ entry_id: "before" }], turn: { id: "turn" } } });
  expect(messages[2]).toMatchObject({ id: "steer", content: "Sort by Sharpe instead" });
  expect(messages[3]).toMatchObject({ activityType: WORK_ACTIVITY, content: { entries: [{ entry_id: "after" }], turn: { id: "turn" } } });
  expect(messages.at(-1)).toMatchObject({ id: "reply", timestamp: "2026-09-30T14:23:06Z" });
});

test("Steer accepted before the next model output remains below completed tools while running", () => {
  const messages = chatViewMessages([turn([
    entry("user_input", "prompt", { content: "List my research", inputId: "prompt", source: "prompt" }),
    entry("tool_activity", "before", { name: "list_research_runs", status: "complete" }),
    entry("user_input", "steer", { content: "Continue", inputId: "steer", source: "steer" }),
  ], "running")]);
  expect(messages.map(message => message.role)).toEqual(["user", "activity", "user", "activity"]);
  expect(messages[1]).toMatchObject({ content: { entries: [{ entry_id: "before" }] } });
  expect(messages[2]).toMatchObject({ id: "steer" });
  expect(messages[3]).toMatchObject({ content: { entries: [] } });
});

test("later Steer tools do not fold a reply that was already visible", () => {
  const messages = chatViewMessages([turn([
    entry("user_input", "prompt", { content: "List my research", inputId: "prompt", source: "prompt" }),
    entry("assistant_message", "earlier-reply", { content: "Here is the list", status: "complete" }),
    entry("user_input", "steer", { content: "Compare these", inputId: "steer", source: "steer" }),
    entry("tool_activity", "after", { name: "get_research_run", status: "complete" }),
    entry("assistant_message", "later-reply", { content: "Here is the comparison", status: "complete" }),
  ])]);
  const reply = messages.findIndex(message => message.id === "earlier-reply");
  const steer = messages.findIndex(message => message.id === "steer");
  expect(reply).toBeGreaterThan(-1);
  expect(reply).toBeLessThan(steer);
  expect(messages[reply]?.timestamp).toBeUndefined();
  expect(messages.at(-1)).toMatchObject({ id: "later-reply", timestamp: "2026-09-30T14:23:06Z" });
});

test.each(["complete", "failed", "stopped"])("terminal %s tool status remains available without fabricating tool arguments or results", status => {
  const tool = entry("tool_activity", "call", { name: "run_factor", status });
  expect(projectChatEntries([tool])).toMatchObject([{ id: "call", role: "activity", content: { entry: tool } }]);
});
test("running tools have no premature tool result and recovery text stays outside folded history", () => {
  const recovery = { status: "recovering", attempts: 1, cause: "OUTPUT_LIMIT", errorCode: null, replacementMessageId: "new" };
  const messages = chatViewMessages([turn([
    entry("assistant_message", "partial", { content: "Retain me", status: "complete", recovery }),
    entry("tool_activity", "call", { name: "run_factor", status: "running" }),
  ], "running")]);
  expect(messages.find(message => message.id === "partial")).toMatchObject({ content: "Retain me", entry: { payload: { recovery } } });
  expect(projectChatEntries([entry("tool_activity", "call", { name: "run_factor", status: "running" })])).toHaveLength(1);
});
test("a later research view supersedes only the same resource", () => {
  const surface = (id: string, runId: string) => entry("a2ui", id, { activityType: "a2ui-surface", status: "ready", content: { a2ui_operations: [
    { version: "v0.9", createSurface: { surfaceId: id, catalogId: "urn:thesistrace:a2ui:research:v0.9" } },
    { version: "v0.9", updateComponents: { surfaceId: id, components: [{ id: "root", component: "ResearchRun", runId }] } },
  ] } });
  const messages = chatViewMessages([turn([
    surface("old", "run_0123456789abcdef0123"),
    surface("latest", "run_0123456789abcdef0123"),
    surface("other", "run_abcdef0123456789abcd"),
  ])]);
  expect(messages.map(message => message.id)).toEqual(["work:turn", "latest", "other"]);
});

test("refreshing a resource preserves an earlier view's unique explanation", () => {
  const surface = (id: string, components: object[]) => entry("a2ui", id, { activityType: "a2ui-surface", status: "ready", content: { a2ui_operations: [
    { version: "v0.9", createSurface: { surfaceId: id, catalogId: "urn:thesistrace:a2ui:research:v0.9" } },
    { version: "v0.9", updateComponents: { surfaceId: id, components } },
  ] } });
  const runId = "run_0123456789abcdef0123";
  const messages = chatViewMessages([turn([
    surface("explained", [
      { component: "Column", id: "root", children: ["reason", "run"] },
      { component: "Text", id: "reason", text: "This experiment distinguishes quality from momentum." },
      { component: "ResearchRun", id: "run", runId },
    ]),
    surface("latest", [{ component: "ResearchRun", id: "root", runId }]),
  ])]);
  expect(messages.map(message => message.id)).toContain("explained");
});
