// @vitest-environment happy-dom

import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";

import type { AgentSessionSummary } from "../chat/sessionHistory";
import type { SessionHistoryController } from "../chat/useSessionHistory";
import { AppShell } from "./AppShell";

vi.mock("../auth/AccountMenu", () => ({
  AccountMenu: () => (
    <details>
      <summary aria-label="Account menu">Account</summary>
      <button type="button">Log out</button>
    </details>
  ),
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
const session: AgentSessionSummary = {
  activity_at: "2026-08-30T04:00:00.000000Z", created_at: "2026-08-29T04:00:00.000000Z",
  message_title: null,
  current_turn: null, latest_turn: null, title: "Quality Alpha",
  id: "00000000-0000-4000-8000-000000000001", version: "2026-08-30T04:00:00.000Z",
};
const history: SessionHistoryController = {
  deleteSession: vi.fn(), error: null, loadMore: vi.fn(), loadingMore: false,
  nextCursor: null, refresh: vi.fn(), refreshVersion: 0, renameSession: vi.fn(),
  sessions: [session], status: "ready", watchGeneratedTitle: vi.fn(),
};

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

function Routes() {
  const [href, navigate] = useState(`/chat?session=${session.id}`);
  const currentPath = href.split("?")[0]!;
  return (
      <AppShell currentPath={currentPath} currentSessionId={currentPath === "/chat" ? session.id : null}
        isNewChat={href === "/chat"} isOperator={false} navigate={navigate} sessionHistory={history}>
        <h1>{currentPath === "/chat" ? "Conversation" : "Data overview"}</h1>
      </AppShell>
  );
}

test("retains the same sidebar, history scroll, and collapsed state across Chat and Data", async () => {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root!.render(<Routes />));
  const sidebar = document.querySelector("#primary-navigation");
  const historyRegion = document.querySelector(".chat-session-region")!;
  historyRegion.scrollTop = 75;
  const dataLink = () => document.querySelector<HTMLAnchorElement>('.resource-nav a[href="/data"]')!;
  const conversationLink = () => document.querySelector<HTMLAnchorElement>(`.chat-session-row a`)!;

  expect(document.querySelector(".context-bar")).toBeNull();
  const collapse = document.querySelector<HTMLButtonElement>('[aria-label="Collapse sidebar"]')!;
  expect(collapse?.closest(".sidebar-brand-row")).not.toBeNull();
  expect(sidebar?.contains(collapse)).toBe(true);
  await act(async () => collapse.click());
  await act(async () => dataLink().click());

  expect(document.querySelector("h1")?.textContent).toBe("Data overview");
  expect(document.querySelector("#primary-navigation")).toBe(sidebar);
  expect(document.querySelector(".chat-session-region")).toBe(historyRegion);
  expect(historyRegion.scrollTop).toBe(75);
  expect(document.querySelector(".app-shell-collapsed")).not.toBeNull();
  expect(dataLink().getAttribute("aria-current")).toBe("page");
  expect(conversationLink().getAttribute("aria-current")).toBeNull();
  expect(document.querySelector(".context-bar")).toBeNull();

  await act(async () => conversationLink().click());
  expect(document.querySelector("h1")?.textContent).toBe("Conversation");
  expect(document.querySelector("#primary-navigation")).toBe(sidebar);
  expect(document.querySelector(".app-shell-collapsed")).not.toBeNull();
  expect(conversationLink().getAttribute("aria-current")).toBe("page");
  expect(dataLink().getAttribute("aria-current")).toBeNull();
  expect(document.querySelectorAll('[data-slot="sidebar"]')).toHaveLength(1);
  expect(document.querySelector(".context-bar")).toBeNull();
  const expand = document.querySelector<HTMLButtonElement>('[aria-label="Expand sidebar"]')!;
  expect(sidebar?.contains(expand)).toBe(true);
  await act(async () => expand.click());
  expect(document.querySelector(".app-shell-collapsed")).toBeNull();
});

test("brand opens the landing page through browser navigation", async () => {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root!.render(<Routes />));
  const home = document.querySelector<HTMLAnchorElement>('[aria-label="QAgentis home"]')!;
  expect(home.getAttribute("href")).toBe("/");
  const event = new MouseEvent("click", { bubbles: true, cancelable: true });
  await act(async () => home.dispatchEvent(event));
  expect(event.defaultPrevented).toBe(false);
  expect(document.querySelector("h1")?.textContent).toBe("Conversation");
});

test("leaves modified navigation clicks to the browser", async () => {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root!.render(<Routes />));
  const link = document.querySelector<HTMLAnchorElement>('.resource-nav a[href="/data"]')!;
  const event = new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true });
  await act(async () => link.dispatchEvent(event));
  expect(event.defaultPrevented).toBe(false);
  expect(document.querySelector("h1")?.textContent).toBe("Conversation");
});

test("does not add a sidebar keyboard shortcut or persist its collapse state", async () => {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root!.render(<Routes />));
  await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "b", metaKey: true, bubbles: true })));
  expect(document.querySelector(".app-shell-collapsed")).toBeNull();
  const collapse = document.querySelector<HTMLButtonElement>('[aria-label="Collapse sidebar"]')!;
  await act(async () => collapse.click());
  expect(document.querySelector(".app-shell-collapsed")).not.toBeNull();
  expect(document.cookie).not.toContain("sidebar_state=");
});
