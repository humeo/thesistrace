// @vitest-environment happy-dom

import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  useSessionHistory,
  type SessionHistoryController,
} from "./useSessionHistory";

type PendingRequest = Readonly<{
  input: string;
  resolve: (response: Response) => void;
  signal: AbortSignal;
}>;

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe("Session history Hook lifecycle", () => {
  it("aborts its real first-page, load-more, and title requests when unmounted", async () => {
    const requests = installPendingFetch();
    let controller: SessionHistoryController | null = null;
    const receiveController = (value: SessionHistoryController) => {
      controller = value;
    };

    const firstMount = await mountProbe(receiveController);
    expect(requests).toHaveLength(1);
    const firstPageSignal = requests[0]!.signal;
    await unmountProbe(firstMount);
    expect(firstPageSignal.aborted).toBe(true);

    requests.length = 0;
    const activeMount = await mountProbe(receiveController);
    expect(requests).toHaveLength(1);
    await act(async () => {
      requests[0]!.resolve(jsonResponse(sessionPage()));
      await flushMicrotasks();
    });
    expect(controller).toMatchObject({
      nextCursor: "opaque_cursor",
      status: "ready",
    });

    act(() => {
      void controller!.loadMore();
      controller!.watchGeneratedTitle("00000000-0000-4000-8000-00000000001e");
    });
    expect(requests).toHaveLength(3);
    expect(requests[1]!.input).toContain("cursor=opaque_cursor");
    expect(requests[2]!.input).toContain("00000000-0000-4000-8000-00000000001e");
    const loadMoreSignal = requests[1]!.signal;
    const titleSignal = requests[2]!.signal;

    await unmountProbe(activeMount);

    expect(loadMoreSignal.aborted).toBe(true);
    expect(titleSignal.aborted).toBe(true);
  });
});

function HistoryProbe({
  receive,
}: {
  receive: (controller: SessionHistoryController) => void;
}) {
  const controller = useSessionHistory("researcher-a");
  useEffect(() => receive(controller), [controller, receive]);
  return null;
}

async function mountProbe(
  receive: (controller: SessionHistoryController) => void,
): Promise<Root> {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<HistoryProbe receive={receive} />);
    await flushMicrotasks();
  });
  return root;
}

async function unmountProbe(root: Root): Promise<void> {
  await act(async () => {
    root.unmount();
    await flushMicrotasks();
  });
}

function installPendingFetch(): PendingRequest[] {
  const requests: PendingRequest[] = [];
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const signal = init?.signal;
    if (!(signal instanceof AbortSignal)) {
      return Promise.reject(new Error("Session history request had no AbortSignal"));
    }
    return new Promise<Response>((resolve, reject) => {
      let settled = false;
      const abort = () => {
        if (settled) return;
        settled = true;
        reject(new DOMException("Request aborted", "AbortError"));
      };
      signal.addEventListener("abort", abort, { once: true });
      requests.push({
        input: String(input),
        resolve: (response) => {
          if (settled) return;
          settled = true;
          signal.removeEventListener("abort", abort);
          resolve(response);
        },
        signal,
      });
    });
  }));
  return requests;
}

function sessionPage() {
  return {
    next_cursor: "opaque_cursor",
    sessions: Array.from({ length: 30 }, (_, index) => ({
      active_run: false,
      activity_at: "2026-08-30T04:00:00.000000Z",
      created_at: "2026-08-29T04:00:00.000000Z",
      id: `00000000-0000-4000-8000-${(30 - index).toString(16).padStart(12, "0")}`,
      title: `Session ${index}`,
      version: "2026-08-30T04:00:00.000Z",
    })),
  };
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}
