import { createHash } from "node:crypto";

import { RunAgentInputSchema, type RunAgentInput } from "@ag-ui/core";
import { z } from "zod";

import { formatChatAnswer, isChatAnswer, type ChatAnswer } from "../../contracts/chat-answer.mjs";

import type { ModelRegistry, ReasoningEffort } from "./model-registry.js";
import { isCanonicalUuid } from "./uuid.js";

export const MAX_CHAT_MESSAGE_BYTES = 16 * 1024;

const promptSelectionSchema = z.object({
  command: z.literal("prompt"),
  modelKey: z.string(),
  reasoningEffort: z.string(),
  sessionMode: z.enum(["new", "existing"]),
}).strict();

const continueSelectionSchema = z.object({
  command: z.literal("continue"),
  modelKey: z.string(),
  reasoningEffort: z.string(),
  sessionMode: z.literal("existing"),
}).strict();

const answerSelectionSchema = z.object({
  command: z.literal("answer"),
  inputId: z.string(),
  interruptId: z.string().min(1).max(800),
}).strict();

const forwardedPropsSchema = z.object({
  thesistrace: z.discriminatedUnion("command", [
    promptSelectionSchema,
    continueSelectionSchema,
    answerSelectionSchema,
  ]),
}).strict();

export type ValidatedPromptRun = Readonly<{
  command: "prompt";
  commandId: string;
  input: RunAgentInput;
  modelKey: string;
  reasoningEffort: ReasoningEffort;
  sessionMode: "new" | "existing";
  userMessage: Readonly<{ content: string; id: string; role: "user" }>;
}>;

type ValidatedContinueRun = Readonly<{
  command: "continue";
  commandId: string;
  input: RunAgentInput;
  modelKey: string;
  reasoningEffort: ReasoningEffort;
  sessionMode: "existing";
}>;

export type { ChatAnswer } from "../../contracts/chat-answer.mjs";

export type ValidatedAnswerRun = Readonly<{
  answer: ChatAnswer;
  command: "answer";
  commandId: string;
  input: RunAgentInput;
  interruptId: string;
}>;

export type ValidatedChatRun = ValidatedPromptRun | ValidatedContinueRun | ValidatedAnswerRun;

export class ChatRequestError extends Error {
  constructor(
    readonly code:
      | "CHAT_INPUT_TOO_LARGE"
      | "INVALID_CHAT_INPUT"
      | "INVALID_MODEL"
      | "UNSUPPORTED_REASONING",
    readonly status: 400 | 413,
  ) {
    super(code);
    this.name = "ChatRequestError";
  }
}

export async function readValidatedChatRun(
  request: Request,
  registry: ModelRegistry,
): Promise<ValidatedChatRun> {
  const input = await readRunInput(request);
  if (!isCanonicalRunEnvelope(input)) throw invalidRequest();

  const forwarded = forwardedPropsSchema.safeParse(input.forwardedProps);
  if (!forwarded.success) throw invalidRequest();
  const command = forwarded.data.thesistrace;

  if (command.command === "answer") {
    if (
      input.messages.length !== 0
      || input.resume?.length !== 1
      || input.resume[0]?.status !== "resolved"
      || input.resume[0].interruptId !== command.interruptId
      || !isCanonicalUuid(command.inputId)
    ) {
      throw invalidRequest();
    }
    return {
      answer: readAnswer(input.resume[0].payload),
      command: "answer",
      commandId: command.inputId,
      input,
      interruptId: command.interruptId,
    };
  }

  if (input.resume !== undefined) throw invalidRequest();
  const selection = resolveSelection(registry, command.modelKey, command.reasoningEffort);

  if (command.command === "continue") {
    if (input.messages.length !== 0) throw invalidRequest();
    return {
      command: "continue",
      commandId: input.runId,
      input,
      modelKey: selection.modelKey,
      reasoningEffort: selection.reasoningEffort,
      sessionMode: "existing",
    };
  }

  if (input.messages.length !== 1) throw invalidRequest();
  const message = input.messages[0];
  if (
    message === undefined
    || message.role !== "user"
    || !isCanonicalUuid(message.id)
    || typeof message.content !== "string"
    || message.content.trim().length === 0
  ) {
    throw invalidRequest();
  }
  enforceMessageSize(message.content);

  return {
    command: "prompt",
    commandId: message.id,
    input,
    modelKey: selection.modelKey,
    reasoningEffort: selection.reasoningEffort,
    sessionMode: command.sessionMode,
    userMessage: { content: message.content, id: message.id, role: "user" },
  };
}

export async function readThreadId(request: Request): Promise<string> {
  const input = await readRunInput(request);
  if (!isCanonicalUuid(input.threadId)) throw invalidRequest();
  return input.threadId;
}

export function isChatThreadId(value: string): boolean {
  return isCanonicalUuid(value);
}

export function chatRunFingerprint(run: ValidatedChatRun): Buffer {
  const common = {
    command: run.command,
    runId: run.input.runId,
    threadId: run.input.threadId,
  };
  if (run.command === "answer") {
    return chatCommandFingerprint({
      ...common,
      answer: run.answer,
      inputId: run.commandId,
      interruptId: run.interruptId,
    });
  }
  if (run.command === "continue") {
    return chatCommandFingerprint({
      ...common,
      modelKey: run.modelKey,
      reasoningEffort: run.reasoningEffort,
    });
  }
  return chatCommandFingerprint({
    ...common,
    content: run.userMessage.content,
    inputId: run.userMessage.id,
    modelKey: run.modelKey,
    reasoningEffort: run.reasoningEffort,
    sessionMode: run.sessionMode,
  });
}

export function chatCommandFingerprint(value: unknown): Buffer {
  return createHash("sha256").update(canonicalJson(value)).digest();
}

function resolveSelection(
  registry: ModelRegistry,
  modelKey: string,
  requestedEffort: string,
): Readonly<{ modelKey: string; reasoningEffort: ReasoningEffort }> {
  const model = registry.models.find((candidate) => candidate.enabled && candidate.key === modelKey);
  if (model === undefined) throw new ChatRequestError("INVALID_MODEL", 400);
  const reasoningEffort = model.reasoningEfforts.find((effort) => effort === requestedEffort);
  if (reasoningEffort === undefined) throw new ChatRequestError("UNSUPPORTED_REASONING", 400);
  return { modelKey: model.key, reasoningEffort };
}

function readAnswer(value: unknown): ChatAnswer {
  if (!isChatAnswer(value)) throw invalidRequest();
  enforceMessageSize(value.text);
  enforceMessageSize(formatChatAnswer(value));
  return value;
}

function enforceMessageSize(content: string): void {
  if (Buffer.byteLength(content, "utf8") > MAX_CHAT_MESSAGE_BYTES) {
    throw new ChatRequestError("CHAT_INPUT_TOO_LARGE", 413);
  }
}

async function readRunInput(request: Request): Promise<RunAgentInput> {
  let body: unknown;
  try {
    body = await request.clone().json();
  } catch {
    throw invalidRequest();
  }
  const parsed = RunAgentInputSchema.safeParse(body);
  if (!parsed.success) throw invalidRequest();
  return parsed.data;
}

function isCanonicalRunEnvelope(input: RunAgentInput): boolean {
  return isCanonicalUuid(input.threadId)
    && isCanonicalUuid(input.runId)
    && input.parentRunId === undefined
    && (input.state === undefined || isEmptyRecord(input.state))
    && input.tools.length === 0
    && input.context.length === 0;
}

function isEmptyRecord(value: unknown): value is Record<string, never> {
  return isRecord(value) && Object.keys(value).length === 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => (
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    )).join(",")}}`;
  }
  return JSON.stringify(value);
}

function invalidRequest(): ChatRequestError {
  return new ChatRequestError("INVALID_CHAT_INPUT", 400);
}
