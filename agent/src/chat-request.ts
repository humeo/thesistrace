import { createHash } from "node:crypto";

import { RunAgentInputSchema, type RunAgentInput } from "@ag-ui/core";
import { z } from "zod";

import {
  canonicalSubmittedBrowserMessages,
  splitAssistantTextParentId,
} from "./browser-message-safety.js";
import {
  parseSafeToolResult,
} from "./safe-tool-result.js";
import type { ModelRegistry, ReasoningEffort } from "./model-registry.js";

export const MAX_CHAT_MESSAGE_BYTES = 16 * 1024;
const MAX_TRANSCRIPT_MESSAGES = 256;
const MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024;
const MAX_ASSISTANT_MESSAGE_BYTES = 256 * 1024;
const MAX_TOOL_CALLS_PER_MESSAGE = 32;
const MAX_TOOL_CALL_ID_BYTES = 512;
const TOOL_NAME_PATTERN = /^[A-Za-z0-9_.:-]{1,128}$/;
const uuidSchema = z.uuid();
const selectionSchema = z.object({
  modelKey: z.string(),
  reasoningEffort: z.enum(["none", "minimal", "low", "medium", "high", "xhigh"]),
}).strict();

export type ValidatedChatRun = Readonly<{
  input: RunAgentInput;
  latestUserMessage: Readonly<{ content: string; id: string; role: "user" }>;
  modelKey: string;
  reasoningEffort: ReasoningEffort;
}>;

export class ChatRequestError extends Error {
  constructor(
    readonly code: "CHAT_MESSAGE_TOO_LARGE" | "INVALID_CHAT_REQUEST",
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
  let body: unknown;
  try {
    body = await request.clone().json();
  } catch {
    throw invalidRequest();
  }
  const parsed = RunAgentInputSchema.safeParse(body);
  if (!parsed.success) throw invalidRequest();
  const input = parsed.data;
  if (
    !uuidSchema.safeParse(input.threadId).success
    || !uuidSchema.safeParse(input.runId).success
    || input.parentRunId !== undefined
    || input.resume !== undefined
    || !isEmptyRecord(input.state)
    || input.messages.length < 1
    || input.messages.length > MAX_TRANSCRIPT_MESSAGES
    || input.tools.length !== 0
    || input.context.length !== 0
  ) {
    throw invalidRequest();
  }

  const forwardedProps = input.forwardedProps;
  if (!isRecord(forwardedProps) || !hasExactKeys(forwardedProps, ["thesistrace"])) {
    throw invalidRequest();
  }
  const selection = selectionSchema.safeParse(forwardedProps.thesistrace);
  if (!selection.success) throw invalidRequest();
  const model = registry.models.find(
    (candidate) => candidate.enabled && candidate.key === selection.data.modelKey,
  );
  if (
    model === undefined
    || !model.reasoningEfforts.includes(selection.data.reasoningEffort)
  ) {
    throw invalidRequest();
  }

  validateBrowserTranscript(input.messages);
  const latest = input.messages.at(-1);
  if (
    latest === undefined
    || latest.role !== "user"
    || typeof latest.content !== "string"
    || latest.content.trim().length === 0
  ) {
    throw invalidRequest();
  }
  if (Buffer.byteLength(latest.content, "utf8") > MAX_CHAT_MESSAGE_BYTES) {
    throw new ChatRequestError("CHAT_MESSAGE_TOO_LARGE", 413);
  }

  return {
    input,
    latestUserMessage: {
      content: latest.content,
      id: latest.id,
      role: "user",
    },
    modelKey: model.key,
    reasoningEffort: selection.data.reasoningEffort,
  };
}

export async function readThreadId(request: Request): Promise<string> {
  let body: unknown;
  try {
    body = await request.clone().json();
  } catch {
    throw invalidRequest();
  }
  const parsed = RunAgentInputSchema.safeParse(body);
  if (!parsed.success || !uuidSchema.safeParse(parsed.data.threadId).success) {
    throw invalidRequest();
  }
  return parsed.data.threadId;
}

export function isChatThreadId(value: string): boolean {
  return uuidSchema.safeParse(value).success;
}

export function chatRunFingerprint(input: RunAgentInput): Buffer {
  const forwarded = isRecord(input.forwardedProps)
    && isRecord(input.forwardedProps.thesistrace)
    ? input.forwardedProps.thesistrace
    : {};
  return createHash("sha256").update(JSON.stringify({
    messages: input.messages.map(fingerprintMessage),
    modelKey: typeof forwarded.modelKey === "string" ? forwarded.modelKey : null,
    reasoningEffort: typeof forwarded.reasoningEffort === "string"
      ? forwarded.reasoningEffort
      : null,
    runId: input.runId,
    threadId: input.threadId,
  })).digest();
}

function validateBrowserTranscript(messages: RunAgentInput["messages"]): void {
  const openToolCalls = new Set<string>();
  const completedToolCalls = new Set<string>();
  const messageIds = new Set<string>();
  let transcriptBytes = 0;

  for (const message of messages) {
    const splitTextParentId = message.role === "assistant"
      ? splitAssistantTextParentId(message.id)
      : null;
    if (
      (
        !uuidSchema.safeParse(message.id).success
        && (
          splitTextParentId === null
          || !uuidSchema.safeParse(splitTextParentId).success
        )
      )
      || messageIds.has(message.id)
      || ("name" in message && message.name !== undefined)
      || ("encryptedValue" in message && message.encryptedValue !== undefined)
    ) {
      throw invalidRequest();
    }
    messageIds.add(message.id);
    if (message.role === "user") {
      if (typeof message.content !== "string") throw invalidRequest();
      transcriptBytes += Buffer.byteLength(message.content, "utf8");
      continue;
    }
    if (message.role === "assistant") {
      if (message.content !== undefined && typeof message.content !== "string") {
        throw invalidRequest();
      }
      const content = message.content ?? "";
      const contentBytes = Buffer.byteLength(content, "utf8");
      if (contentBytes > MAX_ASSISTANT_MESSAGE_BYTES) throw invalidRequest();
      transcriptBytes += contentBytes;
      if (message.toolCalls === undefined) continue;
      if (
        message.toolCalls.length < 1
        || message.toolCalls.length > MAX_TOOL_CALLS_PER_MESSAGE
      ) {
        throw invalidRequest();
      }
      for (const toolCall of message.toolCalls) {
        if (
          toolCall.type !== "function"
          || toolCall.encryptedValue !== undefined
          || toolCall.function.arguments !== "{}"
          || !TOOL_NAME_PATTERN.test(toolCall.function.name)
          || Buffer.byteLength(toolCall.id, "utf8") < 1
          || Buffer.byteLength(toolCall.id, "utf8") > MAX_TOOL_CALL_ID_BYTES
          || openToolCalls.has(toolCall.id)
        ) {
          throw invalidRequest();
        }
        openToolCalls.add(toolCall.id);
      }
      continue;
    }
    if (message.role === "tool") {
      if (
        parseSafeToolResult(message.content) === null
        || message.error !== undefined
        || !openToolCalls.has(message.toolCallId)
        || completedToolCalls.has(message.toolCallId)
      ) {
        throw invalidRequest();
      }
      completedToolCalls.add(message.toolCallId);
      transcriptBytes += Buffer.byteLength(message.content, "utf8");
      continue;
    }
    throw invalidRequest();
  }

  if (transcriptBytes > MAX_TRANSCRIPT_BYTES) throw invalidRequest();
  try {
    canonicalSubmittedBrowserMessages(messages);
  } catch {
    throw invalidRequest();
  }
}

function fingerprintMessage(message: RunAgentInput["messages"][number]): unknown {
  if (message.role === "assistant") {
    return {
      content: message.content ?? "",
      id: message.id,
      role: message.role,
      toolCalls: message.toolCalls?.map((toolCall) => ({
        arguments: toolCall.function.arguments,
        id: toolCall.id,
        name: toolCall.function.name,
      })) ?? null,
    };
  }
  if (message.role === "tool") {
    return {
      content: message.content,
      id: message.id,
      role: message.role,
      toolCallId: message.toolCallId,
    };
  }
  return {
    content: message.content,
    id: message.id,
    role: message.role,
  };
}

function invalidRequest(): ChatRequestError {
  return new ChatRequestError("INVALID_CHAT_REQUEST", 400);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isEmptyRecord(value: unknown): boolean {
  return isRecord(value) && Object.keys(value).length === 0;
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length
    && [...keys].sort().every((key, index) => actual[index] === key);
}
