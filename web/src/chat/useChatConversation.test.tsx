// @vitest-environment happy-dom

import type { AgentSubscriber, HttpAgent } from "@ag-ui/client";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";

vi.mock("./sessionHistory", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./sessionHistory")>();
  return { ...actual, loadAgentSession: vi.fn() };
});

vi.mock("./chatProtocol", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./chatProtocol")>();
  return { ...actual, loadCommandReceipt: vi.fn(), loadTimelinePage: vi.fn() };
});

import { ChatApiError, loadCommandReceipt, loadTimelinePage, type TimelineTurn } from "./chatProtocol";
import { loadAgentSession, type AgentSessionSummary } from "./sessionHistory";
import { StagedInputStore, StagedInputStoreError, type StagedInput } from "./stagedInputStore";
import {
  mergeLatestTurns,
  prependOlderTurns,
  useChatConversation,
  type ChatConversationController,
} from "./useChatConversation";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const researcherId = "00000000-0000-4000-8000-000000000900";
const threadId = "00000000-0000-4000-8000-000000000901";
const turnId = "00000000-0000-4000-8000-000000000902";
let root: Root | undefined;
let latestController: ChatConversationController | undefined;

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  latestController = undefined;
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

test("merges polling updates by whole Turn and keeps previously loaded history", () => {
  const older = timelineTurn("00000000-0000-4000-8000-000000000910", "older");
  const changing = timelineTurn("00000000-0000-4000-8000-000000000911", "streaming");
  const replacement = timelineTurn(changing.id, "complete");
  const newest = timelineTurn("00000000-0000-4000-8000-000000000912", "newest");

  expect(mergeLatestTurns([older, changing], [replacement, newest])).toEqual([
    older,
    replacement,
    newest,
  ]);
  expect(prependOlderTurns([replacement, newest], [older, replacement])).toEqual([
    older,
    replacement,
    newest,
  ]);
});

test("retries a failed older page without mistaking it for a latest-page refresh", async () => {
  const newest = timelineTurn("00000000-0000-4000-8000-000000000911", "newest");
  const older = timelineTurn("00000000-0000-4000-8000-000000000910", "older");
  vi.mocked(loadAgentSession).mockResolvedValue(session);
  vi.mocked(loadTimelinePage)
    .mockResolvedValueOnce({ next_cursor: "older-cursor", turns: [newest] })
    .mockRejectedValueOnce(new TypeError("older page unavailable"))
    .mockResolvedValueOnce({ next_cursor: null, turns: [older] });
  vi.spyOn(StagedInputStore.prototype, "list").mockResolvedValue([]);

  await mountConversation({
    agent: { runAgent: vi.fn(), setMessages: vi.fn() } as unknown as HttpAgent,
    existingSession: true,
  });
  await vi.waitFor(() => expect(latestController?.nextCursor).toBe("older-cursor"));
  await act(async () => latestController?.loadOlder());
  expect(latestController?.timelineError).toBe(true);

  await act(async () => latestController?.retryTimeline());

  expect(loadTimelinePage).toHaveBeenNthCalledWith(2, threadId, "older-cursor");
  expect(loadTimelinePage).toHaveBeenNthCalledWith(3, threadId, "older-cursor");
  expect(latestController?.turns.map((candidate) => candidate.id)).toEqual([older.id, newest.id]);
  expect(latestController?.timelineError).toBe(false);
});

test("keeps corrupt staged storage fail-closed without restarting the session controller", async () => {
  vi.mocked(loadAgentSession).mockResolvedValue(session);
  vi.mocked(loadTimelinePage).mockResolvedValue({ next_cursor: null, turns: [] });
  const list = vi.spyOn(StagedInputStore.prototype, "list")
    .mockRejectedValue(new StagedInputStoreError("STAGE_STORAGE_CORRUPT"));

  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root?.render(<ConversationHarness />);
  });
  await vi.waitFor(() => {
    expect(container.textContent).toContain("Staged inputs could not be read.");
  });

  // A corrupt read changes the queue lock, but must not restart the controller
  // effect and issue another opening request for the same Chat.
  expect(loadAgentSession).toHaveBeenCalledTimes(1);

  list.mockResolvedValue([]);
  await act(async () => latestController?.retryRecovery());
  expect(latestController?.queueLocked).toBe(false);
  expect(latestController?.error).toBeNull();
});

test("serializes Stage writes and preserves a draft changed while IndexedDB is pending", async () => {
  vi.mocked(loadAgentSession).mockResolvedValue(session);
  vi.mocked(loadTimelinePage).mockResolvedValue({ next_cursor: null, turns: [] });
  vi.spyOn(StagedInputStore.prototype, "list").mockResolvedValue([]);
  let resolveStage!: (item: StagedInput) => void;
  const pendingStage = new Promise<StagedInput>((resolve) => { resolveStage = resolve; });
  const stage = vi.spyOn(StagedInputStore.prototype, "stage").mockReturnValue(pendingStage);

  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root?.render(<ConversationHarness />);
  });
  await vi.waitFor(() => expect(latestController?.phase).toBe("active"));
  await act(async () => latestController?.setDraft("First staged input"));
  await vi.waitFor(() => expect(latestController?.action).toMatchObject({ enabled: true, kind: "stage" }));

  const executeFromAcceptedRender = latestController!.executeMainAction;
  let firstWrite!: Promise<void>;
  act(() => {
    firstWrite = executeFromAcceptedRender();
    void executeFromAcceptedRender();
  });
  expect(stage).toHaveBeenCalledTimes(1);
  await vi.waitFor(() => expect(latestController?.action).toMatchObject({ enabled: false, kind: "stage" }));
  await act(async () => latestController?.setDraft("Draft typed during the write"));

  resolveStage(stagedInput("First staged input"));
  await act(async () => firstWrite);

  expect(stage).toHaveBeenCalledWith(researcherId, threadId, "First staged input");
  expect(latestController?.draft).toBe("Draft typed during the write");
  expect(latestController?.action).toMatchObject({ enabled: true, kind: "stage" });
});

test("retains a Prompt draft until authoritative acceptance", async () => {
  vi.mocked(loadAgentSession).mockResolvedValue(session);
  vi.mocked(loadTimelinePage).mockResolvedValue({ next_cursor: null, turns: [] });
  vi.mocked(loadCommandReceipt).mockImplementation(async (_sessionId, commandId) => ({
    command_id: commandId,
    error_code: null,
    kind: "prompt",
    status: "accepted",
    turn_id: turnId,
  }));
  vi.spyOn(StagedInputStore.prototype, "list").mockResolvedValue([]);
  let completeRun!: () => void;
  const run = new Promise<void>((resolve) => { completeRun = resolve; });
  const runAgent = vi.fn(() => run);

  await mountConversation({
    agent: { runAgent, setMessages: vi.fn() } as unknown as HttpAgent,
    existingSession: false,
  });
  await vi.waitFor(() => expect(latestController?.phase).toBe("new"));
  await act(async () => latestController?.setDraft("A new research prompt"));
  await vi.waitFor(() => expect(latestController?.action).toMatchObject({ enabled: true, kind: "send" }));

  let execution!: Promise<void>;
  act(() => { execution = latestController!.executeMainAction(); });
  await vi.waitFor(() => expect(latestController?.phase).toBe("opening"));
  expect(latestController?.draft).toBe("A new research prompt");

  completeRun();
  await act(async () => execution);
  await vi.waitFor(() => expect(latestController?.draft).toBe(""));
});

test("refreshes Session history when the current Turn becomes terminal", async () => {
  const onSessionChanged = vi.fn();
  vi.mocked(loadAgentSession).mockResolvedValue({
    ...session,
    current_turn: null,
    latest_turn: { ...turn, status: "completed" },
    version: "2026-09-02T00:01:00.000000Z",
  });
  vi.mocked(loadTimelinePage).mockResolvedValue({ next_cursor: null, turns: [] });
  vi.spyOn(StagedInputStore.prototype, "list").mockResolvedValue([]);

  await mountConversation({
    agent: { runAgent: vi.fn(), setMessages: vi.fn() } as unknown as HttpAgent,
    existingSession: true,
    onSessionChanged,
  });

  await vi.waitFor(() => expect(latestController?.phase).toBe("idle"));
  expect(onSessionChanged).toHaveBeenCalledTimes(1);
});

test("commits the final Turn projection before exposing a terminal Session", async () => {
  const partialTurn = timelineTurn(turnId, "Partial answer");
  const finalTurn = timelineTurn(turnId, "Complete answer");
  const terminalSession: AgentSessionSummary = {
    ...session,
    current_turn: null,
    latest_turn: { ...turn, status: "completed" },
    version: "2026-09-02T00:01:00.000000Z",
  };
  let resolveFinalTimeline!: (page: { next_cursor: null; turns: TimelineTurn[] }) => void;
  const finalTimeline = new Promise<{ next_cursor: null; turns: TimelineTurn[] }>((resolve) => {
    resolveFinalTimeline = resolve;
  });
  vi.mocked(loadAgentSession)
    .mockResolvedValueOnce(session)
    .mockResolvedValue(terminalSession);
  vi.mocked(loadTimelinePage)
    .mockResolvedValueOnce({ next_cursor: null, turns: [partialTurn] })
    .mockReturnValueOnce(finalTimeline)
    .mockResolvedValue({ next_cursor: null, turns: [finalTurn] });
  vi.spyOn(StagedInputStore.prototype, "list").mockResolvedValue([]);

  await mountConversation({
    agent: { runAgent: vi.fn(), setMessages: vi.fn() } as unknown as HttpAgent,
    existingSession: true,
  });
  await vi.waitFor(() => expect(latestController?.turns).toEqual([partialTurn]));
  let refresh!: Promise<void>;
  act(() => { refresh = latestController!.refresh(); });
  await vi.waitFor(() => expect(loadTimelinePage).toHaveBeenCalledTimes(2));

  expect(latestController?.phase).toBe("active");
  expect(latestController?.turns).toEqual([partialTurn]);

  await act(async () => {
    resolveFinalTimeline({ next_cursor: null, turns: [finalTurn] });
    await refresh;
  });
  expect(latestController?.phase).toBe("idle");
  expect(latestController?.turns).toEqual([finalTurn]);
});

test("keeps an input and surfaces a known failure rejected before acceptance", async () => {
  vi.mocked(loadTimelinePage).mockResolvedValue({ next_cursor: null, turns: [] });
  vi.spyOn(StagedInputStore.prototype, "list").mockResolvedValue([]);
  const runAgent = vi.fn(async (_input, subscriber?: AgentSubscriber) => {
    await subscriber?.onRunErrorEvent?.({
      event: {
        code: "AGENT_CAPACITY",
        message: "At capacity",
        type: "RUN_ERROR",
      },
    } as never);
  });

  await mountConversation({
    agent: { runAgent, setMessages: vi.fn() } as unknown as HttpAgent,
    existingSession: false,
  });
  await act(async () => latestController?.setDraft("Retain this input"));
  await vi.waitFor(() => expect(latestController?.action).toMatchObject({
    enabled: true,
    kind: "send",
  }));
  await act(async () => latestController?.executeMainAction());

  expect(latestController?.phase).toBe("new");
  expect(latestController?.draft).toBe("Retain this input");
  expect(latestController?.errorCode).toBe("AGENT_CAPACITY");
  expect(latestController?.error).toContain("Agent at capacity");
  expect(loadCommandReceipt).not.toHaveBeenCalled();
});

test("refreshes Session history when a Prompt finds that its Chat was deleted", async () => {
  const onSessionChanged = vi.fn();
  const idleSession: AgentSessionSummary = {
    ...session,
    current_turn: null,
    latest_turn: { ...turn, status: "completed" },
  };
  vi.mocked(loadAgentSession).mockResolvedValue(idleSession);
  vi.mocked(loadTimelinePage).mockResolvedValue({ next_cursor: null, turns: [] });
  vi.spyOn(StagedInputStore.prototype, "list").mockResolvedValue([]);
  const runAgent = vi.fn(async (_input, subscriber?: AgentSubscriber) => {
    await subscriber?.onRunErrorEvent?.({
      event: {
        code: "CHAT_SESSION_NOT_FOUND",
        message: "Chat not found",
        type: "RUN_ERROR",
      },
    } as never);
  });

  await mountConversation({
    agent: { runAgent, setMessages: vi.fn() } as unknown as HttpAgent,
    existingSession: true,
    initialSession: idleSession,
    onSessionChanged,
  });
  await vi.waitFor(() => expect(latestController?.phase).toBe("idle"));
  await act(async () => latestController?.setDraft("Refresh this deleted Chat"));
  await act(async () => latestController?.executeMainAction());

  expect(latestController?.draft).toBe("Refresh this deleted Chat");
  expect(latestController?.errorCode).toBe("CHAT_SESSION_NOT_FOUND");
  expect(onSessionChanged).toHaveBeenCalledTimes(1);
});

test("treats a missing receipt as rejection when the user explicitly retries recovery", async () => {
  vi.mocked(loadTimelinePage).mockResolvedValue({ next_cursor: null, turns: [] });
  vi.mocked(loadCommandReceipt)
    .mockRejectedValueOnce(new TypeError("connection lost"))
    .mockRejectedValueOnce(new ChatApiError("CHAT_COMMAND_NOT_FOUND", 404));
  vi.spyOn(StagedInputStore.prototype, "list").mockResolvedValue([]);
  const runAgent = vi.fn(async () => { throw new TypeError("connection lost"); });

  await mountConversation({
    agent: { runAgent, setMessages: vi.fn() } as unknown as HttpAgent,
    existingSession: false,
  });
  await act(async () => latestController?.setDraft("Recover this prompt"));
  await vi.waitFor(() => expect(latestController?.action).toMatchObject({ enabled: true, kind: "send" }));
  await act(async () => latestController?.executeMainAction());
  expect(latestController?.phase).toBe("recovering");
  expect(latestController?.draft).toBe("Recover this prompt");

  await act(async () => latestController?.retryRecovery());
  expect(latestController?.phase).toBe("new");
  expect(latestController?.draft).toBe("Recover this prompt");
  expect(latestController?.error).toContain("input was restored");
});

async function mountConversation(options: Readonly<{
  agent: HttpAgent;
  existingSession: boolean;
  initialSession?: AgentSessionSummary;
  onSessionChanged?: () => void;
}>): Promise<void> {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(<ConversationHarness {...options} />));
}

function ConversationHarness({
  agent = { runAgent: vi.fn(), setMessages: vi.fn() } as unknown as HttpAgent,
  existingSession = true,
  initialSession,
  onSessionChanged = vi.fn(),
}: Readonly<{
  agent?: HttpAgent;
  existingSession?: boolean;
  initialSession?: AgentSessionSummary;
  onSessionChanged?: () => void;
}>) {
  const controller = useChatConversation({
    agent,
    existingSession,
    initialSession: existingSession ? initialSession ?? session : undefined,
    onAccepted: vi.fn(),
    onSessionChanged,
    onTitleMaySettle: vi.fn(),
    researcherId,
    selection: {
      model: {
        default_reasoning_effort: "medium",
        display_name: "Scripted Research",
        key: "scripted-research",
        reasoning_efforts: ["medium"],
      },
      reasoningEffort: "medium",
    },
    threadId,
    titleMaySettle: false,
  });
  latestController = controller;
  return <output>{controller.error}</output>;
}

function stagedInput(content: string): StagedInput {
  return {
    content,
    createdAt: "2026-09-02T00:00:00.000Z",
    inputId: "00000000-0000-4000-8000-000000000903",
    leaseOwner: null,
    leaseUntil: null,
    researcherId,
    sequence: 1,
    sessionId: threadId,
    status: "staged",
  };
}

function timelineTurn(id: string, content: string): TimelineTurn {
  return {
    completed_at: "2026-09-02T00:01:00.000000Z",
    entries: [{
      created_at: "2026-09-02T00:00:01.000000Z",
      entry_id: `assistant:${content}`,
      kind: "assistant_message",
      payload: { content, status: "complete" },
      turn_id: id,
    }],
    id,
    started_at: "2026-09-02T00:00:00.000000Z",
    status: "completed",
  };
}

const turn = {
  id: turnId,
  kind: "prompt" as const,
  model_key: "scripted-research",
  question: null,
  reasoning_effort: "medium",
  started_at: "2026-09-02T00:00:00.000000Z",
  status: "running" as const,
  terminal_error_code: null,
};

const session: AgentSessionSummary = {
  activity_at: "2026-09-02T00:00:00.000000Z",
  created_at: "2026-09-02T00:00:00.000000Z",
  current_turn: turn,
  id: threadId,
  latest_turn: turn,
  title: "Research Alpha idea",
  version: "2026-09-02T00:00:00.000000Z",
};
