// @vitest-environment happy-dom

import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";

import { ChatTimeline } from "./ChatTimeline";
import type { ChatConversationController } from "./useChatConversation";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

test("renders a focusable log with full-width assistant text and right-aligned user input", async () => {
  await mount(controller({
    timeline: [
      entry("user_input", "user:1", { content: "My idea", inputId: INPUT_ID, source: "prompt" }),
      entry("assistant_message", "assistant:1", { content: "A measured response", status: "complete" }),
    ],
  }));

  const log = document.querySelector<HTMLElement>('[role="log"]');
  expect(log?.tabIndex).toBe(0);
  expect(log?.getAttribute("aria-live")).toBe("off");
  expect(document.querySelector(".chat-message-user")?.textContent).toContain("My idea");
  expect(document.querySelector(".chat-message-assistant")?.textContent).toContain("A measured response");
  expect(document.querySelector(".chat-message-assistant")?.textContent).not.toContain("Assistant");
});

test("shows the quiet first-response indicator once per active Turn", async () => {
  await mount(controller({
    currentTurnId: TURN_ID,
    hasFirstAssistantText: false,
    phase: "active",
    timeline: [entry("user_input", "user:1", { content: "My idea", inputId: INPUT_ID, source: "prompt" })],
  }));
  expect(document.querySelector(".chat-response-indicator")?.textContent).toContain("Working");

  await mount(controller({
    currentTurnId: TURN_ID,
    hasFirstAssistantText: true,
    phase: "active",
    timeline: [entry("assistant_message", "assistant:1", { content: "Started", status: "streaming" })],
  }));
  expect(document.querySelector(".chat-response-indicator")).toBeNull();
});

test("renders a structured pending question and sends selection changes to the controller", async () => {
  const setAnswerSelections = vi.fn();
  const question = {
    interrupt_id: `${TURN_ID}::tool-1`,
    options: [{ description: "Lower turnover", label: "Quality" }, { label: "Risk" }],
    question: "Which objective should lead?",
    selection_mode: "single_select" as const,
  };
  await mount(controller({
    phase: "waiting_for_user",
    question,
    setAnswerSelections,
    timeline: [entry("question", "question:1", { ...question, status: "pending" })],
  }));

  expect(document.querySelector(".chat-question")?.textContent).toContain("Which objective should lead?");
  const quality = document.querySelector<HTMLInputElement>('input[value="Quality"]')!;
  await act(async () => quality.click());
  expect(setAnswerSelections).toHaveBeenCalledWith(["Quality"]);
});

test("copies user and assistant text through the shared announcement channel", async () => {
  const announce = vi.fn();
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  await mount(controller({
    timeline: [entry("assistant_message", "assistant:1", { content: "Copy me", status: "complete" })],
  }), announce);

  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="Copy response"]')?.click());
  expect(writeText).toHaveBeenCalledWith("Copy me");
  expect(announce).toHaveBeenCalledWith("Copied to clipboard.");
});

test("preserves the first visible timeline item when older history is prepended", async () => {
  let olderLoaded = false;
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(
    <PaginationHarness onLoad={() => { olderLoaded = true; }} />,
  ));

  const viewport = document.querySelector<HTMLElement>('[role="log"]')!;
  const first = document.querySelector<HTMLElement>('[data-entry-id="assistant:1"]')!;
  const firstVisible = document.querySelector<HTMLElement>('[data-entry-id="assistant:2"]')!;
  vi.spyOn(viewport, "getBoundingClientRect").mockReturnValue(rect(100, 500));
  vi.spyOn(first, "getBoundingClientRect").mockImplementation(() => (
    olderLoaded ? rect(150, 190) : rect(40, 80)
  ));
  vi.spyOn(firstVisible, "getBoundingClientRect").mockImplementation(() => (
    olderLoaded ? rect(170, 210) : rect(140, 180)
  ));
  viewport.scrollTop = 250;

  await act(async () => {
    document.querySelector<HTMLButtonElement>(".chat-timeline-load-older")?.click();
    await Promise.resolve();
  });

  expect(viewport.scrollTop).toBe(280);
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
    setAnswerSelections: vi.fn(),
    setDraft: vi.fn(),
    steerStaged: vi.fn(async () => undefined),
    statusAnnouncement: "Ready.",
    textareaRef: { current: null },
    timeline: [],
    timelineError: false,
    ...overrides,
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
        timeline: [
          ...(loaded ? [entry("assistant_message", "assistant:0", { content: "Older", status: "complete" })] : []),
          entry("assistant_message", "assistant:1", { content: "Above viewport", status: "complete" }),
          entry("assistant_message", "assistant:2", { content: "First visible", status: "complete" }),
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

function entry(
  kind: "user_input" | "assistant_message" | "question",
  entryId: string,
  payload: Record<string, unknown>,
) {
  return {
    created_at: "2026-09-02T00:00:00.000000Z",
    entry_id: entryId,
    kind,
    payload,
    turn_id: TURN_ID,
  } as ChatConversationController["timeline"][number];
}

const TURN_ID = "00000000-0000-4000-8000-000000000001";
const INPUT_ID = "00000000-0000-4000-8000-000000000002";
