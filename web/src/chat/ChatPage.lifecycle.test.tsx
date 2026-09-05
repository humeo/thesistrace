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
  expect(document.querySelector("#chat-composer-guidance")?.textContent).toContain("Enter to stage");
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

test.each(["new", "active", "waiting_for_user"] as const)("keeps %s keyboard guidance accessible without a visible footer", async (phase) => {
  await mount(composerController({ phase, question: phase === "waiting_for_user" ? pendingQuestion : null }));
  const input = document.querySelector("textarea")!;
  const description = document.getElementById(input.getAttribute("aria-describedby")!);
  expect(description?.textContent).toContain("Shift+Enter for newline");
  expect(description?.classList.contains("visually-hidden")).toBe(true);
  expect(document.querySelector(".chat-composer-guidance")).toBeNull();
});

test("keeps answer size warnings visible after removing the guidance footer", async () => {
  await mount(composerController({ phase: "waiting_for_user", question: pendingQuestion, draftBytes: 16 * 1024 + 1 }));
  expect(document.querySelector(".chat-byte-count")?.closest(".visually-hidden")).toBeNull();
  expect(document.querySelector(".chat-byte-count")?.textContent).toContain("bytes");
  expect(document.querySelector(".chat-composer-validation")?.textContent).toContain("Input exceeds");
});

const pendingQuestion = {
  interrupt_id: "turn::question",
  options: [{ label: "Quality", description: "Lower turnover" }, { label: "Risk" }],
  question: "Which objective should lead?",
  selection_mode: "single_select" as const,
};

test.each(["single_select", "multi_select", "free_text"] as const)("keeps %s questions and custom input in the one composer surface", async (mode) => {
  const selections = vi.fn();
  await mount(composerController({
    action: { enabled: true, kind: "stop", label: "Stop" },
    phase: "waiting_for_user",
    question: { ...pendingQuestion, selection_mode: mode, options: mode === "free_text" ? null : pendingQuestion.options },
    setAnswerSelections: selections,
  }));
  expect(document.querySelector(".chat-question-composer h2")?.textContent).toBe(pendingQuestion.question);
  expect(document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Answer"]')?.disabled).toBe(false);
  expect(document.querySelector<HTMLButtonElement>('[aria-label="Send answer"]')?.disabled).toBe(true);
  expect(document.body.textContent).not.toContain("Model settings");
  if (mode !== "free_text") {
    await act(async () => document.querySelector<HTMLInputElement>('input[value="Quality"]')?.click());
    expect(selections).toHaveBeenCalledWith(["Quality"]);
  }
});

test("answers explicitly, keeps Stop independent, and never treats blank Enter as Stop", async () => {
  const execute = vi.fn(async () => undefined);
  const stop = vi.fn(async () => undefined);
  const controller = composerController({
    action: { enabled: true, kind: "stop", label: "Stop" },
    executeMainAction: execute, stopTurn: stop, phase: "waiting_for_user", question: pendingQuestion,
  });
  await mount(controller);
  const input = document.querySelector("textarea")!;
  await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" })));
  await act(async () => document.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(execute).not.toHaveBeenCalled();
  expect(stop).not.toHaveBeenCalled();
  await mount({ ...controller, action: { enabled: true, kind: "answer", label: "Send answer" }, draft: "Keep churn low", answerSelections: ["Quality"] });
  const answer = document.querySelector("textarea")!;
  await act(async () => answer.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter", isComposing: true })));
  expect(execute).not.toHaveBeenCalled();
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="Send answer"]')?.click());
  expect(execute).toHaveBeenCalledOnce();
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="Stop"]')?.click());
  expect(stop).toHaveBeenCalledOnce();
});

test.each(["opening", "recovering", "stopping"] as const)("retains but locks the question form during %s", async (phase) => {
  await mount(composerController({
    action: { enabled: false, kind: "stop", label: "Stop" },
    phase, question: pendingQuestion, draft: "Retained note", answerSelections: ["Quality"],
  }));
  expect(document.querySelector<HTMLTextAreaElement>("textarea")?.value).toBe("Retained note");
  expect(document.querySelector<HTMLTextAreaElement>("textarea")?.disabled).toBe(true);
  expect(document.querySelector<HTMLInputElement>('input[value="Quality"]')?.checked).toBe(true);
  expect(document.querySelector<HTMLFieldSetElement>("fieldset")?.disabled).toBe(true);
  expect(document.querySelector<HTMLButtonElement>('[aria-label="Stop"]')?.disabled).toBe(true);
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

test("does not offer to edit a staged prompt into a pending answer", async () => {
  await mount(composerController({
    phase: "waiting_for_user",
    question: pendingQuestion,
    queue: [staged("Research a different idea", 1)],
  }));
  expect(document.querySelector<HTMLButtonElement>('[aria-label="Edit staged input"]')?.disabled).toBe(true);
  expect(document.querySelector<HTMLButtonElement>('[aria-label="Delete staged input"]')?.disabled).toBe(false);
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
    stopTurn: vi.fn(async () => undefined),
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
