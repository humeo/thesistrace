import { z } from "zod";

import { isChatAnswer, type ChatAnswer } from "../../contracts/chat-answer.mjs";

import { MAX_CHAT_MESSAGE_BYTES, chatCommandFingerprint } from "./chat-request.js";
import { isCanonicalUuid } from "./uuid.js";

export const MAX_CHAT_COMMAND_BODY_BYTES = MAX_CHAT_MESSAGE_BYTES + 2 * 1024;
const TIMELINE_PAGE_SIZE = 20;

export type AssistantRecovery = Readonly<{
  status: "recovering" | "succeeded" | "failed";
  cause: "OUTPUT_LIMIT" | "CONTEXT_TOO_LARGE";
  attempts: 0 | 1;
  replacementMessageId: string | null;
  errorCode: string | null;
}>;

export type TurnKind = "prompt" | "continue";
export type TurnStatus =
  | "running"
  | "waiting_for_user"
  | "stopping"
  | "completed"
  | "stopped"
  | "failed";
export type CommandKind = "prompt" | "continue" | "steer" | "answer" | "stop";
type CommandStatus = "pending" | "accepted" | "rejected";
type AssistantItemStatus = "streaming" | "complete" | "stopped" | "failed";

export type QuestionOption = Readonly<{ description?: string; label: string }>;
export type PendingQuestion = Readonly<{
  interruptId: string;
  options: readonly QuestionOption[] | null;
  question: string;
  selectionMode: "free_text" | "single_select" | "multi_select";
  toolCallId: string;
}>;

export type PublicTurn = Readonly<{
  id: string;
  kind: TurnKind;
  modelKey: string;
  reasoningEffort: string;
  startedAt: string;
  status: TurnStatus;
  terminalErrorCode: string | null;
  question: PendingQuestion | null;
}>;

export type CommandReceipt = Readonly<{
  commandId: string;
  errorCode: string | null;
  kind: CommandKind;
  status: CommandStatus;
  turnId: string;
}>;

export type ChatTimelineEntry =
  | Readonly<{
      createdAt: string;
      entryId: string;
      kind: "user_input";
      payload: Readonly<{ content: string; inputId: string; source: "prompt" | "steer" | "answer" }>;
      turnId: string;
    }>
  | Readonly<{
      createdAt: string;
      entryId: string;
      kind: "assistant_message";
      payload: Readonly<{ content: string; status: AssistantItemStatus; recovery?: AssistantRecovery; supersedes?: string }>;
      turnId: string;
    }>
  | Readonly<{
      createdAt: string;
      entryId: string;
      kind: "tool_activity";
      payload: Readonly<{ name: string; status: "running" | "complete" | "failed" | "stopped" }>;
      turnId: string;
    }>
  | Readonly<{
      createdAt: string;
      entryId: string;
      kind: "a2ui";
      payload: Readonly<{ activityType: string; content: Record<string, unknown>; status: "loading" | "ready" | "error" }>;
      turnId: string;
    }>
  | Readonly<{
      createdAt: string;
      entryId: string;
      kind: "question";
      payload: PendingQuestion & Readonly<{ status: "pending" | "answered" | "stopped" }>;
      turnId: string;
    }>
  | Readonly<{
      createdAt: string;
      entryId: string;
      kind: "turn_outcome";
      payload: Readonly<{ errorCode?: string; status: "completed" | "stopped" | "failed" }>;
      turnId: string;
    }>;

type ChatTimelineTurn = Readonly<{
  completedAt: string | null;
  entries: readonly ChatTimelineEntry[];
  id: string;
  startedAt: string;
  status: TurnStatus;
}>;

export type TimelinePage = Readonly<{
  nextCursor: string | null;
  turns: readonly ChatTimelineTurn[];
}>;

export type TimelineCursor = Readonly<{
  startedAt: string;
  turnId: string;
}>;

export type SteerInput = Readonly<{
  content: string;
  expectedTurnId: string;
  fingerprint: Buffer;
  inputId: string;
}>;

export type StopInput = Readonly<{
  commandId: string;
  expectedTurnId: string;
  fingerprint: Buffer;
}>;

export class ChatControlError extends Error {
  constructor(
    readonly code:
      | "CHAT_CAPABILITY_UNAVAILABLE"
      | "CHAT_COMMAND_CONFLICT"
      | "CHAT_QUESTION_NOT_FOUND"
      | "CHAT_STORAGE_FAILURE"
      | "CHAT_TURN_NOT_STEERABLE"
      | "INVALID_CHAT_INPUT"
      | "STALE_CHAT_TURN",
    readonly status: 400 | 409 | 503,
  ) {
    super(code);
    this.name = "ChatControlError";
  }
}

const steerSchema = z.object({
  content: z.string(),
  expectedTurnId: z.string(),
  inputId: z.string(),
}).strict();

const stopSchema = z.object({
  commandId: z.string(),
  expectedTurnId: z.string(),
}).strict();

export async function readSteerInput(request: Request): Promise<SteerInput> {
  const parsed = steerSchema.safeParse(await readJson(request));
  if (
    !parsed.success
    || !isCanonicalUuid(parsed.data.expectedTurnId)
    || !isCanonicalUuid(parsed.data.inputId)
    || parsed.data.content.trim().length === 0
    || Buffer.byteLength(parsed.data.content, "utf8") > MAX_CHAT_MESSAGE_BYTES
  ) {
    throw invalidChatInput();
  }
  return {
    ...parsed.data,
    fingerprint: chatCommandFingerprint({
      content: parsed.data.content,
      expectedTurnId: parsed.data.expectedTurnId,
      inputId: parsed.data.inputId,
      kind: "steer",
    }),
  };
}

export async function readStopInput(request: Request): Promise<StopInput> {
  const parsed = stopSchema.safeParse(await readJson(request));
  if (
    !parsed.success
    || !isCanonicalUuid(parsed.data.expectedTurnId)
    || !isCanonicalUuid(parsed.data.commandId)
  ) {
    throw invalidChatInput();
  }
  return {
    ...parsed.data,
    fingerprint: chatCommandFingerprint({
      commandId: parsed.data.commandId,
      expectedTurnId: parsed.data.expectedTurnId,
      kind: "stop",
    }),
  };
}

export function projectAskUserInterrupt(event: unknown, expectedRunId: string): PendingQuestion | null {
  if (!isRecord(event) || event.type !== "RUN_FINISHED") return null;
  const outcome = event.outcome;
  if (!isRecord(outcome) || outcome.type !== "interrupt" || !Array.isArray(outcome.interrupts)) {
    return null;
  }
  if (outcome.interrupts.length !== 1) throw invalidChatInput();
  const interrupt = outcome.interrupts[0];
  if (!isRecord(interrupt)) throw invalidChatInput();
  const metadata = interrupt.metadata;
  const mastra = isRecord(metadata) ? metadata.mastra : undefined;
  const payload = isRecord(mastra) ? mastra.suspendPayload : undefined;
  const toolCallId = interrupt.toolCallId;
  const interruptId = interrupt.id;
  if (
    interrupt.reason !== "mastra:tool_suspend"
    || !isRecord(mastra)
    || mastra.type !== "mastra_suspend"
    || mastra.toolName !== "ask_user"
    || mastra.runId !== expectedRunId
    || typeof toolCallId !== "string"
    || typeof interruptId !== "string"
    || interruptId !== `${expectedRunId}::${toolCallId}`
    || toolCallId.length < 1
    || toolCallId.length > 512
    || interruptId.length > 800
    || !isRecord(payload)
  ) {
    throw invalidChatInput();
  }
  const question = cleanText(payload.question, 4_096);
  if (question === null || question === undefined) throw invalidChatInput();
  const options = readQuestionOptions(payload.options);
  const selectionMode = payload.selectionMode === undefined
    ? options === null ? "free_text" : "single_select"
    : payload.selectionMode;
  if (
    selectionMode !== "free_text"
    && selectionMode !== "single_select"
    && selectionMode !== "multi_select"
  ) {
    throw invalidChatInput();
  }
  if ((selectionMode === "free_text") !== (options === null)) throw invalidChatInput();
  return { interruptId, options, question, selectionMode, toolCallId };
}

export function validateAnswerForQuestion(
  answer: ChatAnswer,
  question: PendingQuestion,
): void {
  if (!isChatAnswer(answer)) throw invalidChatInput();
  const labels = new Set(question.options?.map((option) => option.label));
  if (
    answer.selections.some((label) => !labels.has(label))
    || (question.selectionMode === "single_select" && answer.selections.length > 1)
    || (question.selectionMode === "free_text" && answer.selections.length > 0)
  ) throw invalidChatInput();
}

export function encodeTimelineCursor(cursor: TimelineCursor): string {
  const startedAt = parseDatabaseUtc(cursor.startedAt);
  if (!isCanonicalUuid(cursor.turnId)) throw invalidChatInput();
  return Buffer.from(JSON.stringify({
    i: cursor.turnId,
    s: startedAt,
    v: 2,
  }), "utf8").toString("base64url");
}

export function readTimelineQuery(request: Request): Readonly<{
  before?: TimelineCursor;
  limit: number;
}> {
  const params = new URL(request.url).searchParams;
  for (const key of params.keys()) {
    if (key !== "before" && key !== "limit") throw invalidChatInput();
  }
  const before = params.get("before");
  const limit = params.get("limit");
  let parsedBefore: TimelineCursor | undefined;
  if (before !== null) {
    try {
      if (before.length === 0 || before.length > 512 || !/^[A-Za-z0-9_-]+$/u.test(before)) {
        throw invalidChatInput();
      }
      const bytes = Buffer.from(before, "base64url");
      if (bytes.toString("base64url") !== before) throw invalidChatInput();
      const decoded = JSON.parse(Buffer.from(before, "base64url").toString("utf8")) as unknown;
      if (
        !isRecord(decoded)
        || Object.keys(decoded).length !== 3
        || decoded.v !== 2
        || typeof decoded.s !== "string"
        || typeof decoded.i !== "string"
        || !isCanonicalUuid(decoded.i)
      ) {
        throw invalidChatInput();
      }
      parsedBefore = {
        startedAt: parseDatabaseUtc(decoded.s),
        turnId: decoded.i,
      };
    } catch (error) {
      if (error instanceof ChatControlError) throw error;
      throw invalidChatInput();
    }
  }
  const parsedLimit = limit === null ? TIMELINE_PAGE_SIZE : Number(limit);
  if (!Number.isInteger(parsedLimit) || parsedLimit < 1 || parsedLimit > TIMELINE_PAGE_SIZE) {
    throw invalidChatInput();
  }
  return { before: parsedBefore, limit: parsedLimit };
}

function parseDatabaseUtc(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/u.test(value)) {
    throw invalidChatInput();
  }
  const milliseconds = `${value.slice(0, 23)}Z`;
  const parsed = new Date(milliseconds);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString() !== milliseconds) {
    throw invalidChatInput();
  }
  return value;
}

function readQuestionOptions(value: unknown): readonly QuestionOption[] | null {
  if (value === undefined) return null;
  if (!Array.isArray(value) || value.length < 1 || value.length > 20) throw invalidChatInput();
  const options = value.map((item): QuestionOption => {
    if (!isRecord(item) || Object.keys(item).some((key) => key !== "label" && key !== "description")) {
      throw invalidChatInput();
    }
    const label = cleanText(item.label, 200);
    const description = item.description === undefined ? undefined : cleanText(item.description, 500);
    if (label === null || label === undefined || description === null) throw invalidChatInput();
    return description === undefined ? { label } : { description, label };
  });
  if (new Set(options.map((option) => option.label)).size !== options.length) throw invalidChatInput();
  return options;
}

async function readJson(request: Request): Promise<unknown> {
  try {
    return await request.clone().json();
  } catch {
    throw invalidChatInput();
  }
}

function cleanText(value: unknown, maxBytes: number): string | null | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string") return null;
  const clean = value.trim();
  return clean.length > 0 && Buffer.byteLength(clean, "utf8") <= maxBytes ? clean : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalidChatInput(): ChatControlError {
  return new ChatControlError("INVALID_CHAT_INPUT", 400);
}
