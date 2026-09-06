// @vitest-environment happy-dom

import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";

import type { TimelineEntry, TimelineTurn } from "./chatProtocol";
import { ChatTimeline } from "./ChatTimeline";
import type { ChatConversationController } from "./useChatConversation";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("renders each complete Turn in order with assistant text and right-aligned user input", async () => {
  await mount(controller({
    turns: [timelineTurn([
      entry("user_input", "user:1", { content: "My idea", inputId: INPUT_ID, source: "prompt" }),
      entry("assistant_message", "assistant:1", { content: "A measured response", status: "complete" }),
    ])],
  }));

  const log = document.querySelector<HTMLElement>('[role="log"]');
  expect(log?.tabIndex).toBe(0);
  expect(log?.getAttribute("aria-live")).toBe("off");
  expect(document.querySelector(".chat-message-user")?.textContent).toContain("My idea");
  expect(document.querySelector(".chat-message-assistant")?.textContent).toContain("A measured response");
  expect(document.querySelector(".chat-turn-assistant-meta")?.textContent).toContain("Worked for 1m 0s");
});

test("shows only a quiet ring before the first assistant text in the active Turn", async () => {
  await mount(controller({
    currentTurnId: TURN_ID,
    hasFirstAssistantText: false,
    phase: "active",
    turns: [timelineTurn([
      entry("user_input", "user:1", { content: "My idea", inputId: INPUT_ID, source: "prompt" }),
    ], { completed_at: null, status: "running" })],
  }));
  const indicator = document.querySelector(".chat-response-indicator");
  expect(indicator?.getAttribute("aria-label")).toContain("preparing a response");
  expect(indicator?.textContent).toBe("");

  await mount(controller({
    currentTurnId: TURN_ID,
    hasFirstAssistantText: true,
    phase: "active",
    turns: [timelineTurn([
      entry("assistant_message", "assistant:1", { content: "Started", status: "streaming" }),
    ], { completed_at: null, status: "running" })],
  }));
  expect(document.querySelector(".chat-response-indicator")).toBeNull();
});

test("groups only consecutive tool activity into collapsed inline disclosures", async () => {
  await mount(controller({
    turns: [timelineTurn([
      entry("assistant_message", "assistant:1", { content: "Checking.", status: "complete" }),
      entry("tool_activity", "tool:1", { name: "read_context", status: "complete" }),
      entry("tool_activity", "tool:2", { name: "run_factor", status: "running" }),
      entry("assistant_message", "assistant:2", { content: "Continuing.", status: "complete" }),
      entry("tool_activity", "tool:3", { name: "read_result", status: "failed" }),
    ])],
  }));

  const groups = [...document.querySelectorAll<HTMLDetailsElement>(".chat-tool-group")];
  expect(groups).toHaveLength(2);
  expect(groups[0]?.open).toBe(false);
  expect(groups[0]?.querySelector("summary")?.textContent).toContain("Using 2 tools");
  expect(groups[0]?.querySelector("summary")?.textContent).toContain("1 active");
  expect(groups[1]?.querySelector("summary")?.textContent).toContain("1 failed");
  const firstTool = groups[0]?.querySelector<HTMLElement>('[role="article"]');
  expect(firstTool?.getAttribute("aria-label")).toBe("Tool read_context: Completed");
  expect(firstTool?.textContent).toBe("read_contextCompleted");
});

test("announces a failed Turn with its public failure code", async () => {
  await mount(controller({
    turns: [timelineTurn([
      entry("turn_outcome", "outcome:1", { errorCode: "MCP_TRANSIENT", status: "failed" }),
    ], { status: "failed" })],
  }));

  const alert = document.querySelector<HTMLElement>('[role="alert"]');
  expect(alert?.getAttribute("data-failure-code")).toBe("MCP_TRANSIENT");
  expect(alert?.textContent).toContain("Turn failed");
});

test.each([
  ["OUTPUT_LIMIT", "Answer was truncated"],
  ["CONTEXT_COMPACTION_FAILED", "Conversation compression failed"],
  ["CONTEXT_TOO_LARGE", "Conversation exceeds model capacity"],
])("explains %s while retaining partial output and successful tools", async (errorCode, label) => {
  await mount(controller({ turns: [timelineTurn([
    entry("assistant_message", "assistant:partial", { content: "Partial answer retained", status: "complete" }),
    entry("tool_activity", "tool:done", { name: "submit_research_run", status: "complete" }),
    entry("turn_outcome", "outcome:1", { errorCode, status: "failed" }),
  ], { status: "failed" })] }));
  expect(document.querySelector('[role="alert"]')?.textContent).toContain(label);
  expect(document.querySelector('[role="alert"]')?.textContent).toContain("do not resubmit successful operations");
  expect(document.body.textContent).toContain("Partial answer retained");
  expect(document.body.textContent).toContain("Completed");
});

test("keeps a compact question activity and directs answering to the composer", async () => {
  const focusComposer = vi.fn();
  const question = {
    interrupt_id: `${TURN_ID}::tool-1`,
    options: [{ description: "Lower turnover", label: "Quality" }, { label: "Risk" }],
    question: "Which objective should lead?",
    selection_mode: "single_select" as const,
  };
  await mount(controller({
    phase: "waiting_for_user",
    question,
    focusComposer,
    turns: [timelineTurn([
      entry("question", "question:1", { ...question, status: "pending" }),
    ], { completed_at: null, status: "waiting_for_user" })],
  }));

  expect(document.querySelector(".chat-question-activity summary")?.textContent).toBe("Asking questions");
  expect(document.querySelector(".chat-question-activity p")?.textContent).toBe("Which objective should lead?");
  expect(document.querySelector(".chat-question-activity input")).toBeNull();
  await act(async () => document.querySelector<HTMLButtonElement>(".chat-question-waiting")?.click());
  expect(focusComposer).toHaveBeenCalledOnce();
});

test("copies the complete assistant response once while retaining user Copy", async () => {
  const announce = vi.fn();
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  await mount(controller({
    turns: [timelineTurn([
      entry("user_input", "user:1", { content: "My idea", inputId: INPUT_ID, source: "prompt" }),
      entry("assistant_message", "assistant:1", { content: "First", status: "complete" }),
      entry("assistant_message", "assistant:2", { content: "Second", status: "complete" }),
    ])],
  }), announce);

  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="Copy response"]')?.click());
  expect(writeText).toHaveBeenCalledWith("First\n\nSecond");
  expect(document.querySelector('[aria-label="Copy your message"]')).not.toBeNull();
  expect(announce).toHaveBeenCalledWith("Copied to clipboard.");
});

test("automatically loads older Turns and preserves the first visible Turn", async () => {
  let intersect!: () => void;
  class TestIntersectionObserver {
    constructor(private readonly callback: IntersectionObserverCallback) {
      intersect = () => this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
    }
    disconnect() {}
    observe() {}
    takeRecords() { return []; }
    unobserve() {}
  }
  vi.stubGlobal("IntersectionObserver", TestIntersectionObserver);
  let olderLoaded = false;
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(
    <PaginationHarness onLoad={() => { olderLoaded = true; }} />,
  ));

  const viewport = document.querySelector<HTMLElement>('[role="log"]')!;
  const first = document.querySelector<HTMLElement>(`[data-turn-id="${TURN_ID}"]`)!;
  const firstVisible = document.querySelector<HTMLElement>(`[data-turn-id="${TURN_ID_2}"]`)!;
  vi.spyOn(viewport, "getBoundingClientRect").mockReturnValue(rect(100, 500));
  vi.spyOn(first, "getBoundingClientRect").mockImplementation(() => (
    olderLoaded ? rect(150, 190) : rect(40, 80)
  ));
  vi.spyOn(firstVisible, "getBoundingClientRect").mockImplementation(() => (
    olderLoaded ? rect(170, 210) : rect(140, 180)
  ));
  viewport.scrollTop = 250;

  await act(async () => {
    intersect();
    await Promise.resolve();
  });

  expect(olderLoaded).toBe(true);
  expect(viewport.scrollTop).toBe(280);
  expect(document.querySelector(".chat-timeline-load-older")).toBeNull();
});

test("uses the controller's authoritative retry target for timeline failures", async () => {
  const retryTimeline = vi.fn(async () => undefined);
  const loadOlder = vi.fn(async () => true);
  await mount(controller({
    loadOlder,
    nextCursor: "older-page",
    retryTimeline,
    timelineError: true,
    turns: [timelineTurn([
      entry("assistant_message", "assistant:1", { content: "Retained", status: "complete" }),
    ])],
  }));

  await act(async () => document.querySelector<HTMLButtonElement>(".chat-timeline-error button")?.click());

  expect(retryTimeline).toHaveBeenCalledOnce();
  expect(loadOlder).not.toHaveBeenCalled();
});

async function mount(
  value: ChatConversationController,
  onAnnounce = vi.fn(),
): Promise<void> {
  if (root !== undefined) await act(async () => root?.unmount());
  document.body.replaceChildren();
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(<ChatTimeline controller={value} onAnnounce={onAnnounce} />));
}

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

function PaginationHarness({ onLoad }: { onLoad: () => void }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <ChatTimeline
      controller={controller({
        loadOlder: async () => {
          onLoad();
          setLoaded(true);
          return true;
        },
        nextCursor: loaded ? null : "older-page",
        turns: [
          ...(loaded ? [timelineTurn([
            entry("assistant_message", "assistant:0", { content: "Older", status: "complete" }, TURN_ID_0),
          ], { id: TURN_ID_0 })] : []),
          timelineTurn([
            entry("assistant_message", "assistant:1", { content: "Above viewport", status: "complete" }),
          ]),
          timelineTurn([
            entry("assistant_message", "assistant:2", { content: "First visible", status: "complete" }, TURN_ID_2),
          ], { id: TURN_ID_2 }),
        ],
      })}
      onAnnounce={vi.fn()}
    />
  );
}

function rect(top: number, bottom: number): DOMRect {
  return {
    bottom,
    height: bottom - top,
    left: 0,
    right: 760,
    top,
    width: 760,
    x: 0,
    y: top,
    toJSON: () => ({}),
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

const TURN_ID_0 = "00000000-0000-4000-8000-000000000000";
const TURN_ID = "00000000-0000-4000-8000-000000000001";
const TURN_ID_2 = "00000000-0000-4000-8000-000000000003";
const INPUT_ID = "00000000-0000-4000-8000-000000000002";

function researchSurface(id: string, status: string, runId = "run_0123456789abcdef0123"): TimelineEntry {
  return entry("a2ui", id, { activityType: "a2ui-surface", status: "ready", content: {
    a2ui_operations: [
      { version: "v0.9", createSurface: { catalogId: "urn:thesistrace:a2ui:research:v0.9", surfaceId: id } },
      { version: "v0.9", updateComponents: { surfaceId: id, components: [
        { id: "root", component: "Column", children: ["run"] },
        { id: "run", component: "ResearchRunStatus", runId, status, formula: "rank(close)" },
      ] } },
    ],
  } });
}

test("completed Turns omit progress while keeping distinct final results visible", async () => {
  await mount(controller({ turns: [timelineTurn([
    researchSurface("progress", "running"),
    researchSurface("result", "succeeded"),
    researchSurface("other-result", "succeeded", "run_abcdef0123456789abcd"),
    entry("assistant_message", "final", { content: "Both finished.", status: "complete" }),
  ])] }));
  expect(document.querySelector('[data-entry-id="progress"]')).toBeNull();
  expect(document.body.textContent).not.toContain("Last observed progress");
  expect(document.querySelector('[data-entry-id="result"]')?.closest("details")).toBeNull();
  expect(document.querySelector('[data-entry-id="other-result"]')?.closest("details")).toBeNull();
  expect(document.querySelector('[data-entry-id="final"]')?.closest("details")).toBeNull();
});

test("active Turns replace older progress only for the same research resources", async () => {
  await mount(controller({ turns: [timelineTurn([
    researchSurface("older", "queued"), researchSurface("newer", "running"),
    researchSurface("unrelated", "running", "run_abcdef0123456789abcd"),
  ], { status: "running", completed_at: null })] }));
  expect(document.querySelector('[data-entry-id="older"]')).toBeNull();
  expect(document.querySelector('[data-entry-id="newer"]')?.closest(".chat-progress-history")).toBeNull();
  expect(document.querySelector('[data-entry-id="unrelated"]')?.closest(".chat-progress-history")).toBeNull();
});

test("interrupted Turns do not add a stale progress card", async () => {
  await mount(controller({ turns: [timelineTurn([researchSurface("progress", "running")], { status: "failed" })] }));
  expect(document.querySelector('[data-entry-id="progress"]')).toBeNull();
});

test("Worked for folds the complete execution history but leaves the final answer outside", async () => {
  await mount(controller({ turns: [timelineTurn([
    entry("assistant_message", "before", { content: "Checking.", status: "complete" }),
    entry("tool_activity", "call-one", { name: "get_context", status: "complete" }),
    entry("assistant_message", "between", { content: "Checking results.", status: "complete" }),
    entry("tool_activity", "call-two", { name: "get_results", status: "complete" }),
    entry("assistant_message", "final", { content: "Finished.", status: "complete" }),
  ])] }));
  const work = document.querySelector<HTMLDetailsElement>(".chat-work-history")!;
  expect(work).not.toBeNull();
  expect(work.open).toBe(false);
  expect(work.querySelector("summary")?.textContent).toContain("Worked for");
  expect(work.querySelector('[data-entry-id="before"]')).not.toBeNull();
  expect(work.querySelector('[data-entry-id="between"]')).not.toBeNull();
  expect(work.querySelector('[data-entry-id="call-two"]')).not.toBeNull();
  expect(document.querySelector('[data-entry-id="final"]')?.closest(".chat-work-history")).toBeNull();
});

test("answered questions stay in the tool history with their answer, without a user bubble", async () => {
  await mount(controller({ turns: [timelineTurn([
    entry("user_input", "prompt", { source: "prompt", content: "Research", inputId: INPUT_ID }),
    entry("question", "question:1", { interrupt_id: `${TURN_ID}::ask`, status: "answered", question: "Which approach?", options: null, selection_mode: "free_text" }),
    entry("user_input", "answer", { source: "answer", content: "Default approach", inputId: INPUT_ID }),
    entry("assistant_message", "final", { content: "Submitted.", status: "complete" }),
  ])] }));
  expect(document.querySelectorAll('.chat-message-user')).toHaveLength(1);
  const tool = document.querySelector('[data-tool-name="ask_user"]');
  expect(tool).not.toBeNull();
  expect(tool?.closest('.chat-work-history')).not.toBeNull();
  expect(tool?.textContent).toContain("Which approach?");
  expect(tool?.textContent).toContain("Default approach");
  expect(document.body.textContent).not.toContain("Question answered");
});
