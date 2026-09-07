import { isUuid } from "../uuid";

const REQUEST_TIMEOUT_MS = 5_000;
const TIMELINE_LIMIT = 20;

export type AssistantRecovery = Readonly<{
  status: "recovering" | "succeeded" | "failed";
  cause: "OUTPUT_LIMIT" | "CONTEXT_TOO_LARGE";
  attempts: 0 | 1;
  replacementMessageId: string | null;
  errorCode: string | null;
}>;

export type ChatTurnStatus =
  | "running"
  | "waiting_for_user"
  | "stopping"
  | "completed"
  | "stopped"
  | "failed";

export type ChatQuestion = Readonly<{
  interrupt_id: string;
  options: readonly Readonly<{ description?: string; label: string }>[] | null;
  question: string;
  selection_mode: "free_text" | "single_select" | "multi_select";
}>;

export type ChatTurn = Readonly<{
  id: string;
  kind: "prompt" | "continue";
  model_key: string;
  question: ChatQuestion | null;
  reasoning_effort: string;
  started_at: string;
  status: ChatTurnStatus;
  terminal_error_code: string | null;
}>;

export type TimelineEntry = Readonly<{
  created_at: string;
  entry_id: string;
  turn_id: string;
}> & (
  | Readonly<{
      kind: "user_input";
      payload: Readonly<{ content: string; inputId: string; source: "prompt" | "steer" | "answer" }>;
    }>
  | Readonly<{
      kind: "assistant_message";
      payload: Readonly<{ content: string; status: "streaming" | "complete" | "stopped" | "failed"; recovery?: AssistantRecovery; supersedes?: string }>;
    }>
  | Readonly<{
      kind: "tool_activity";
      payload: Readonly<{ name: string; status: "running" | "complete" | "failed" | "stopped" }>;
    }>
  | Readonly<{
      kind: "a2ui";
      payload: Readonly<{ activityType: string; content: Record<string, unknown>; status: "loading" | "ready" | "error" }>;
    }>
  | Readonly<{
      kind: "question";
      payload: ChatQuestion & Readonly<{ status: "pending" | "answered" | "stopped" }>;
    }>
  | Readonly<{
      kind: "turn_outcome";
      payload: Readonly<{ errorCode?: string; status: "completed" | "stopped" | "failed" }>;
    }>
);

export type TimelineTurn = Readonly<{
  completed_at: string | null;
  entries: readonly TimelineEntry[];
  id: string;
  started_at: string;
  status: ChatTurnStatus;
}>;

export type TimelinePage = Readonly<{
  next_cursor: string | null;
  turns: readonly TimelineTurn[];
}>;

export type ChatCommandReceipt = Readonly<{
  command_id: string;
  error_code: string | null;
  kind: "prompt" | "continue" | "steer" | "answer" | "stop";
  status: "pending" | "accepted" | "rejected";
  turn_id: string;
}>;

export class ChatApiError extends Error {
  constructor(readonly code: string, readonly status: number) {
    super(code);
    this.name = "ChatApiError";
  }
}

export class ChatCommandAcceptanceUnknownError extends Error {
  constructor() {
    super("CHAT_COMMAND_ACCEPTANCE_UNKNOWN");
    this.name = "ChatCommandAcceptanceUnknownError";
  }
}

export async function loadTimelinePage(
  threadId: string,
  before?: string,
  signal?: AbortSignal,
): Promise<TimelinePage> {
  const query = new URLSearchParams({ limit: String(TIMELINE_LIMIT) });
  if (before !== undefined) query.set("before", before);
  const response = await boundedFetch(
    `/api/agent/sessions/${encodeURIComponent(threadId)}/timeline?${query.toString()}`,
    { signal },
  );
  if (!response.ok) throw await apiError(response);
  return decodeTimelinePage(await readJson(response));
}

export async function steerChat(
  threadId: string,
  input: Readonly<{ content: string; expectedTurnId: string; inputId: string }>,
  signal?: AbortSignal,
): Promise<ChatCommandReceipt> {
  return commandRequest(
    `/api/agent/sessions/${encodeURIComponent(threadId)}/steer`,
    input,
    signal,
  );
}

export async function stopChat(
  threadId: string,
  input: Readonly<{ commandId: string; expectedTurnId: string }>,
  signal?: AbortSignal,
): Promise<ChatCommandReceipt> {
  return commandRequest(
    `/api/agent/sessions/${encodeURIComponent(threadId)}/stop`,
    input,
    signal,
  );
}

export async function loadCommandReceipt(
  threadId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<ChatCommandReceipt> {
  const response = await boundedFetch(
    `/api/agent/sessions/${encodeURIComponent(threadId)}/commands/${encodeURIComponent(commandId)}`,
    { signal },
  );
  if (!response.ok) throw await apiError(response);
  return decodeCommandReceipt(await readJson(response));
}

export function decodeChatTurn(value: unknown): ChatTurn | null {
  if (value === null) return null;
  if (!isExactRecord(value, [
    "id",
    "kind",
    "model_key",
    "question",
    "reasoning_effort",
    "started_at",
    "status",
    "terminal_error_code",
  ])) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  if (
    typeof value.id !== "string"
    || !isUuid(value.id)
    || (value.kind !== "prompt" && value.kind !== "continue")
    || typeof value.model_key !== "string"
    || typeof value.reasoning_effort !== "string"
    || typeof value.started_at !== "string"
    || !isDatabaseUtc(value.started_at)
    || !isTurnStatus(value.status)
    || (value.terminal_error_code !== null && typeof value.terminal_error_code !== "string")
  ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  return {
    id: value.id,
    kind: value.kind,
    model_key: value.model_key,
    question: decodeQuestion(value.question),
    reasoning_effort: value.reasoning_effort,
    started_at: value.started_at,
    status: value.status,
    terminal_error_code: value.terminal_error_code,
  };
}

export function decodeTimelinePage(value: unknown): TimelinePage {
  if (
    !isExactRecord(value, ["next_cursor", "turns"])
    || !Array.isArray(value.turns)
    || value.turns.length > TIMELINE_LIMIT
    || !(value.next_cursor === null || isCursor(value.next_cursor))
  ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  const turns = value.turns.map(decodeTimelineTurn);
  if (new Set(turns.map((turn) => turn.id)).size !== turns.length) {
    throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  }
  return { next_cursor: value.next_cursor, turns };
}

export function decodeCommandReceipt(value: unknown): ChatCommandReceipt {
  if (!isExactRecord(value, ["command_id", "error_code", "kind", "status", "turn_id"])) {
    throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  }
  if (
    typeof value.command_id !== "string"
    || !isUuid(value.command_id)
    || typeof value.turn_id !== "string"
    || !isUuid(value.turn_id)
    || !["prompt", "continue", "steer", "answer", "stop"].includes(String(value.kind))
    || !["pending", "accepted", "rejected"].includes(String(value.status))
    || (value.error_code !== null && typeof value.error_code !== "string")
  ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  return value as ChatCommandReceipt;
}

async function commandRequest(
  endpoint: string,
  input: object,
  signal?: AbortSignal,
): Promise<ChatCommandReceipt> {
  let response: Response;
  try {
    response = await boundedFetch(endpoint, {
      body: JSON.stringify(input),
      headers: { "content-type": "application/json" },
      method: "POST",
      signal,
    });
  } catch (error) {
    if (signal?.aborted === true) throw error;
    throw new ChatCommandAcceptanceUnknownError();
  }
  if (!response.ok) {
    const error = await apiError(response);
    if (response.status >= 500) throw new ChatCommandAcceptanceUnknownError();
    throw error;
  }
  return decodeCommandReceipt(await readJson(response));
}

async function boundedFetch(input: RequestInfo | URL, init: RequestInit): Promise<Response> {
  const timeout = new AbortController();
  const signal = init.signal == null
    ? timeout.signal
    : AbortSignal.any([init.signal, timeout.signal]);
  const timer = window.setTimeout(() => timeout.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(input, { ...init, credentials: "same-origin", signal });
  } finally {
    window.clearTimeout(timer);
  }
}

async function apiError(response: Response): Promise<ChatApiError> {
  try {
    const value = await readJson(response);
    if (isExactRecord(value, ["code"]) && typeof value.code === "string") {
      return new ChatApiError(value.code, response.status);
    }
  } catch {
    // Collapse malformed public errors at this boundary.
  }
  return new ChatApiError("CHAT_SERVICE_UNAVAILABLE", response.status);
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ChatApiError("INVALID_CHAT_RESPONSE", response.status);
  }
}

function decodeTimelineTurn(value: unknown): TimelineTurn {
  if (!isExactRecord(value, ["completed_at", "entries", "id", "started_at", "status"])) {
    throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  }
  if (
    typeof value.id !== "string"
    || !isUuid(value.id)
    || typeof value.started_at !== "string"
    || !isDatabaseUtc(value.started_at)
    || (value.completed_at !== null && (
      typeof value.completed_at !== "string" || !isDatabaseUtc(value.completed_at)
    ))
    || !isTurnStatus(value.status)
    || !Array.isArray(value.entries)
  ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  const turnId = value.id;
  const entries = value.entries.map((entry) => decodeTimelineEntry(entry, turnId));
  if (new Set(entries.map((entry) => entry.entry_id)).size !== entries.length) {
    throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  }
  return {
    completed_at: value.completed_at,
    entries,
    id: turnId,
    started_at: value.started_at,
    status: value.status,
  };
}

function decodeTimelineEntry(value: unknown, expectedTurnId: string): TimelineEntry {
  if (!isExactRecord(value, ["created_at", "entry_id", "kind", "payload", "turn_id"])) {
    throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  }
  if (
    typeof value.created_at !== "string"
    || !isDatabaseUtc(value.created_at)
    || typeof value.entry_id !== "string"
    || value.entry_id.length < 1
    || value.entry_id.length > 800
    || typeof value.turn_id !== "string"
    || !isUuid(value.turn_id)
    || value.turn_id !== expectedTurnId
    || !isRecord(value.payload)
  ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  const base = {
    created_at: value.created_at,
    entry_id: value.entry_id,
    turn_id: value.turn_id,
  };
  if (value.kind === "user_input") {
    if (
      !isExactRecord(value.payload, ["content", "inputId", "source"])
      || typeof value.payload.content !== "string"
      || typeof value.payload.inputId !== "string"
      || !isUuid(value.payload.inputId)
      || !["prompt", "steer", "answer"].includes(String(value.payload.source))
    ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
    return { ...base, kind: value.kind, payload: value.payload } as TimelineEntry;
  }
  if (value.kind === "assistant_message") {
    if (
      !isExactRecord(value.payload, ["content", "status", ...(isRecord(value.payload) && value.payload.recovery !== undefined ? ["recovery"] : []), ...(isRecord(value.payload) && value.payload.supersedes !== undefined ? ["supersedes"] : [])])
      || typeof value.payload.content !== "string"
      || (value.payload.recovery !== undefined && !isAssistantRecovery(value.payload.recovery))
      || (value.payload.supersedes !== undefined && (typeof value.payload.supersedes !== "string" || !isUuid(value.payload.supersedes)))
      || !["streaming", "complete", "stopped", "failed"].includes(String(value.payload.status))
    ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
    return { ...base, kind: value.kind, payload: value.payload } as TimelineEntry;
  }
  if (value.kind === "tool_activity") {
    if (
      !isExactRecord(value.payload, ["name", "status"])
      || typeof value.payload.name !== "string"
      || !["running", "complete", "failed", "stopped"].includes(String(value.payload.status))
    ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
    return { ...base, kind: value.kind, payload: value.payload } as TimelineEntry;
  }
  if (value.kind === "a2ui") {
    if (
      !isExactRecord(value.payload, ["activityType", "content", "status"])
      || typeof value.payload.activityType !== "string"
      || !isRecord(value.payload.content)
      || !["loading", "ready", "error"].includes(String(value.payload.status))
    ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
    return { ...base, kind: value.kind, payload: value.payload } as TimelineEntry;
  }
  if (value.kind === "question") {
    const question = decodeQuestion(value.payload);
    if (
      question === null
      || typeof value.payload.status !== "string"
      || !["pending", "answered", "stopped"].includes(value.payload.status)
    ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
    return { ...base, kind: value.kind, payload: value.payload } as TimelineEntry;
  }
  if (value.kind === "turn_outcome") {
    const keys = value.payload.errorCode === undefined ? ["status"] : ["errorCode", "status"];
    if (
      !isExactRecord(value.payload, keys)
      || !["completed", "stopped", "failed"].includes(String(value.payload.status))
      || (value.payload.errorCode !== undefined && typeof value.payload.errorCode !== "string")
    ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
    return { ...base, kind: value.kind, payload: value.payload } as TimelineEntry;
  }
  throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
}

function decodeQuestion(value: unknown): ChatQuestion | null {
  if (value === null) return null;
  if (!isRecord(value)) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  const allowed = ["interrupt_id", "options", "question", "selection_mode"];
  const withStatus = [...allowed, "status"];
  if (!isExactRecord(value, allowed) && !isExactRecord(value, withStatus)) {
    throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  }
  if (
    typeof value.interrupt_id !== "string"
    || typeof value.question !== "string"
    || !["free_text", "single_select", "multi_select"].includes(String(value.selection_mode))
  ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
  let options: ChatQuestion["options"] = null;
  if (value.options !== null) {
    if (!Array.isArray(value.options) || value.options.length < 1 || value.options.length > 20) {
      throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
    }
    options = value.options.map((option) => {
      if (
        !isRecord(option)
        || !isExactRecord(option, option.description === undefined ? ["label"] : ["description", "label"])
        || typeof option.label !== "string"
        || (option.description !== undefined && typeof option.description !== "string")
      ) throw new ChatApiError("INVALID_CHAT_RESPONSE", 500);
      return option as { description?: string; label: string };
    });
  }
  return {
    interrupt_id: value.interrupt_id,
    options,
    question: value.question,
    selection_mode: value.selection_mode as ChatQuestion["selection_mode"],
  };
}

function isTurnStatus(value: unknown): value is ChatTurnStatus {
  return typeof value === "string" && [
    "running",
    "waiting_for_user",
    "stopping",
    "completed",
    "stopped",
    "failed",
  ].includes(value);
}

function isCursor(value: unknown): value is string {
  return typeof value === "string" && value.length <= 512 && /^[A-Za-z0-9_-]+$/u.test(value);
}

function isDatabaseUtc(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/u.test(value)) return false;
  const date = new Date(`${value.slice(0, 23)}Z`);
  return !Number.isNaN(date.getTime());
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isAssistantRecovery(value: unknown): value is AssistantRecovery {
  return isExactRecord(value, ["status", "cause", "attempts", "replacementMessageId", "errorCode"])
    && ["recovering", "succeeded", "failed"].includes(String(value.status))
    && ["OUTPUT_LIMIT", "CONTEXT_TOO_LARGE"].includes(String(value.cause))
    && (value.attempts === 0 || value.attempts === 1)
    && (value.replacementMessageId === null || (typeof value.replacementMessageId === "string" && isUuid(value.replacementMessageId)))
    && (value.errorCode === null || typeof value.errorCode === "string");
}

function isExactRecord(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  if (!isRecord(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}
