// @vitest-environment happy-dom

import type { ReactNode } from "react";
import { AppShell } from "../shell/AppShell";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test, vi } from "vitest";

import { AuthProvider } from "../auth/AuthProvider";
import { ChatTestProvider } from "./chatTestProvider";
import { ChatContent } from "./ChatPage";
import { chatSessionHref, readBrowserChatThread } from "./chatNavigation";
import { SessionHistoryList, sessionDialogErrorMessage } from "./SessionHistoryList";
import {
  AgentSessionInvalidError,
  AgentSessionTitleInvalidError,
  type AgentSessionSummary,
} from "./sessionHistory";

const researcherId = "00000000-0000-4000-8000-000000000900";
const catalogState = {
  status: "ready" as const,
  catalog: {
    default_model_key: "research-primary",
    models: [{
      default_reasoning_effort: "medium" as const,
      display_name: "Research Primary",
      key: "research-primary",
      reasoning_efforts: ["low", "medium", "high"] as const,
    }],
  },
};
const sessionHistory = {
  deleteSession: vi.fn(async () => undefined),
  error: null,
  loadMore: vi.fn(async () => undefined),
  loadingMore: false,
  nextCursor: null,
  refresh: vi.fn(),
  refreshVersion: 0,
  renameSession: vi.fn(async (session: AgentSessionSummary, title: string) => ({
    id: session.id,
    title,
    version: session.version,
  })),
  sessions: [] as readonly AgentSessionSummary[],
  status: "ready" as const,
  watchGeneratedTitle: vi.fn(),
};

test("renders Chat within the shared workspace hierarchy and integrated model picker", () => {
  const markup = renderToStaticMarkup(
    <TestWorkspace>
      <ChatContent
        catalogState={catalogState}
        navigateChat={vi.fn()}
        preferenceState={{ status: "not-required" }}
        researcherId={researcherId}
        reloadCatalog={vi.fn()}
        selectedSessionState={{ status: "not-required" }}
        sessionHistory={sessionHistory}
      />
    </TestWorkspace>,
  );

  const labels = ["Quantgrove", "New Chat", ">Data<", ">Research<", "Research Runs", "Daily Tracks"];
  const positions = labels.map((label) => markup.indexOf(label));
  expect(positions.every((position) => position >= 0)).toBe(true);
  expect(positions).toEqual([...positions].sort((left, right) => left - right));
  expect(markup).toContain('aria-label="Chats"');
  expect(markup).not.toContain(">Chats<");
  expect(markup).toMatch(/<textarea[^>]*disabled=""/);
  expect(markup).toContain('aria-label="Model Research Primary, reasoning Medium"');
  expect(markup).not.toContain("Next Turn settings");
  expect(markup).not.toContain('class="context-bar"');
  expect(markup).not.toContain("chat-model-context");
  expect(markup).not.toMatch(/temperature|top-p|endpoint|byok/i);
});

test.each([
  [{ selection_mode: "manual", model_key: "retired", reasoning_effort: "high" }, "Medium"],
  [{ selection_mode: "default", model_key: "research-primary", reasoning_effort: "high" }, "Medium"],
  [{ selection_mode: "manual", model_key: "research-primary", reasoning_effort: "high" }, "High"],
] as const)("initializes next-Turn settings from selection intent %#", (preference, effort) => {
  const markup = renderToStaticMarkup(<TestWorkspace><ChatContent
    catalogState={catalogState} navigateChat={vi.fn()}
    preferenceState={{ status: "ready", preference }} researcherId={researcherId}
    reloadCatalog={vi.fn()} selectedSessionState={{ status: "not-required" }} sessionHistory={sessionHistory}
  /></TestWorkspace>);
  expect(markup).toContain(`aria-label="Model Research Primary, reasoning ${effort}"`);
  expect(markup).not.toContain("Choose model</span>");
});

test("keeps loading and Not Found states in the chat canvas without a top bar", () => {
  const thread = { id: "00000000-0000-4000-8000-000000000111", kind: "session" as const };
  const common = {
    catalogState,
    navigateChat: vi.fn(),
    researcherId,
    reloadCatalog: vi.fn(),
    sessionHistory,
    thread,
  };
  const loading = renderToStaticMarkup(
    <TestWorkspace><ChatContent {...common} preferenceState={{ status: "loading" }} selectedSessionState={{ status: "loading" }} /></TestWorkspace>,
  );
  expect(loading).toContain('aria-busy="true"');
  expect(loading).toMatch(/<textarea[^>]*disabled=""/);
  expect(loading).not.toContain('class="context-bar"');
  expect(loading).not.toMatch(/<main[^>]*>\s*<header/);

  const missing = renderToStaticMarkup(
    <TestWorkspace><ChatContent {...common} preferenceState={{ status: "not-found" }} selectedSessionState={{ status: "not-found" }} /></TestWorkspace>,
  );
  expect(missing).toMatch(/<h1[^>]*>Chat not found<\/h1>/);
  expect(missing).not.toContain('class="context-bar"');
});

test("opening a history session never renders the New Chat landing screen", () => {
  const selected = session({ title: "Greeting" });
  const markup = renderToStaticMarkup(
    <ChatTestProvider><ChatContent
      catalogState={catalogState}
      navigateChat={vi.fn()}
      preferenceState={{ status: "loading" }}
      researcherId={researcherId}
      reloadCatalog={vi.fn()}
      selectedSessionState={{ status: "ready", session: selected }}
      sessionHistory={{ ...sessionHistory, sessions: [selected] }}
      thread={{ id: selected.id, kind: "session" }}
    /></ChatTestProvider>,
  );
  const canvas = document.createElement("div");
  canvas.innerHTML = markup;
  expect(canvas.querySelector(".chat-new-chat-start")).toBeNull();
  expect(canvas.querySelector("main > header")).toBeNull();
  expect(canvas.querySelector("main")?.getAttribute("aria-label")).toBe("Greeting");
});

test("keeps New Chat ephemeral until a canonical opaque session is present", () => {
  const generated = "00000000-0000-4000-8000-000000000111";
  expect(readBrowserChatThread("", () => generated)).toEqual({ id: generated, kind: "new" });
  expect(readBrowserChatThread("?session=prototype", () => generated)).toEqual({ id: null, kind: "invalid" });
  expect(readBrowserChatThread("?session=AA000000-0000-4000-8000-000000000222", () => generated)).toEqual({
    id: "aa000000-0000-4000-8000-000000000222",
    kind: "session",
  });
  expect(readBrowserChatThread(`?session=${generated}&session=00000000-0000-4000-8000-000000000222`, () => generated))
    .toEqual({ id: null, kind: "invalid" });
  expect(chatSessionHref(generated)).toBe(`/chat?session=${generated}`);
});

test.each([
  ["running", "chat-session-active-spinner"],
  ["waiting_for_user", "chat-session-waiting-icon"],
] as const)("renders the icon-only current Turn state %s in Chat history", (status, className) => {
  const currentTurn = turn(status);
  const markup = renderToStaticMarkup(
    <SessionHistoryList
      controller={{ ...sessionHistory, sessions: [session({ current_turn: currentTurn, latest_turn: currentTurn })] }}
      currentSessionId={null}
      navigate={vi.fn()}
      navigationInteractive
      restoreFocus={vi.fn()}
      onDecision={vi.fn()}
    />,
  );
  expect(markup).toContain(`class="${className}"`);
  expect(markup).not.toMatch(/chat-session-run-(?:full|compact)/);
});

test("keeps rename validation copy distinct from malformed server responses", () => {
  expect(sessionDialogErrorMessage("rename", new AgentSessionTitleInvalidError())).toBe(
    "Choose a title between 1 and 80 characters other than Untitled.",
  );
  expect(sessionDialogErrorMessage("rename", new AgentSessionInvalidError())).toBe(
    "The Chat title response was invalid.",
  );
});

function session(overrides: Partial<AgentSessionSummary> = {}): AgentSessionSummary {
  return {
    activity_at: "2026-08-30T04:00:00.000000Z",
    created_at: "2026-08-29T04:00:00.000000Z",
    current_turn: null,
    id: "00000000-0000-4000-8000-000000000001",
    latest_turn: null,
    title: "Quality Alpha",
    version: "2026-08-30T04:00:00.000Z",
    ...overrides,
  };
}

function turn(status: "running" | "waiting_for_user"): NonNullable<AgentSessionSummary["current_turn"]> {
  return {
    id: "00000000-0000-4000-8000-000000000010",
    kind: "prompt",
    model_key: "research-primary",
    question: status === "waiting_for_user" ? {
      interrupt_id: "00000000-0000-4000-8000-000000000010::ask-1",
      options: null,
      question: "Which universe should be used?",
      selection_mode: "free_text",
    } : null,
    reasoning_effort: "medium",
    started_at: "2026-08-30T04:00:00.000000Z",
    status,
    terminal_error_code: null,
  };
}

function TestWorkspace({ children }: { children: ReactNode }) {
  return (
    <ChatTestProvider><AuthProvider>
      <AppShell currentPath="/chat" currentSessionId={null} isNewChat isOperator={false}
        navigate={vi.fn()} sessionHistory={sessionHistory}>
        {children}
      </AppShell>
    </AuthProvider></ChatTestProvider>
  );
}
