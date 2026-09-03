import { isUuid } from "../uuid";
import { decodeChatTurn, type ChatTurn } from "./chatProtocol";

const SESSION_PAGE_SIZE = 30;
const MAX_TITLE_CHARACTERS = 80;
const SESSION_REQUEST_TIMEOUT_MS = 5_000;
const GENERATED_TITLE_POLL_INTERVAL_MS = 1_000;
const GENERATED_TITLE_WATCH_TIMEOUT_MS = 20_000;
const SESSION_TITLE_DEFAULT_IGNORABLE = /\p{Default_Ignorable_Code_Point}/u;
const SESSION_TITLE_VISIBLE_BASE = /[\p{L}\p{N}\p{S}]/u;

export type AgentSessionSummary = Readonly<{
  activity_at: string;
  created_at: string;
  current_turn: ChatTurn | null;
  id: string;
  latest_turn: ChatTurn | null;
  title: string;
  version: string;
}>;

export type AgentSessionPage = Readonly<{
  next_cursor: string | null;
  sessions: readonly AgentSessionSummary[];
}>;

export type SessionGroup = Readonly<{
  label: "Today" | "Previous 7 days" | "Older";
  sessions: readonly AgentSessionSummary[];
}>;

export class AgentSessionInvalidError extends Error {
  constructor() {
    super("Agent Chat Session response is invalid");
    this.name = "AgentSessionInvalidError";
  }
}

export class AgentSessionTitleInvalidError extends Error {
  constructor() {
    super("Agent Chat Session title is invalid");
    this.name = "AgentSessionTitleInvalidError";
  }
}

export class AgentSessionUnavailableError extends Error {
  constructor() {
    super("Agent Chat Sessions are unavailable");
    this.name = "AgentSessionUnavailableError";
  }
}

export class AgentSessionNotFoundError extends Error {
  constructor() {
    super("Agent Chat Session was not found");
    this.name = "AgentSessionNotFoundError";
  }
}

export class AgentSessionChangedError extends Error {
  constructor() {
    super("Agent Chat Session changed");
    this.name = "AgentSessionChangedError";
  }
}

export class AgentSessionActiveRunError extends Error {
  constructor() {
    super("Agent Chat Session has an active Run");
    this.name = "AgentSessionActiveRunError";
  }
}

export type GeneratedTitleWatchResult = "settled" | "unchanged" | "stopped";

/**
 * Observe the independent best-effort title operation without extending the
 * Agent Run or keeping the Session busy. The final probe occurs after the
 * server's five-second title deadline, and every wait/request is abortable.
 */
export async function watchGeneratedSessionTitle(options: Readonly<{
  load?: (threadId: string, signal: AbortSignal) => Promise<AgentSessionSummary>;
  onSettled: (
    session: AgentSessionSummary,
    signal: AbortSignal,
  ) => Promise<void> | void;
  signal: AbortSignal;
  threadId: string;
  timeoutMs?: number;
  wait?: (delayMs: number, signal: AbortSignal) => Promise<void>;
}>): Promise<GeneratedTitleWatchResult> {
  const load = options.load ?? loadAgentSession;
  const wait = options.wait ?? waitForGeneratedTitleProbe;
  const deadlineController = new AbortController();
  let deadlineReached = false;
  const onCallerAbort = () => deadlineController.abort();
  if (options.signal.aborted) throw abortError();
  options.signal.addEventListener("abort", onCallerAbort, { once: true });
  const deadlineTimer = setTimeout(() => {
    deadlineReached = true;
    deadlineController.abort();
  }, options.timeoutMs ?? GENERATED_TITLE_WATCH_TIMEOUT_MS);

  try {
    while (true) {
      let session: AgentSessionSummary;
      try {
        session = await awaitWithAbort(
          load(options.threadId, deadlineController.signal),
          deadlineController.signal,
        );
      } catch (error) {
        if (options.signal.aborted) throw abortError();
        if (deadlineReached) return "unchanged";
        if (!(error instanceof AgentSessionUnavailableError)) return "stopped";
        try {
          await awaitWithAbort(
            wait(GENERATED_TITLE_POLL_INTERVAL_MS, deadlineController.signal),
            deadlineController.signal,
          );
        } catch {
          if (options.signal.aborted) throw abortError();
          return deadlineReached ? "unchanged" : "stopped";
        }
        continue;
      }
      if (session.title !== "Untitled") {
        try {
          await awaitWithAbort(
            Promise.resolve(options.onSettled(session, deadlineController.signal)),
            deadlineController.signal,
          );
        } catch {
          if (options.signal.aborted) throw abortError();
          return deadlineReached ? "settled" : "stopped";
        }
        return "settled";
      }
      try {
        await awaitWithAbort(
          wait(GENERATED_TITLE_POLL_INTERVAL_MS, deadlineController.signal),
          deadlineController.signal,
        );
      } catch {
        if (options.signal.aborted) throw abortError();
        return deadlineReached ? "unchanged" : "stopped";
      }
    }
  } finally {
    clearTimeout(deadlineTimer);
    options.signal.removeEventListener("abort", onCallerAbort);
  }
}

export async function loadAgentSessionPage(
  cursor?: string,
  signal?: AbortSignal,
): Promise<AgentSessionPage> {
  const parameters = new URLSearchParams();
  if (cursor !== undefined) parameters.set("cursor", cursor);
  const suffix = parameters.size === 0 ? "" : `?${parameters.toString()}`;
  const response = await sessionFetch(`/api/agent/sessions${suffix}`, { signal });
  if (!response.ok) throw new AgentSessionUnavailableError();
  try {
    return decodeAgentSessionPage(await response.json());
  } catch (error) {
    if (error instanceof AgentSessionInvalidError) throw error;
    throw new AgentSessionInvalidError();
  }
}

export async function loadAgentSession(
  threadId: string,
  signal?: AbortSignal,
): Promise<AgentSessionSummary> {
  const response = await sessionFetch(sessionEndpoint(threadId), { signal });
  if (response.status === 404) throw new AgentSessionNotFoundError();
  if (!response.ok) throw new AgentSessionUnavailableError();
  try {
    const session = decodeAgentSessionSummary(await response.json());
    if (session.id !== threadId) throw new AgentSessionInvalidError();
    return session;
  } catch (error) {
    if (error instanceof AgentSessionInvalidError) throw error;
    throw new AgentSessionInvalidError();
  }
}

export async function renameAgentSession(
  session: AgentSessionSummary,
  title: string,
  signal?: AbortSignal,
): Promise<Pick<AgentSessionSummary, "id" | "title" | "version">> {
  const normalized = normalizeManualTitle(title);
  const response = await sessionFetch(sessionEndpoint(session.id), {
    body: JSON.stringify({ title: normalized, version: session.version }),
    headers: { "content-type": "application/json" },
    method: "PATCH",
    signal,
  });
  if (response.status === 404) throw new AgentSessionNotFoundError();
  if (response.status === 409) {
    const code = await responseCode(response);
    if (code === "CHAT_SESSION_CHANGED") throw new AgentSessionChangedError();
    throw new AgentSessionInvalidError();
  }
  if (!response.ok) throw new AgentSessionUnavailableError();
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new AgentSessionInvalidError();
  }
  if (
    !isExactRecord(value, ["id", "title", "version"])
    || value.id !== session.id
    || typeof value.title !== "string"
    || value.title !== normalized
    || normalizeTitle(value.title) !== value.title
    || typeof value.version !== "string"
    || !isExactUtc(value.version)
  ) {
    throw new AgentSessionInvalidError();
  }
  return { id: value.id, title: value.title, version: value.version };
}

export async function deleteAgentSession(
  session: AgentSessionSummary,
  signal?: AbortSignal,
): Promise<void> {
  const response = await sessionFetch(sessionEndpoint(session.id), {
    method: "DELETE",
    signal,
  });
  if (response.status === 404) throw new AgentSessionNotFoundError();
  if (response.status === 409) {
    const code = await responseCode(response);
    if (code === "CHAT_SESSION_RUN_ACTIVE") throw new AgentSessionActiveRunError();
    throw new AgentSessionInvalidError();
  }
  if (response.status !== 204) throw new AgentSessionUnavailableError();
}

export function decodeAgentSessionPage(value: unknown): AgentSessionPage {
  if (
    !isExactRecord(value, ["next_cursor", "sessions"])
    || !Array.isArray(value.sessions)
    || value.sessions.length > SESSION_PAGE_SIZE
    || !(value.next_cursor === null || isCursor(value.next_cursor))
  ) {
    throw new AgentSessionInvalidError();
  }
  const sessions = value.sessions.map(decodeAgentSessionSummary);
  const ids = new Set<string>();
  for (const [index, session] of sessions.entries()) {
    if (ids.has(session.id)) throw new AgentSessionInvalidError();
    ids.add(session.id);
    const previous = sessions[index - 1];
    if (
      previous !== undefined
      && (
        previous.activity_at < session.activity_at
        || (previous.activity_at === session.activity_at && previous.id <= session.id)
      )
    ) {
      throw new AgentSessionInvalidError();
    }
  }
  if (sessions.length < SESSION_PAGE_SIZE && value.next_cursor !== null) {
    throw new AgentSessionInvalidError();
  }
  return { next_cursor: value.next_cursor, sessions };
}

export function decodeAgentSessionSummary(value: unknown): AgentSessionSummary {
  if (
    !isExactRecord(value, [
      "activity_at",
      "created_at",
      "current_turn",
      "id",
      "latest_turn",
      "title",
      "version",
    ])
    || typeof value.activity_at !== "string"
    || !isExactDatabaseUtc(value.activity_at)
    || typeof value.created_at !== "string"
    || !isExactDatabaseUtc(value.created_at)
    || value.created_at > value.activity_at
    || typeof value.id !== "string"
    || !isUuid(value.id)
    || value.id !== value.id.toLowerCase()
    || typeof value.title !== "string"
    || normalizeTitle(value.title) !== value.title
    || typeof value.version !== "string"
    || !isExactUtc(value.version)
  ) {
    throw new AgentSessionInvalidError();
  }
  let currentTurn: ChatTurn | null;
  let latestTurn: ChatTurn | null;
  try {
    currentTurn = decodeChatTurn(value.current_turn);
    latestTurn = decodeChatTurn(value.latest_turn);
  } catch {
    throw new AgentSessionInvalidError();
  }
  if (
    (currentTurn !== null && !["running", "waiting_for_user", "stopping"].includes(currentTurn.status))
    || (currentTurn !== null && currentTurn.id !== latestTurn?.id)
  ) throw new AgentSessionInvalidError();
  return {
    activity_at: value.activity_at,
    created_at: value.created_at,
    current_turn: currentTurn,
    id: value.id,
    latest_turn: latestTurn,
    title: value.title,
    version: value.version,
  };
}

export function appendAgentSessionPage(
  existing: readonly AgentSessionSummary[],
  page: AgentSessionPage,
): readonly AgentSessionSummary[] {
  const seen = new Set(existing.map((session) => session.id));
  if (page.sessions.some((session) => seen.has(session.id))) {
    throw new AgentSessionInvalidError();
  }
  const boundary = existing.at(-1);
  const first = page.sessions[0];
  if (boundary !== undefined && first !== undefined && !comesBefore(boundary, first)) {
    throw new AgentSessionInvalidError();
  }
  return [...existing, ...page.sessions];
}

export function groupSessionsByRecency(
  sessions: readonly AgentSessionSummary[],
  now = new Date(),
): readonly SessionGroup[] {
  if (Number.isNaN(now.getTime())) throw new AgentSessionInvalidError();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const previousSevenDays = new Date(today);
  previousSevenDays.setDate(previousSevenDays.getDate() - 7);
  const buckets: Record<SessionGroup["label"], AgentSessionSummary[]> = {
    Today: [],
    "Previous 7 days": [],
    Older: [],
  };
  for (const session of sessions) {
    const activity = databaseInstantDate(session.activity_at);
    if (activity >= today) buckets.Today.push(session);
    else if (activity >= previousSevenDays) buckets["Previous 7 days"].push(session);
    else buckets.Older.push(session);
  }
  return (["Today", "Previous 7 days", "Older"] as const).flatMap((label) => (
    buckets[label].length === 0 ? [] : [{ label, sessions: buckets[label] }]
  ));
}

function databaseInstantDate(value: string): Date {
  return new Date(`${value.slice(0, 23)}Z`);
}

function normalizeTitle(value: string): string {
  const normalized = value.trim().replace(/\s+/gu, " ");
  if (
    normalized.length === 0
    || /[\u0000-\u001f\u007f-\u009f]/u.test(normalized)
    || SESSION_TITLE_DEFAULT_IGNORABLE.test(normalized)
    || !SESSION_TITLE_VISIBLE_BASE.test(normalized)
    || [...normalized].length > MAX_TITLE_CHARACTERS
  ) {
    throw new AgentSessionInvalidError();
  }
  return normalized;
}

function normalizeManualTitle(value: string): string {
  let normalized: string;
  try {
    normalized = normalizeTitle(value);
  } catch (error) {
    if (error instanceof AgentSessionInvalidError) {
      throw new AgentSessionTitleInvalidError();
    }
    throw error;
  }
  if (normalized === "Untitled") throw new AgentSessionTitleInvalidError();
  return normalized;
}

function comesBefore(left: AgentSessionSummary, right: AgentSessionSummary): boolean {
  return left.activity_at > right.activity_at
    || (left.activity_at === right.activity_at && left.id > right.id);
}

async function sessionFetch(
  input: RequestInfo | URL,
  init: RequestInit,
): Promise<Response> {
  const controller = new AbortController();
  const parentSignal = init.signal;
  let timedOut = false;
  const onParentAbort = () => controller.abort();
  if (parentSignal?.aborted === true) controller.abort();
  else parentSignal?.addEventListener("abort", onParentAbort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, SESSION_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(input, {
      ...init,
      credentials: "same-origin",
      signal: controller.signal,
    });
    if (response.status === 204) return response;
    // A header-only response is not a completed metadata request. Retain the
    // caller cancellation and deadline until its whole body has arrived.
    const body = await awaitWithAbort(response.arrayBuffer(), controller.signal);
    return new Response(body, {
      headers: response.headers,
      status: response.status,
      statusText: response.statusText,
    });
  } catch (error) {
    if (parentSignal?.aborted === true) throw abortError();
    if (timedOut) throw new AgentSessionUnavailableError();
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new AgentSessionUnavailableError();
  } finally {
    clearTimeout(timer);
    parentSignal?.removeEventListener("abort", onParentAbort);
  }
}

function awaitWithAbort<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      reject(abortError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
    operation.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        resolve(value);
      },
      (error: unknown) => {
        signal.removeEventListener("abort", onAbort);
        reject(error);
      },
    );
  });
}

function waitForGeneratedTitleProbe(
  delayMs: number,
  signal: AbortSignal,
): Promise<void> {
  if (signal.aborted) return Promise.reject(abortError());
  if (delayMs === 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delayMs);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function abortError(): DOMException {
  return new DOMException("The title observation was aborted.", "AbortError");
}

function sessionEndpoint(threadId: string): string {
  return `/api/agent/sessions/${encodeURIComponent(threadId)}`;
}

async function responseCode(response: Response): Promise<string> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new AgentSessionInvalidError();
  }
  if (!isExactRecord(value, ["code"]) || typeof value.code !== "string") {
    throw new AgentSessionInvalidError();
  }
  return value.code;
}

function isCursor(value: unknown): value is string {
  return typeof value === "string"
    && value.length <= 512
    && /^[A-Za-z0-9_-]+$/.test(value);
}

function isExactUtc(value: string): boolean {
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString() === value;
}

function isExactDatabaseUtc(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/u.test(value)) return false;
  const milliseconds = `${value.slice(0, 23)}Z`;
  return isExactUtc(milliseconds);
}

function isExactRecord(
  value: unknown,
  keys: readonly string[],
): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}
