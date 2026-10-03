// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { notifyManager } from "@tanstack/react-query";
import { ChatTimeline } from "./ChatTimeline";
import { ChatTestProvider } from "./chatTestProvider";
import { ChatConversationView } from "./ChatConversation";
import { changeInterfaceLanguage } from "../i18n";
import type { TimelineEntry, TimelineTurn } from "./chatProtocol";
import type { ChatConversationController } from "./useChatConversation";
import * as core from "../auth/coreFetch";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
beforeEach(() => notifyManager.setNotifyFunction(callback => { act(callback); }));
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  await changeInterfaceLanguage("en"); document.body.replaceChildren(); vi.restoreAllMocks(); vi.useRealTimers();
  notifyManager.setNotifyFunction(callback => callback());
});
async function mount(value: ChatConversationController, full = false) {
  const container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root?.render(<ChatTestProvider controller={value}>{full
    ? <ChatConversationView controller={value} existingSession agentId="default" threadId="test" modelControls={null} />
    : <ChatTimeline controller={value} />}</ChatTestProvider>));
}
test("only the latest turn reads its last five distinct research resources by their latest occurrence", async () => {
  const requested: string[] = [];
  vi.spyOn(core, "coreFetch").mockImplementation(async input => {
    const id = String(input).split("/").at(-1)!;
    requested.push(id);
    if (id === "run_44444444444444444444") return new Response("", { status: 503 });
    return new Response(JSON.stringify({ id, name: `Research ${id}`, status: "running", research_kind: "factor_evaluation",
      formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-09-01" }));
  });
  const ids = Array.from({ length: 8 }, (_, index) => `run_${String(index).repeat(20)}`);
  const latest = timelineTurn([
    ...researchTurn("first-view", ids.slice(0, 4)).entries,
    ...researchTurn("repeat-view", ids[0]!).entries,
    ...researchTurn("last-view", ids.slice(4)).entries,
  ].map(value => ({ ...value, turn_id: "latest" })), { id: "latest" });
  const turns = [researchTurn("older", ids[0]!), latest];
  await mount(controller({ turns }));
  await vi.waitFor(() => expect(document.querySelectorAll('section[aria-label^="ResearchRun "] time')).toHaveLength(5));
  const eligible = [ids[0], ...ids.slice(4)];
  expect(requested).toEqual(eligible);
  expect(document.querySelectorAll('section[aria-label^="ResearchRun "]')).toHaveLength(6);
  expect(document.querySelectorAll('[role="alert"]')).toHaveLength(1);
  const overflow = document.querySelector('[data-entry-id="research:first-view"]')!;
  expect([...overflow.querySelectorAll("a")].slice(1).map(a => a.getAttribute("href")))
    .toEqual(ids.slice(1, 4).map(id => `/research-runs/${id}`));
  expect(document.querySelectorAll('[data-entry-id="research:last-view"] section')).toHaveLength(4);
  const older = document.querySelector(`[data-entry-id="research:older"]`)!;
  expect(older.querySelector("a")?.getAttribute("href")).toBe(`/research-runs/${ids[0]}`);
  expect(older.querySelector("button, [role=status], [role=alert]")).toBeNull();
  expect(document.body.textContent).toContain("Answer older");

  const next = controller({ turns: [researchTurn("older-turn", "run_99999999999999999999"), ...turns, timelineTurn([
    entry("user_input", "new-prompt", { content: "Next question", inputId: INPUT_ID, source: "prompt" }, "new-turn"),
  ], { id: "new-turn", status: "running", completed_at: null })] });
  await act(async () => root?.render(<ChatTestProvider controller={next}><ChatTimeline controller={next} /></ChatTestProvider>));
  await vi.waitFor(() => expect(document.querySelectorAll('section[aria-label^="ResearchRun "]')).toHaveLength(0));
  expect(requested).toEqual(eligible);
  expect(document.querySelector('[data-entry-id="research:first-view"] button')).toBeNull();
});

function researchTurn(id: string, runId: string | string[]): TimelineTurn {
  return timelineTurn([
    entry("a2ui", `research:${id}`, { activityType: "a2ui-surface", status: "ready", content: { a2ui_operations: [
      { version: "v0.9", createSurface: { catalogId: "urn:thesistrace:a2ui:research:v0.9", surfaceId: id } },
      { version: "v0.9", updateComponents: { surfaceId: id, components: [Array.isArray(runId)
        ? { component: "ResearchComparison", id: "root", runIds: runId }
        : { component: "ResearchRun", id: "root", runId }] } },
    ] } }, id),
    entry("assistant_message", `answer:${id}`, { content: `Answer ${id}`, status: "complete" }, id),
  ], { id });
}
test("the last-five budget follows layout display order and includes tracking references", async () => {
  const runs = Array.from({ length: 5 }, (_, index) => `run_${String(index).repeat(20)}`);
  const trackId = "track_11111111111111111111";
  const requested: string[] = [];
  vi.spyOn(core, "coreFetch").mockImplementation(async input => {
    requested.push(String(input));
    return new Response("", { status: 503 });
  });
  await mount(controller({ turns: [timelineTurn([
    entry("a2ui", "ordered-resources", { activityType: "a2ui-surface", status: "ready", content: { a2ui_operations: [
      { version: "v0.9", createSurface: { catalogId: "urn:thesistrace:a2ui:research:v0.9", surfaceId: "ordered-resources" } },
      { version: "v0.9", updateComponents: { surfaceId: "ordered-resources", components: [
        { component: "ResearchRun", id: "overflow", runId: runs[4] },
        { component: "DailyTrack", id: "tracking", trackId },
        { component: "ResearchComparison", id: "research", runIds: runs.slice(0, 4) },
        { component: "Column", id: "root", children: ["research", "tracking", "overflow"] },
      ] } },
    ] } }),
  ])] }));
  await vi.waitFor(() => expect(document.querySelectorAll('[role="alert"]')).toHaveLength(5));
  expect(requested).toEqual([...runs.slice(1, 4).map(id => `/api/research-runs/${id}`), `/api/daily-tracks/${trackId}`, `/api/research-runs/${runs[4]}`]);
  expect(document.querySelector(`a[href="/research-runs/${runs[0]}"]`)?.textContent).toBe(`View research: ${runs[0]}`);
});
test("repeated references in the latest turn share reads and refresh together, then read again on reopening", async () => {
  const runId = "run_11111111111111111111";
  let finish!: (response: Response) => void;
  const response = (name: string) => new Response(JSON.stringify({ id: runId, name, status: "running", research_kind: "factor_evaluation",
    formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-09-01" }));
  const request = vi.spyOn(core, "coreFetch").mockImplementation(input => String(input).endsWith(runId)
    ? new Promise<Response>(resolve => { finish = resolve; })
    : Promise.resolve(new Response(JSON.stringify({ id: String(input).split("/").at(-1), name: "Other research", status: "cancelled",
      research_kind: "factor_evaluation", formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-09-01" }))));
  const value = controller({ turns: [timelineTurn([
    ...researchTurn("first", runId).entries,
    ...researchTurn("second", [runId, "run_22222222222222222222"]).entries,
    ...researchTurn("third", [runId, "run_33333333333333333333"]).entries,
  ].map(value => ({ ...value, turn_id: "latest" })), { id: "latest" })] });
  await mount(value);
  expect(request.mock.calls.filter(([input]) => String(input).endsWith(runId))).toHaveLength(1);
  await act(async () => finish(response("Shared research")));
  await vi.waitFor(() => expect([...document.querySelectorAll(`a[href="/research-runs/${runId}"]`)].map(a => a.textContent))
    .toEqual(["Shared research", "Shared research", "Shared research"]));

  request.mockResolvedValueOnce(response("Refreshed research"));
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="Reload view: Shared research"]')!.click());
  await vi.waitFor(() => expect([...document.querySelectorAll(`a[href="/research-runs/${runId}"]`)].map(a => a.textContent))
    .toEqual(["Refreshed research", "Refreshed research", "Refreshed research"]));
  expect(request.mock.calls.filter(([input]) => String(input).endsWith(runId))).toHaveLength(2);
  await act(async () => root?.unmount());
  await mount(value);
  await act(async () => finish(response("Reopened research")));
  await vi.waitFor(() => expect(document.body.textContent).toContain("Reopened research"));
  expect(request.mock.calls.filter(([input]) => String(input).endsWith(runId))).toHaveLength(3);
});
test("a new turn revalidates unfinished research and turns the earlier reference into a link", async () => {
  const runId = "run_11111111111111111111";
  const request = vi.spyOn(core, "coreFetch").mockResolvedValueOnce(new Response(JSON.stringify({ id: runId, name: "Running research",
    status: "running", research_kind: "factor_evaluation", formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-09-01" })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: runId, name: "Finished research", status: "cancelled", research_kind: "factor_evaluation",
      formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-09-01" })));
  const first = researchTurn("first", runId);
  await mount(controller({ turns: [first] }));
  await vi.waitFor(() => expect(document.body.textContent).toContain("Running research"));
  const next = controller({ turns: [first, researchTurn("second", runId)] });
  await act(async () => root?.render(<ChatTestProvider controller={next}><ChatTimeline controller={next} /></ChatTestProvider>));
  await vi.waitFor(() => expect([...document.querySelectorAll(`a[href="/research-runs/${runId}"]`)].map(a => a.textContent))
    .toEqual([`View research: ${runId}`, "Finished research"]));
  expect(request).toHaveBeenCalledTimes(2);
});
test("uses native message Copy controls and server timestamps across languages", async () => {
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  await mount(controller({ turns: [timelineTurn([
    entry("user_input", "user", { content: "My idea", inputId: INPUT_ID, source: "prompt" }),
    entry("assistant_message", "reply", { content: "**完整原文**", status: "complete" }),
  ])] }));
  expect(document.querySelector(".ant-bubble-list")).not.toBeNull();
  expect(document.body.textContent).toContain("Worked for 1m 0s");
  expect(document.querySelector("time")?.textContent).toMatch(/^\d{1,2}:\d{2} (AM|PM)$/);
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="Copy response"]')!.click());
  expect(writeText).toHaveBeenCalledWith("**完整原文**");
  await act(async () => changeInterfaceLanguage("zh-CN"));
  expect(document.body.textContent).toContain("工作耗时 1 分 0 秒");
  expect(document.querySelector('[aria-label="Copy message"]')).not.toBeNull();
  expect(document.body.textContent).toContain("My idea");
});
test("shows elapsed work immediately after a running prompt before any model output", async () => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  vi.setSystemTime(new Date("2026-09-02T00:00:05Z"));
  const prompt = entry("user_input", "user", { content: "Check the latest research", inputId: INPUT_ID, source: "prompt" });
  await mount(controller({ phase: "active", currentTurnId: TURN_ID, hasFirstAssistantText: false,
    turns: [timelineTurn([prompt], { status: "running", completed_at: null })] }));
  expect(document.body.textContent).toContain("Working for 5s");
  await act(async () => vi.advanceTimersByTime(2_000));
  expect(document.body.textContent).toContain("Working for 7s");
  await act(async () => changeInterfaceLanguage("zh-CN"));
  expect(document.body.textContent).toContain("已工作 7 秒");
  const next = controller({ turns: [timelineTurn([prompt,
    entry("assistant_message", "reply", { content: "Finished", status: "complete" }),
  ], { completed_at: "2026-09-02T00:00:12Z" })] });
  await act(async () => root?.render(<ChatTestProvider controller={next}><ChatTimeline controller={next} /></ChatTestProvider>));
  expect(document.body.textContent).toContain("工作耗时 12 秒");
});
test("native work disclosure retains process text and successful tool results", async () => {
  await mount(controller({ turns: [timelineTurn([
    entry("assistant_message", "process", { content: "Checking quality", status: "complete" }),
    entry("tool_activity", "tool", { name: "run_factor", status: "complete" }),
    entry("assistant_message", "final", { content: "Finished", status: "complete" }),
  ])] }));
  expect(document.body.textContent).toContain("Finished");
  const work = document.querySelector<HTMLElement>(".ant-think-status-wrapper")!;
  expect(work.querySelector("button")).toBeNull();
  await act(async () => work.click());
  expect(document.body.textContent).toContain("Checking quality");
  expect(document.body.textContent).toContain("run_factor");
});
test.each(["completed", "failed", "stopped"] as const)("keeps process expanded while executing, folds on %s and can reopen", async status => {
  const entries = [entry("tool_activity", "tool", { name: "run_factor", status: "complete" })];
  await mount(controller({ phase: "active", turns: [timelineTurn(entries, { status: "running", completed_at: null })] }));
  expect(document.body.textContent).toContain("run_factor");
  const stopping = controller({ phase: "stopping", turns: [timelineTurn(entries, { status: "stopping", completed_at: null })] });
  await act(async () => root?.render(<ChatTestProvider controller={stopping}><ChatTimeline controller={stopping} /></ChatTestProvider>));
  expect(document.body.textContent).toContain("run_factor");
  const finished = controller({ turns: [timelineTurn(entries, { status })] });
  await act(async () => root?.render(<ChatTestProvider controller={finished}><ChatTimeline controller={finished} /></ChatTestProvider>));
  await vi.waitFor(async () => {
    await act(async () => {});
    expect(document.body.textContent).not.toContain("run_factor");
  });
  await act(async () => document.querySelector<HTMLElement>(".ant-think-status-wrapper")!.click());
  expect(document.body.textContent).toContain("run_factor");
});
test("work history is one connected chain with compact tool operations and retained answers", async () => {
  await mount(controller({ turns: [timelineTurn([
    entry("assistant_message", "process", { content: "Checking **quality**", status: "complete" }),
    entry("tool_activity", "first", { name: "get_context", status: "complete" }),
    entry("tool_activity", "second", { name: "run_factor", status: "complete" }),
    entry("question", "question", { interrupt_id: "ask", options: null, selection_mode: "free_text", question: "Which objective?", status: "answered" }),
    entry("user_input", "answer", { content: "Quality\nand liquidity", inputId: INPUT_ID, source: "answer" }),
    entry("tool_activity", "third", { name: "submit_research", status: "complete" }),
    entry("assistant_message", "final", { content: "Finished", status: "complete" }),
  ])] }));
  await act(async () => document.querySelector<HTMLElement>(".ant-think-status-wrapper")!.click());
  const work = document.querySelector(".ant-think-content")!;
  expect(work.querySelectorAll(".ant-thought-chain-box")).toHaveLength(1);
  expect(work.querySelector(".ant-card")).not.toBeNull();
  expect(work.querySelector("button")).toBeNull();
  expect(work.querySelector(".ant-bubble")).toBeNull();
  expect(work.querySelector(".ant-thought-chain-node-footer")).toBeNull();
  expect(work.querySelector("strong")?.textContent).toBe("quality");
  const question = [...work.querySelectorAll<HTMLElement>(".ant-thought-chain-node-title")].find(title => title.textContent === "Question answered")!;
  await act(async () => question.click());
  expect(work.textContent).toContain("Which objective?");
  expect(work.textContent).toContain("Quality\nand liquidity");
  await act(async () => [...work.querySelectorAll<HTMLElement>(".ant-thought-chain-node-title")].find(title => title.textContent === "Used 1 tool")!.click());
  const order = work.textContent!;
  expect(order.indexOf("get_context")).toBeLessThan(order.indexOf("Question answered"));
  expect(order.indexOf("Quality\nand liquidity")).toBeLessThan(order.indexOf("submit_research"));
});
test("tool operations distinguish running, failed and stopped states without marking stops successful", async () => {
  await mount(controller({ turns: [timelineTurn([
    entry("tool_activity", "complete", { name: "completed_operation", status: "complete" }),
    entry("tool_activity", "failed", { name: "failed_operation", status: "failed" }),
    entry("tool_activity", "stopped", { name: "stopped_operation", status: "stopped" }),
    entry("tool_activity", "running", { name: "running_operation", status: "running" }),
  ], { status: "running", completed_at: null })] }));
  for (const [name, status] of [["completed", "Completed"], ["failed", "Failed"], ["stopped", "Stopped"], ["running", "Running"]]) {
    const operation = document.querySelector(`[aria-label="Tool ${name}_operation: ${status}"]`)!;
    expect(operation).not.toBeNull();
    expect(operation.textContent).toContain(status);
    if (name === "stopped") expect(operation.querySelector('.anticon-check-circle')).toBeNull();
  }
});
test.each(["recovering", "succeeded", "failed"] as const)("retains partial answer and durable %s recovery", async status => {
  await mount(controller({ turns: [timelineTurn([entry("assistant_message", "partial", {
    content: "Partial retained", status: "complete", recovery: { status, cause: "OUTPUT_LIMIT", attempts: 1, replacementMessageId: INPUT_ID, errorCode: null },
  })])] }));
  expect(document.body.textContent).toContain("Partial retained");
  expect(document.querySelector('[role="status"]')).not.toBeNull();
});
test("recovery and completion metadata update even when the answer text is unchanged", async () => {
  const partial = (status: "recovering" | "succeeded") => entry("assistant_message", "partial", {
    content: "Partial retained", status: "complete", recovery: { status, cause: "OUTPUT_LIMIT", attempts: 1, replacementMessageId: INPUT_ID, errorCode: null },
  });
  await mount(controller({ phase: "recovering", turns: [timelineTurn([partial("recovering")], { status: "running", completed_at: null })] }));
  expect(document.querySelector('[role="status"]')?.textContent).toContain("preparing a replacement");
  const next = controller({ turns: [timelineTurn([partial("succeeded")])] });
  await act(async () => root?.render(<ChatTestProvider controller={next}><ChatTimeline controller={next} /></ChatTestProvider>));
  expect(document.querySelector('[role="status"]')?.textContent).toContain("replaced by the complete answer below");
  expect(document.querySelector("time")?.getAttribute("datetime")).toBe("2026-09-02T00:01:00.000000Z");
});
test.each([["MCP_TRANSIENT", "Turn failed"], ["OUTPUT_LIMIT", "Answer was truncated"], ["CONTEXT_TOO_LARGE", "Conversation exceeds model capacity"]])("explains failed %s without losing partial text", async (errorCode, label) => {
  await mount(controller({ turns: [timelineTurn([
    entry("assistant_message", "partial", { content: "Keep this answer", status: "failed" }),
    entry("turn_outcome", "outcome", { status: "failed", errorCode }),
  ], { status: "failed" })] }));
  expect(document.querySelector('[role="alert"]')?.textContent).toContain(label);
  expect(document.body.textContent).toContain("Keep this answer");
});
test("pending question uses existing controls and focuses the composer", async () => {
  const focusComposer = vi.fn();
  await mount(controller({ focusComposer, phase: "waiting_for_user", turns: [timelineTurn([
    entry("question", "question", { interrupt_id: "ask", options: null, selection_mode: "free_text", question: "Which objective?", status: "pending" }),
  ], { status: "waiting_for_user", completed_at: null })] }));
  await act(async () => document.querySelector<HTMLButtonElement>(".chat-question-waiting")!.click());
  expect(focusComposer).toHaveBeenCalledOnce();
});
test("older history and retry use authoritative controller commands", async () => {
  const loadOlder = vi.fn(); const retryTimeline = vi.fn();
  await mount(controller({ nextCursor: "older", timelineError: true, loadOlder, retryTimeline }), true);
  await act(async () => [...document.querySelectorAll("button")].find(button => button.textContent === "Load more")!.click());
  await act(async () => [...document.querySelectorAll("button")].find(button => button.textContent === "Retry")!.click());
  expect(loadOlder).toHaveBeenCalledOnce(); expect(retryTimeline).toHaveBeenCalledOnce();
});
function controller(overrides: Partial<ChatConversationController> = {}): ChatConversationController {
  return {
    action: { enabled: false, kind: "send", label: "Send" },
    answerSelections: [],
    currentTurnId: null,
    draft: "",
    draftBytes: 0,
    editStaged: vi.fn(async () => undefined),
    error: null,
    executeMainAction: vi.fn(async () => undefined),
    focusComposer: vi.fn(),
    hasFirstAssistantText: true,
    loadOlder: vi.fn(async () => true),
    loadingOlder: false,
    latestTurnId: null,
    latestTurnStatus: null,
    nextCursor: null,
    phase: "idle",
    question: null,
    queue: [],
    queueLocked: false,
    refresh: vi.fn(async () => undefined),
    removeStaged: vi.fn(async () => undefined),
    retryRecovery: vi.fn(async () => undefined),
    retryTimeline: vi.fn(async () => undefined),
    setAnswerSelections: vi.fn(),
    setDraft: vi.fn(),
    steerStaged: vi.fn(async () => undefined),
    stopTurn: vi.fn(async () => undefined),
    statusAnnouncement: "Ready.",
    textareaRef: { current: null },
    timelineError: false,
    turns: [],
    ...overrides,
    errorCode: overrides.errorCode ?? null,
  };
}

function timelineTurn(
  entries: readonly TimelineEntry[],
  overrides: Partial<TimelineTurn> = {},
): TimelineTurn {
  return {
    completed_at: "2026-09-02T00:01:00.000000Z",
    entries,
    id: TURN_ID,
    started_at: "2026-09-02T00:00:00.000000Z",
    status: "completed",
    ...overrides,
  };
}

function entry(
  kind: TimelineEntry["kind"],
  entryId: string,
  payload: Record<string, unknown>,
  turnId = TURN_ID,
): TimelineEntry {
  return {
    created_at: "2026-09-02T00:00:00.000000Z",
    entry_id: entryId,
    kind,
    payload,
    turn_id: turnId,
  } as TimelineEntry;
}

const TURN_ID = "00000000-0000-4000-8000-000000000001";
const INPUT_ID = "00000000-0000-4000-8000-000000000002";
