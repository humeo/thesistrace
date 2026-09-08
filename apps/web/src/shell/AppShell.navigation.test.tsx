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
  const dataLink = document.querySelector<HTMLAnchorElement>('.resource-nav a[href="/data"]')!;
  const conversationLink = document.querySelector<HTMLAnchorElement>(`.chat-session-row a`)!;

  expect(document.querySelector(".context-bar")).toBeNull();
  const collapse = document.querySelector<HTMLButtonElement>('[aria-label="Collapse sidebar"]')!;
  expect(collapse?.closest(".sidebar-brand-row")).not.toBeNull();
  expect(sidebar?.contains(collapse)).toBe(true);
  await act(async () => collapse.click());
  await act(async () => dataLink.click());

  expect(document.querySelector("h1")?.textContent).toBe("Data overview");
  expect(document.querySelector("#primary-navigation")).toBe(sidebar);
  expect(document.querySelector(".chat-session-region")).toBe(historyRegion);
  expect(historyRegion.scrollTop).toBe(75);
  expect(document.querySelector(".app-shell-collapsed")).not.toBeNull();
  expect(dataLink.getAttribute("aria-current")).toBe("page");
  expect(conversationLink.getAttribute("aria-current")).toBeNull();
  expect(document.querySelector(".context-bar")).toBeNull();

  await act(async () => conversationLink.click());
  expect(document.querySelector("h1")?.textContent).toBe("Conversation");
  expect(document.querySelector("#primary-navigation")).toBe(sidebar);
  expect(document.querySelector(".app-shell-collapsed")).not.toBeNull();
  expect(conversationLink.getAttribute("aria-current")).toBe("page");
  expect(dataLink.getAttribute("aria-current")).toBeNull();
  expect(document.querySelectorAll("aside")).toHaveLength(1);
  expect(document.querySelector(".context-bar")).toBeNull();
  const expand = document.querySelector<HTMLButtonElement>('[aria-label="Expand sidebar"]')!;
  expect(sidebar?.contains(expand)).toBe(true);
  await act(async () => expand.click());
  expect(document.querySelector(".app-shell-collapsed")).toBeNull();
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

test("mobile focus wraps through the account trigger, excluding closed menu controls", async () => {
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true, media: "(max-width: 768px)", onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  });
  // Chromium reports layout boxes even for controls inside closed details.
  vi.spyOn(Element.prototype, "getClientRects").mockReturnValue(
    [new DOMRect(0, 0, 44, 44)] as unknown as DOMRectList,
  );
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root!.render(<Routes />));
  const open = document.querySelector<HTMLButtonElement>('[aria-label="Open navigation"]')!;
  expect(open).not.toBeNull();
  expect(open.closest(".context-bar")).toBeNull();
  await act(async () => open.click());
  const home = document.querySelector<HTMLAnchorElement>('[aria-label="QuantTrace home"]')!;
  const account = document.querySelector<HTMLElement>('[aria-label="Account menu"]')!;
  await act(async () => {
    home.focus();
    home.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }));
  });
  expect(document.activeElement).toBe(account);
  await act(async () => account.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })));
  expect(document.activeElement).toBe(home);

  const dataLink = document.querySelector<HTMLAnchorElement>('.resource-nav a[href="/data"]')!;
  await act(async () => dataLink.click());
  expect(document.querySelector("h1")?.textContent).toBe("Data overview");
  expect(document.querySelector(".context-bar")).toBeNull();
  expect(open.getAttribute("aria-expanded")).toBe("false");
  expect(document.querySelector("#primary-navigation")?.hasAttribute("inert")).toBe(true);
  await act(async () => open.click());
  expect(open.getAttribute("aria-expanded")).toBe("true");
  const close = document.querySelector<HTMLButtonElement>(".mobile-navigation-close")!;
  expect(document.activeElement).toBe(close);
  await act(async () => close.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })));
  expect(open.getAttribute("aria-expanded")).toBe("false");
});
