// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentSessionUnavailableError, type AgentSessionSummary } from "./sessionHistory";
import { watchSelectedSession } from "./sessionSynchronization";

const threadId = "00000000-0000-4000-8000-000000009001";
const session: AgentSessionSummary = {
  active_run: false,
  activity_at: "2026-08-30T04:00:00.000000Z",
  created_at: "2026-08-30T04:00:00.000000Z",
  id: threadId,
  title: "Research comparison",
  version: "2026-08-30T04:00:00.000Z",
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-30T04:00:00.000Z"));
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("selected Chat synchronization", () => {
  it("attaches initially and on remote Run changes without issuing a Run request", async () => {
    let current = session;
    const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(current));
    vi.stubGlobal("fetch", fetch);
    const synchronize = vi.fn(async () => undefined);
    const controller = new AbortController();
    const observing = watchSelectedSession({
      isStreaming: () => false, signal: controller.signal, synchronize, threadId,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(synchronize).toHaveBeenCalledWith(session);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(synchronize).toHaveBeenCalledTimes(1);
    current = { ...session, active_run: true, activity_at: "2026-08-30T04:00:01.000000Z" };
    await vi.advanceTimersByTimeAsync(2_000);
    expect(synchronize).toHaveBeenLastCalledWith(current);
    current = { ...current, active_run: false };
    await vi.advanceTimersByTimeAsync(2_000);
    expect(synchronize).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls.every((call) => String(call[0]).endsWith(`/sessions/${threadId}`))).toBe(true);
    controller.abort();
    await observing;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not replace the local Run stream or consume a change while admission races a probe", async () => {
    let streaming = true;
    const fetch = vi.fn(async () => { streaming = true; return json(session); });
    vi.stubGlobal("fetch", fetch);
    const synchronize = vi.fn(async () => undefined);
    const controller = new AbortController();
    const observing = watchSelectedSession({
      isStreaming: () => streaming, signal: controller.signal, synchronize, threadId,
    });
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetch).not.toHaveBeenCalled();
    streaming = false;
    await vi.advanceTimersByTimeAsync(2_000);
    expect(synchronize).not.toHaveBeenCalled();

    fetch.mockImplementation(async () => json(session));
    streaming = false;
    await vi.advanceTimersByTimeAsync(2_000);
    expect(synchronize).toHaveBeenCalledExactlyOnceWith(session);
    controller.abort();
    await observing;
  });

  it("suspends hidden-page probes and refreshes when the page becomes visible", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const fetch = vi.fn(async () => json(session));
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    const synchronize = vi.fn(async () => undefined);
    const observing = watchSelectedSession({
      isStreaming: () => false, signal: controller.signal, synchronize, threadId,
    });
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetch).not.toHaveBeenCalled();
    visibility.mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
    expect(synchronize).toHaveBeenCalledExactlyOnceWith(session);
    controller.abort();
    await observing;
  });

  it("does not replace an accepted local stream with a stale probe error", async () => {
    let streaming = false;
    const fetch = vi.fn(async () => {
      streaming = true;
      throw new Error("The earlier metadata request failed");
    });
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    const synchronize = vi.fn(async () => undefined);
    let failed = false;
    const observing = watchSelectedSession({
      isStreaming: () => streaming, signal: controller.signal, synchronize, threadId,
    }).catch(() => { failed = true; });
    await vi.advanceTimersByTimeAsync(0);
    expect(failed).toBe(false);
    expect(synchronize).not.toHaveBeenCalled();
    controller.abort();
    await observing;
  });

  it("includes the complete metadata response body in the five-second deadline", async () => {
    let stream!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start: (controller) => { stream = controller; } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body)));
    let failure: unknown;
    const observing = watchSelectedSession({
      isStreaming: () => false, signal: new AbortController().signal, synchronize: vi.fn(), threadId,
    }).catch((error: unknown) => { failure = error; });
    try {
      await vi.advanceTimersByTimeAsync(5_000);
      expect(failure).toBeInstanceOf(AgentSessionUnavailableError);
    } finally {
      stream.error(new Error("Fixture stream closed"));
      await observing;
    }
  });

  it.each([404, 503])("stops on HTTP %s without retrying or exposing another Session", async (status) => {
    const fetch = vi.fn(async () => new Response("{}", { status }));
    vi.stubGlobal("fetch", fetch);
    const synchronize = vi.fn(async () => undefined);
    await expect(watchSelectedSession({
      isStreaming: () => false, signal: new AbortController().signal, synchronize, threadId,
    })).rejects.toBeInstanceOf(Error);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetch).toHaveBeenCalledOnce();
    expect(synchronize).not.toHaveBeenCalled();
  });

  it.each(["timeout", "navigation"])('bounds an in-flight metadata request on %s', async (reason) => {
    let aborted = false;
    vi.stubGlobal("fetch", vi.fn((_input: unknown, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => {
        aborted = true;
        reject(new DOMException("Aborted", "AbortError"));
      }, { once: true });
    })));
    const controller = new AbortController();
    const observing = watchSelectedSession({
      isStreaming: () => false, signal: controller.signal, synchronize: vi.fn(), threadId,
    });
    const failed = reason === "timeout"
      ? expect(observing).rejects.toBeInstanceOf(AgentSessionUnavailableError)
      : expect(observing).rejects.toMatchObject({ name: "AbortError" });
    if (reason === "timeout") await vi.advanceTimersByTimeAsync(5_000);
    else controller.abort();
    await failed;
    expect(aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});

function json(value: AgentSessionSummary): Response {
  return new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
}
