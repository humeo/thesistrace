// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import { SessionHistoryList } from "./SessionHistoryList";
import type { SessionHistoryController } from "./useSessionHistory";

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
