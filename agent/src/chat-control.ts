import { z } from "zod";

import { MAX_CHAT_MESSAGE_BYTES, chatCommandFingerprint } from "./chat-request.js";
import { isCanonicalUuid } from "./uuid.js";

export const MAX_CHAT_COMMAND_BODY_BYTES = MAX_CHAT_MESSAGE_BYTES + 2 * 1024;
export const TIMELINE_PAGE_SIZE = 50;

export type TurnKind = "prompt" | "continue";
export type TurnStatus =
  | "running"
  | "waiting_for_user"
  | "stopping"
  | "completed"
  | "stopped"
  | "failed";
export type CommandKind = "prompt" | "continue" | "steer" | "answer" | "stop";
export type CommandStatus = "pending" | "accepted" | "rejected";
export type AssistantItemStatus = "streaming" | "complete" | "stopped" | "failed";

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
      payload: Readonly<{ content: string; status: AssistantItemStatus }>;
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

export type TimelinePage = Readonly<{
  entries: readonly ChatTimelineEntry[];
  nextCursor: string | null;
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
  answer: string | readonly string[],
  question: PendingQuestion,
): void {
  if (question.selectionMode === "multi_select") {
    if (!Array.isArray(answer)) throw invalidChatInput();
    const labels = new Set(question.options?.map((option) => option.label));
    if (new Set(answer).size !== answer.length || answer.some((value) => !labels.has(value))) {
      throw invalidChatInput();
    }
    return;
  }
  if (typeof answer !== "string") throw invalidChatInput();
  if (
    question.selectionMode === "single_select"
    && !question.options?.some((option) => option.label === answer)
  ) {
    throw invalidChatInput();
  }
}

export function encodeTimelineCursor(sequence: number): string {
  if (!Number.isSafeInteger(sequence) || sequence < 1) throw invalidChatInput();
  return Buffer.from(JSON.stringify({ sequence, version: 1 }), "utf8").toString("base64url");
}

export function readTimelineQuery(request: Request): Readonly<{ before?: number; limit: number }> {
  const params = new URL(request.url).searchParams;
  for (const key of params.keys()) {
    if (key !== "before" && key !== "limit") throw invalidChatInput();
  }
  const before = params.get("before");
  const limit = params.get("limit");
  let parsedBefore: number | undefined;
  if (before !== null) {
    try {
      const decoded = JSON.parse(Buffer.from(before, "base64url").toString("utf8")) as unknown;
      if (
        !isRecord(decoded)
        || Object.keys(decoded).length !== 2
        || decoded.version !== 1
        || !Number.isSafeInteger(decoded.sequence)
        || (decoded.sequence as number) < 1
      ) {
        throw invalidChatInput();
      }
      parsedBefore = decoded.sequence as number;
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
