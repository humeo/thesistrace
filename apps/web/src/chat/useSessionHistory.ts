import { useCallback, useEffect, useRef, useState } from "react";

import {
  AgentSessionInvalidError,
  AgentSessionNotFoundError,
  appendAgentSessionPage,
  deleteAgentSession,
  loadAgentSession,
  loadAgentSessionPage,
  renameAgentSession,
  watchGeneratedSessionTitle,
  type AgentSessionPage,
  type AgentSessionSummary,
} from "./sessionHistory";

export type SessionHistoryStatus = "loading" | "ready" | "error";

export type SessionHistoryController = Readonly<{
  deleteSession: (session: AgentSessionSummary) => Promise<void>;
  error: string | null;
  loadMore: () => Promise<void>;
  loadingMore: boolean;
  nextCursor: string | null;
  refresh: () => void;
  refreshVersion: number;
  renameSession: (
    session: AgentSessionSummary,
    title: string,
  ) => Promise<Pick<AgentSessionSummary, "id" | "title" | "version">>;
  sessions: readonly AgentSessionSummary[];
  status: SessionHistoryStatus;
  watchGeneratedTitle: (threadId: string) => void;
}>;

export type SessionHistoryState = Readonly<{
  error: string | null;
  generation: number;
  loadingMore: boolean;
  nextCursor: string | null;
  ownerId: string;
  sessions: readonly AgentSessionSummary[];
  status: SessionHistoryStatus;
}>;

export type SessionHistoryAction =
  | Readonly<{
      generation: number;
      ownerId: string;
      page: AgentSessionPage;
      type: "first-page-succeeded";
    }>
  | Readonly<{
      cursor: string;
      generation: number;
      ownerId: string;
      page: AgentSessionPage;
      type: "load-more-succeeded";
    }>;

function initialState(ownerId: string, generation = 0): SessionHistoryState {
  return {
    error: null,
    generation,
    loadingMore: false,
    nextCursor: null,
    ownerId,
    sessions: [],
    status: "loading",
  };
}

export function useSessionHistory(researcherId: string): SessionHistoryController {
  const [state, setState] = useState<SessionHistoryState>(() => initialState(researcherId));
  const [refreshVersion, setRefreshVersion] = useState(0);
  const researcherRef = useRef(researcherId);
  const stateRef = useRef(state);
  const generationRef = useRef(0);
  const firstPageControllerRef = useRef<AbortController | null>(null);
  const loadMoreControllerRef = useRef<AbortController | null>(null);
  const titleWatchControllersRef = useRef(new Map<string, AbortController>());
  researcherRef.current = researcherId;
  stateRef.current = state;

  const refreshFirstPage = useCallback(async (parentSignal?: AbortSignal) => {
    firstPageControllerRef.current?.abort();
    loadMoreControllerRef.current?.abort();
    loadMoreControllerRef.current = null;
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    const { controller, detach } = linkedAbortController(parentSignal);
    firstPageControllerRef.current = controller;
    setState((current) => current.ownerId === researcherId
      ? {
          ...current,
          error: null,
          generation,
          loadingMore: false,
          status: current.sessions.length === 0 ? "loading" : "ready",
        }
      : initialState(researcherId, generation));
    setRefreshVersion((current) => current + 1);
    try {
      const page = await loadAgentSessionPage(undefined, controller.signal);
      if (
        controller.signal.aborted
        || researcherRef.current !== researcherId
        || generationRef.current !== generation
      ) return;
      setState((current) => sessionHistoryReducer(current, {
        generation,
        ownerId: researcherId,
        page,
        type: "first-page-succeeded",
      }));
    } catch (error) {
      if (
        controller.signal.aborted
        || researcherRef.current !== researcherId
        || generationRef.current !== generation
        || (error instanceof DOMException && error.name === "AbortError")
      ) return;
      setState((current) => current.ownerId === researcherId
        && current.generation === generation
        ? {
            ...current,
            error: "Chat history could not be loaded.",
            loadingMore: false,
            nextCursor: null,
            status: current.sessions.length === 0 ? "error" : "ready",
          }
        : current);
    } finally {
      detach();
      if (firstPageControllerRef.current === controller) {
        firstPageControllerRef.current = null;
      }
    }
  }, [researcherId]);

  useEffect(() => {
    void refreshFirstPage();
    return () => {
      abortSessionHistoryRequests(
        [firstPageControllerRef.current, loadMoreControllerRef.current],
        titleWatchControllersRef.current,
      );
      firstPageControllerRef.current = null;
      loadMoreControllerRef.current = null;
    };
  }, [refreshFirstPage]);

  const loadMore = useCallback(async () => {
    const current = stateRef.current;
    if (
      current.ownerId !== researcherId
      || current.status !== "ready"
      || current.loadingMore
      || current.nextCursor === null
      || loadMoreControllerRef.current !== null
    ) {
      return;
    }
    const cursor = current.nextCursor;
    const generation = generationRef.current;
    const controller = new AbortController();
    loadMoreControllerRef.current = controller;
    setState((state) => state.ownerId === researcherId
      ? { ...state, error: null, loadingMore: true }
      : state);
    const requestedFor = researcherRef.current;
    try {
      const page = await loadAgentSessionPage(cursor, controller.signal);
      if (
        researcherRef.current !== requestedFor
        || generationRef.current !== generation
      ) return;
      setState((current) => sessionHistoryReducer(current, {
        cursor,
        generation,
        ownerId: requestedFor,
        page,
        type: "load-more-succeeded",
      }));
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (
        researcherRef.current !== requestedFor
        || generationRef.current !== generation
      ) return;
      setState((current) => ({
        ...current,
        error: "More Chats could not be loaded.",
        loadingMore: false,
      }));
    } finally {
      if (loadMoreControllerRef.current === controller) {
        loadMoreControllerRef.current = null;
      }
    }
  }, [researcherId]);

  const refresh = useCallback(() => {
    void refreshFirstPage();
  }, [refreshFirstPage]);

  const renameSession = useCallback(async (
    session: AgentSessionSummary,
    title: string,
  ) => {
    const renamed = await renameAgentSession(session, title);
    setState((current) => ({
      ...current,
      sessions: current.ownerId === researcherId
        ? current.sessions.map((candidate) => candidate.id === renamed.id
          ? { ...candidate, title: renamed.title, version: renamed.version }
          : candidate)
        : current.sessions,
    }));
    refresh();
    return renamed;
  }, [refresh, researcherId]);

  const deleteSession = useCallback(async (session: AgentSessionSummary) => {
    await deleteAgentSession(session);
    titleWatchControllersRef.current.get(session.id)?.abort();
    titleWatchControllersRef.current.delete(session.id);
    setState((current) => ({
      ...current,
      sessions: current.ownerId === researcherId
        ? current.sessions.filter((candidate) => candidate.id !== session.id)
        : current.sessions,
    }));
    refresh();
  }, [refresh, researcherId]);
  const watchGeneratedTitle = useCallback((threadId: string) => {
    titleWatchControllersRef.current.get(threadId)?.abort();
    const controller = new AbortController();
    titleWatchControllersRef.current.set(threadId, controller);
    void watchGeneratedSessionTitle({
      onSettled: async (session, signal) => {
        if (
          !controller.signal.aborted
          && researcherRef.current === researcherId
        ) {
          setState((current) => current.ownerId === researcherId
            ? {
                ...current,
                sessions: current.sessions.map((candidate) => (
                  candidate.id === session.id ? session : candidate
                )),
              }
            : current);
          await refreshFirstPage(signal);
        }
      },
      signal: controller.signal,
      threadId,
    }).catch((error: unknown) => {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        // Title generation and its observation are best-effort. The durable
        // Untitled state remains the explicit product outcome.
      }
    }).finally(() => {
      if (titleWatchControllersRef.current.get(threadId) === controller) {
        titleWatchControllersRef.current.delete(threadId);
      }
    });
  }, [refreshFirstPage, researcherId]);

  const visible = state.ownerId === researcherId
    ? state
    : initialState(researcherId, generationRef.current);
  const activeSessionIds = visible.sessions
    .filter((session) => session.current_turn !== null)
    .map((session) => session.id).sort().join(",");

  useEffect(() => {
    if (activeSessionIds === "") return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (document.visibilityState !== "hidden") {
        const generation = generationRef.current;
        const updates = await Promise.all(activeSessionIds.split(",").map(async (id) => {
          try { return await loadAgentSession(id, controller.signal); }
          catch { return null; }
        }));
        if (controller.signal.aborted || researcherRef.current !== researcherId) return;
        const byId = new Map(updates.filter((session) => session !== null).map((session) => [session.id, session]));
        setState((current) => {
          if (current.ownerId !== researcherId || current.generation !== generation) return current;
          let changed = false;
          const sessions = current.sessions.map((session) => {
            const next = byId.get(session.id);
            if (next === undefined || JSON.stringify(next) === JSON.stringify(session)) return session;
            changed = true;
            return next;
          });
          const activityError = "Chat activity could not be refreshed.";
          const error = updates.includes(null)
            ? current.error ?? activityError
            : current.error === activityError ? null : current.error;
          return changed || error !== current.error ? { ...current, error, sessions } : current;
        });
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 2_000);
    };
    timer = setTimeout(() => void poll(), 2_000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [activeSessionIds, researcherId]);

  return {
    deleteSession,
    error: visible.error,
    loadMore,
    loadingMore: visible.loadingMore,
    nextCursor: visible.nextCursor,
    refresh,
    refreshVersion,
    renameSession,
    sessions: visible.sessions,
    status: visible.status,
    watchGeneratedTitle,
  };
}

export function sessionHistoryReducer(
  state: SessionHistoryState,
  action: SessionHistoryAction,
): SessionHistoryState {
  if (
    state.ownerId !== action.ownerId
    || state.generation !== action.generation
  ) return state;
  if (action.type === "first-page-succeeded") {
    return {
      ...state,
      error: null,
      loadingMore: false,
      nextCursor: action.page.next_cursor,
      sessions: action.page.sessions,
      status: "ready",
    };
  }
  if (
    state.status !== "ready"
    || state.nextCursor !== action.cursor
  ) return state;
  try {
    return {
      ...state,
      loadingMore: false,
      nextCursor: action.page.next_cursor,
      sessions: appendAgentSessionPage(state.sessions, action.page),
    };
  } catch {
    return {
      ...state,
      error: "Chat history response was invalid.",
      loadingMore: false,
      nextCursor: null,
      status: "error",
    };
  }
}

function abortSessionHistoryRequests(
  requests: readonly (AbortController | null)[],
  titleWatches: Map<string, AbortController>,
): void {
  for (const controller of requests) controller?.abort();
  for (const controller of titleWatches.values()) controller.abort();
  titleWatches.clear();
}

function linkedAbortController(parentSignal?: AbortSignal): Readonly<{
  controller: AbortController;
  detach: () => void;
}> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (parentSignal?.aborted === true) controller.abort();
  else parentSignal?.addEventListener("abort", abort, { once: true });
  return {
    controller,
    detach: () => parentSignal?.removeEventListener("abort", abort),
  };
}

export type SelectedSessionState =
  | Readonly<{ status: "not-required" }>
  | Readonly<{ status: "loading" }>
  | Readonly<{ session: AgentSessionSummary; status: "ready" }>
  | Readonly<{ status: "not-found" }>
  | Readonly<{ status: "invalid" }>
  | Readonly<{ status: "unavailable" }>;

export function useSelectedSession(
  threadId: string | null,
  listed: AgentSessionSummary | undefined,
  researcherId: string,
  historyStatus: SessionHistoryStatus,
  refreshVersion: number,
): SelectedSessionState {
  const selectionKey = `${researcherId}:${threadId ?? "new"}`;
  const [owned, setOwned] = useState<Readonly<{
    key: string;
    state: SelectedSessionState;
  }>>(() => ({
    key: selectionKey,
    state: threadId === null ? { status: "not-required" } : { status: "loading" },
  }));
  useEffect(() => {
    if (threadId === null) {
      setOwned({ key: selectionKey, state: { status: "not-required" } });
      return;
    }
    if (listed !== undefined) {
      setOwned({ key: selectionKey, state: { session: listed, status: "ready" } });
      return;
    }
    if (historyStatus === "loading") {
      setOwned({ key: selectionKey, state: { status: "loading" } });
      return;
    }
    const controller = new AbortController();
    let current = true;
    setOwned({ key: selectionKey, state: { status: "loading" } });
    void loadAgentSession(threadId, controller.signal)
      .then((session) => {
        if (!current) return;
        setOwned({
          key: selectionKey,
          state: { session, status: "ready" },
        });
      })
      .catch((error: unknown) => {
        if (!current || (error instanceof DOMException && error.name === "AbortError")) return;
        if (error instanceof AgentSessionNotFoundError) {
          setOwned({ key: selectionKey, state: { status: "not-found" } });
        } else if (error instanceof AgentSessionInvalidError) {
          setOwned({ key: selectionKey, state: { status: "invalid" } });
        } else {
          setOwned({ key: selectionKey, state: { status: "unavailable" } });
        }
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [historyStatus, listed, refreshVersion, researcherId, selectionKey, threadId]);
  return owned.key === selectionKey
    ? owned.state
    : threadId === null ? { status: "not-required" } : { status: "loading" };
}
