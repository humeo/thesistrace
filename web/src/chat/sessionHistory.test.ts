import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AgentSessionActiveRunError,
  AgentSessionChangedError,
  AgentSessionInvalidError,
  AgentSessionTitleInvalidError,
  appendAgentSessionPage,
  decodeAgentSessionPage,
  deleteAgentSession,
  groupSessionsByRecency,
  loadAgentSession,
  renameAgentSession,
  watchGeneratedSessionTitle,
  type AgentSessionSummary,
} from "./sessionHistory";
import {
  sessionHistoryReducer,
  type SessionHistoryState,
} from "./useSessionHistory";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Agent Chat Session history", () => {
  it("decodes one exact bounded page in stable activity and ID order", () => {
    const sessions = Array.from({ length: 30 }, (_, index) => session({
      id: `00000000-0000-4000-8000-${(30 - index).toString(16).padStart(12, "0")}`,
      title: `Session ${index}`,
    }));
    const decoded = decodeAgentSessionPage({
      next_cursor: "eyJhIjoiY3Vyc29yIn0",
      sessions,
    });

    expect(decoded.sessions).toHaveLength(30);
    expect(decoded.sessions[0]?.id).toBe("00000000-0000-4000-8000-00000000001e");
    expect(decoded.next_cursor).toBe("eyJhIjoiY3Vyc29yIn0");
  });

  it.each([
    { next_cursor: "cursor", sessions: [] },
    { next_cursor: null, sessions: [session(), { ...session(), title: "Duplicate" }] },
    {
      next_cursor: null,
      sessions: [
        session({ id: "00000000-0000-4000-8000-000000000001" }),
        session({ id: "00000000-0000-4000-8000-000000000002" }),
      ],
    },
    { next_cursor: null, sessions: [session({ title: "\u200B" })] },
    { extra: true, next_cursor: null, sessions: [] },
  ])("rejects an unbounded, duplicate, unstable, or expanded page", (value) => {
    expect(() => decodeAgentSessionPage(value)).toThrow(AgentSessionInvalidError);
  });

  it("groups local calendar boundaries without reordering Sessions", () => {
    const now = new Date(2026, 7, 30, 12, 0, 0);
    const sessions = [
      session({ activity_at: databaseInstant(new Date(2026, 7, 30, 0, 0, 0)), title: "Today" }),
      session({
        activity_at: databaseInstant(new Date(2026, 7, 29, 23, 59, 59)),
        id: "00000000-0000-4000-8000-000000000002",
        title: "Yesterday",
      }),
      session({
        activity_at: databaseInstant(new Date(2026, 7, 23, 0, 0, 0)),
        id: "00000000-0000-4000-8000-000000000003",
        title: "Seven days",
      }),
      session({
        activity_at: databaseInstant(new Date(2026, 7, 22, 23, 59, 59)),
        id: "00000000-0000-4000-8000-000000000004",
        title: "Older",
      }),
    ];

    expect(groupSessionsByRecency(sessions, now).map((group) => ({
      label: group.label,
      titles: group.sessions.map((candidate) => candidate.title),
    }))).toEqual([
      { label: "Today", titles: ["Today"] },
      { label: "Previous 7 days", titles: ["Yesterday", "Seven days"] },
      { label: "Older", titles: ["Older"] },
    ]);
  });

  it("appends only a strict continuation across a page boundary", () => {
    const existing = [session({
      activity_at: "2026-08-30T04:00:00.000003Z",
      id: "00000000-0000-4000-8000-000000000003",
    })];
    const continuation = session({
      activity_at: "2026-08-30T04:00:00.000002Z",
      id: "00000000-0000-4000-8000-000000000002",
    });
    expect(appendAgentSessionPage(existing, {
      next_cursor: null,
      sessions: [continuation],
    })).toEqual([...existing, continuation]);

    expect(() => appendAgentSessionPage(existing, {
      next_cursor: null,
      sessions: [existing[0]!],
    })).toThrow(AgentSessionInvalidError);
    expect(() => appendAgentSessionPage(existing, {
      next_cursor: null,
      sessions: [session({
        activity_at: "2026-08-30T04:00:01.000000Z",
        id: "00000000-0000-4000-8000-000000000004",
      })],
    })).toThrow(AgentSessionInvalidError);
  });

  it("loads one direct Session with same-origin credentials", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(session()), {
      headers: { "content-type": "application/json" },
      status: 200,
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadAgentSession(session().id)).resolves.toEqual(session());
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/agent/sessions/${session().id}`,
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("applies the authoritative title when the independent operation settles", async () => {
    let elapsedMs = 0;
    let settled: AgentSessionSummary | null = null;

    await expect(watchGeneratedSessionTitle({
      load: async () => elapsedMs === 0
        ? session()
        : session({
            title: "Low-volatility quality",
            version: "2026-08-30T04:00:01.000Z",
          }),
      onSettled: (value) => {
        settled = value;
      },
      signal: new AbortController().signal,
      threadId: session().id,
      wait: async (delayMs) => {
        elapsedMs += delayMs;
      },
    })).resolves.toBe("settled");

    expect(settled).toMatchObject({ title: "Low-volatility quality" });
  });

  it("observes a legal title stored after generation and lock waiting", async () => {
    let elapsedMs = 0;
    let visibleTitle = "Untitled";

    await expect(watchGeneratedSessionTitle({
      load: async () => session({ title: elapsedMs >= 16_000 ? "Late quality title" : "Untitled" }),
      onSettled: (value) => {
        visibleTitle = value.title;
      },
      signal: new AbortController().signal,
      threadId: session().id,
      timeoutMs: 18_000,
      wait: async (delayMs) => {
        elapsedMs += delayMs;
      },
    })).resolves.toBe("settled");

    expect(visibleTitle).toBe("Late quality title");
  });

  it("ends at its wall-clock deadline even when a request never resolves", async () => {
    vi.useFakeTimers();
    const observation = watchGeneratedSessionTitle({
      load: async () => new Promise<AgentSessionSummary>(() => undefined),
      onSettled: () => undefined,
      signal: new AbortController().signal,
      threadId: session().id,
      timeoutMs: 50,
    });

    await vi.advanceTimersByTimeAsync(50);
    await expect(observation).resolves.toBe("unchanged");
  });

  it("bounds the authoritative history refresh within the same deadline", async () => {
    vi.useFakeTimers();
    const observation = watchGeneratedSessionTitle({
      load: async () => session({ title: "Settled quality title" }),
      onSettled: async () => new Promise<void>(() => undefined),
      signal: new AbortController().signal,
      threadId: session().id,
      timeoutMs: 50,
    });

    await vi.advanceTimersByTimeAsync(50);
    await expect(observation).resolves.toBe("settled");
  });

  it("cancels an in-flight title observation when its owner goes away", async () => {
    const controller = new AbortController();
    let requestAborted = false;
    const observation = watchGeneratedSessionTitle({
      load: async (_threadId, signal) => new Promise<AgentSessionSummary>((_resolve, reject) => {
        signal.addEventListener("abort", () => {
          requestAborted = true;
          reject(new DOMException("aborted", "AbortError"));
        }, { once: true });
      }),
      onSettled: vi.fn(),
      signal: controller.signal,
      threadId: session().id,
    });
    controller.abort();

    await expect(observation).rejects.toMatchObject({ name: "AbortError" });
    expect(requestAborted).toBe(true);
  });

  it("rejects a direct Session response whose identity does not match the route", async () => {
    const requested = session().id;
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(session({
      id: "00000000-0000-4000-8000-000000000002",
    })), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadAgentSession(requested)).rejects.toBeInstanceOf(
      AgentSessionInvalidError,
    );
  });

  it("sends the exact optimistic rename and preserves stable conflicts", async () => {
    const current = session();
    const fetchMock = vi.fn(async (_input: unknown, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({
        title: "Quality Alpha",
        version: current.version,
      });
      return new Response(JSON.stringify({
        id: current.id,
        title: "Quality Alpha",
        version: "2026-08-30T04:00:01.000Z",
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(renameAgentSession(current, "  Quality   Alpha ")).resolves.toEqual({
      id: current.id,
      title: "Quality Alpha",
      version: "2026-08-30T04:00:01.000Z",
    });

    fetchMock.mockResolvedValueOnce(new Response(
      JSON.stringify({ code: "CHAT_SESSION_CHANGED" }),
      { status: 409 },
    ));
    await expect(renameAgentSession(current, "Changed"))
      .rejects.toBeInstanceOf(AgentSessionChangedError);
  });

  it("never sends a manual rename to the reserved Untitled sentinel", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(renameAgentSession(session(), "  Untitled  "))
      .rejects.toBeInstanceOf(AgentSessionTitleInvalidError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    "\u200B",
    "Untitled\u200B",
    "\uFE0F",
    "\u0301",
    "Alpha\u200B",
    "!!!",
  ])("never sends an invisible or baseless manual title: %s", async (title) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(renameAgentSession(session(), title))
      .rejects.toBeInstanceOf(AgentSessionTitleInvalidError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps local title validation distinct from a malformed rename response", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      id: session().id,
      title: "Untitled",
      version: "2026-08-30T04:00:01.000Z",
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(renameAgentSession(session(), " "))
      .rejects.toBeInstanceOf(AgentSessionTitleInvalidError);
    expect(fetchMock).not.toHaveBeenCalled();

    await expect(renameAgentSession(session(), "Quality Alpha"))
      .rejects.toBeInstanceOf(AgentSessionInvalidError);

    fetchMock.mockResolvedValueOnce(new Response(
      JSON.stringify({ code: "CHAT_SESSION_RUN_ACTIVE" }),
      { status: 409 },
    ));
    await expect(renameAgentSession(session(), "Another title"))
      .rejects.toBeInstanceOf(AgentSessionInvalidError);
  });

  it("maps active deletion and accepts only an empty 204 completion", async () => {
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ code: "CHAT_SESSION_RUN_ACTIVE" }),
      { status: 409 },
    ));
    vi.stubGlobal("fetch", fetchMock);
    await expect(deleteAgentSession(session()))
      .rejects.toBeInstanceOf(AgentSessionActiveRunError);

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(deleteAgentSession(session())).resolves.toBeUndefined();
  });

  it.each([
    { generation: 8, ownerId: "researcher-a" },
    { generation: 7, ownerId: "researcher-b" },
  ])("keeps a stale load-more page invisible after refresh or account switch", (request) => {
    const current = historyState();
    expect(sessionHistoryReducer(current, {
      cursor: "opaque_cursor",
      ...request,
      page: { next_cursor: null, sessions: [session({ title: "Stale" })] },
      type: "load-more-succeeded",
    })).toBe(current);
  });

  it("keeps a pre-mutation first-page snapshot invisible after refresh invalidation", () => {
    const current = historyState();
    const stale = session({ title: "Title before rename or delete" });

    expect(sessionHistoryReducer(current, {
      generation: current.generation - 1,
      ownerId: current.ownerId,
      page: { next_cursor: null, sessions: [stale] },
      type: "first-page-succeeded",
    })).toBe(current);
  });

  it("appends a load-more page through the Hook's production state reducer", () => {
    const current = historyState();
    const continuation = session({
      activity_at: "2026-08-30T03:59:59.000000Z",
      id: "00000000-0000-4000-8000-000000000002",
      title: "Continuation",
    });
    expect(sessionHistoryReducer(current, {
      cursor: "opaque_cursor",
      generation: 7,
      ownerId: "researcher-a",
      page: { next_cursor: null, sessions: [continuation] },
      type: "load-more-succeeded",
    })).toMatchObject({
      loadingMore: false,
      nextCursor: null,
      sessions: [...current.sessions, continuation],
      status: "ready",
    });
  });

});

function session(
  overrides: Partial<AgentSessionSummary> = {},
): AgentSessionSummary {
  return {
    activity_at: "2026-08-30T04:00:00.000000Z",
    created_at: "2026-08-29T04:00:00.000000Z",
    current_turn: null,
    id: "00000000-0000-4000-8000-000000000001",
    latest_turn: null,
    title: "Untitled",
    version: "2026-08-30T04:00:00.000Z",
    ...overrides,
  };
}

function databaseInstant(value: Date): string {
  return value.toISOString().replace("Z", "000Z");
}

function historyState(): SessionHistoryState {
  return {
    error: null,
    generation: 7,
    loadingMore: true,
    nextCursor: "opaque_cursor",
    ownerId: "researcher-a",
    sessions: [session()],
    status: "ready",
  };
}
