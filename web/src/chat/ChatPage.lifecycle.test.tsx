// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";

import { ChatComposer } from "./ChatComposer";
import type { StagedInput } from "./stagedInputStore";
import type { ChatConversationController } from "./useChatConversation";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  document.body.replaceChildren();
});

test.each([
  ["send", "Send"],
  ["stage", "Stage"],
  ["stop", "Stop"],
  ["answer", "Send answer"],
  ["continue", "Continue"],
] as const)("renders the state machine's %s primary action with an action name", async (kind, label) => {
  const execute = vi.fn(async () => undefined);
  await mount(composerController({ action: { enabled: true, kind, label }, executeMainAction: execute }));
  const button = document.querySelector<HTMLButtonElement>(`.chat-main-action-${kind}`);
  expect(button?.getAttribute("aria-label")).toBe(label);
  await act(async () => button?.click());
  expect(execute).toHaveBeenCalledOnce();
});

test("Enter submits textual actions while Shift+Enter and an empty Stop do not", async () => {
  const execute = vi.fn(async () => undefined);
  await mount(composerController({
    action: { enabled: true, kind: "stage", label: "Stage" },
    draft: "Investigate quality",
    executeMainAction: execute,
  }));
  const textarea = document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')!;
  await act(async () => textarea.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" })));
  expect(execute).toHaveBeenCalledOnce();
  await act(async () => textarea.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter", shiftKey: true })));
  expect(execute).toHaveBeenCalledOnce();

  await mount(composerController({
    action: { enabled: true, kind: "stop", label: "Stop" },
    executeMainAction: execute,
    phase: "active",
  }));
  const stopTextarea = document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')!;
  expect(document.querySelector(".chat-composer-guidance")?.textContent).toContain("Enter to stage");
  await act(async () => stopTextarea.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" })));
  expect(execute).toHaveBeenCalledOnce();
});

test("keeps the authoritative run status available without restoring the visible phase row", async () => {
  await mount(composerController({ latestTurnStatus: "completed", phase: "idle" }));

  const status = document.querySelector<HTMLElement>("[data-chat-status]");
  expect(status?.textContent).toBe("Run complete");
  expect(status?.classList.contains("visually-hidden")).toBe(true);
  expect(document.querySelector(".chat-composer-status-row")).toBeNull();
});

test("exposes a rejected command as a coded alert without clearing the composer", async () => {
  await mount(composerController({
    draft: "Retained input",
    error: "Agent at capacity. The Turn was not accepted and your input was restored.",
    errorCode: "AGENT_CAPACITY",
  }));

  const alert = document.querySelector<HTMLElement>('[role="alert"]');
  expect(alert?.getAttribute("data-failure-code")).toBe("AGENT_CAPACITY");
  expect(alert?.textContent).toContain("Agent at capacity");
  expect(document.querySelector<HTMLTextAreaElement>("textarea")?.value).toBe("Retained input");
});

test("shows FIFO controls and exposes Steer only on the active head item", async () => {
  const steer = vi.fn(async () => undefined);
  const head = staged("First staged input", 1);
  await mount(composerController({
    phase: "active",
    queue: [head, staged("Second staged input", 2)],
    steerStaged: steer,
  }));
  expect(document.querySelectorAll(".chat-staged-queue li")).toHaveLength(2);
  const steerButtons = [...document.querySelectorAll<HTMLButtonElement>(".chat-staged-actions button")]
    .filter((button) => button.textContent === "Steer");
  expect(steerButtons).toHaveLength(1);
  await act(async () => steerButtons[0]?.click());
  expect(steer).toHaveBeenCalledExactlyOnceWith(head);
});

async function mount(controller: ChatConversationController): Promise<void> {
  if (root !== undefined) await act(async () => root?.unmount());
  document.body.replaceChildren();
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root?.render(<ChatComposer announcement="" controller={controller} modelControls={<span>Model settings</span>} />);
  });
}

function composerController(overrides: Partial<ChatConversationController> = {}): ChatConversationController {
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
    statusAnnouncement: "Ready.",
    textareaRef: { current: null },
    timelineError: false,
    turns: [],
    ...overrides,
    errorCode: overrides.errorCode ?? null,
  };
}

function staged(content: string, sequence: number): StagedInput {
  return {
    content,
    createdAt: "2026-09-02T00:00:00.000Z",
    inputId: `00000000-0000-4000-8000-${sequence.toString().padStart(12, "0")}`,
    leaseOwner: null,
    leaseUntil: null,
    researcherId: "00000000-0000-4000-8000-000000000900",
    sequence,
    sessionId: "00000000-0000-4000-8000-000000000901",
    status: "staged",
  };
}
