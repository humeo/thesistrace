// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import { SessionHistoryList } from "./SessionHistoryList";
import type { SessionHistoryController } from "./useSessionHistory";
import { changeInterfaceLanguage } from "../i18n";
import { chatSessionHref } from "./chatNavigation";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

test("Chat scrolling preserves an open sidebar menu; scrolling its anchor dismisses it", async () => {
  const host = document.createElement("aside");
  const transcript = document.createElement("main");
  document.body.append(host, transcript);
  const root = createRoot(host);
  const session = { id: "00000000-0000-4000-8000-000000000001", title: "Research", version: "1",
    activity_at: "2026-09-13T00:00:00Z", created_at: "2026-09-13T00:00:00Z", current_turn: null, latest_turn: null };
  const controller: SessionHistoryController = {
    sessions: [session], status: "ready", error: null, nextCursor: null, loadingMore: false, refreshVersion: 0,
    deleteSession: vi.fn(), loadMore: vi.fn(), refresh: vi.fn(), renameSession: vi.fn(), watchGeneratedTitle: vi.fn(),
  };
  try {
    await act(async () => root.render(<SessionHistoryList controller={controller} currentSessionId={session.id}
      navigate={vi.fn()} navigationInteractive restoreFocus={vi.fn()} />));
    const trigger = host.querySelector<HTMLButtonElement>('button[aria-label="Actions for Research"]')!;
    await act(async () => trigger.click());
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
    await act(async () => transcript.dispatchEvent(new Event("scroll")));
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    await act(async () => host.dispatchEvent(new Event("scroll")));
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  } finally {
    await act(async () => root.unmount());
    host.remove(); transcript.remove();
  }
});

test("locale changes only the Untitled sentinel display and retains an open history menu", async () => {
  const host = document.createElement("aside");
  document.body.append(host);
  const root = createRoot(host);
  const sessions = ["Untitled", "未命名"].map((title, index) => ({
    id: `00000000-0000-4000-8000-00000000000${index + 1}`, title, version: "1",
    activity_at: "2026-09-13T00:00:00Z", created_at: "2026-09-13T00:00:00Z", current_turn: null, latest_turn: null,
  }));
  const controller: SessionHistoryController = {
    sessions, status: "ready", error: null, nextCursor: null, loadingMore: false, refreshVersion: 0,
    deleteSession: vi.fn(), loadMore: vi.fn(), refresh: vi.fn(), renameSession: vi.fn(), watchGeneratedTitle: vi.fn(),
  };
  try {
    await act(async () => root.render(<SessionHistoryList controller={controller} currentSessionId={null}
      navigate={vi.fn()} navigationInteractive restoreFocus={vi.fn()} />));
    expect(host.querySelector<HTMLAnchorElement>(`a[href="${chatSessionHref(sessions[0].id)}"]`)?.textContent).toBe("Untitled");
    const trigger = host.querySelector<HTMLButtonElement>(`button[aria-label="Actions for Untitled"]`)!;
    await act(async () => trigger.click());
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
    await act(async () => changeInterfaceLanguage("zh-CN"));
    expect(host.querySelector<HTMLAnchorElement>(`a[href="${chatSessionHref(sessions[0].id)}"]`)?.textContent).toBe("未命名");
    expect(host.querySelector<HTMLAnchorElement>(`a[href="${chatSessionHref(sessions[1].id)}"]`)?.textContent).toBe("未命名");
    expect(document.querySelector('[role="menu"]')?.getAttribute("aria-label")).toBe("未命名 的操作");
    expect(document.querySelector('[role="menu"] button:focus')?.textContent).toContain("重命名");
    await act(async () => changeInterfaceLanguage("en"));
    expect(host.querySelector<HTMLAnchorElement>(`a[href="${chatSessionHref(sessions[0].id)}"]`)?.textContent).toBe("Untitled");
    expect(host.querySelector<HTMLAnchorElement>(`a[href="${chatSessionHref(sessions[1].id)}"]`)?.textContent).toBe("未命名");
  } finally {
    await act(async () => changeInterfaceLanguage("en"));
    await act(async () => root.unmount());
    host.remove();
  }
});
