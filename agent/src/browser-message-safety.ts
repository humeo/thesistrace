import { createHash } from "node:crypto";

import {
  EventType,
  type BaseEvent,
  type Message,
} from "@ag-ui/core";

import {
  DURABLE_TOOL_FAILURE,
  DURABLE_TOOL_OUTCOME_FIELD,
} from "./tool-outcome.js";

export const SAFE_TOOL_COMPLETED = "Tool completed.";
export const SAFE_TOOL_FAILED = "Tool failed.";

type DurableUiMessage = Readonly<{
  content?: unknown;
  id?: unknown;
  parts?: unknown;
  role?: unknown;
}>;

type DurableToolInvocation = Readonly<{
  args?: unknown;
  errorText?: unknown;
  isError?: unknown;
  result?: unknown;
  state?: unknown;
  toolCallId?: unknown;
  toolName?: unknown;
}>;
type SafeInvocation = Readonly<{
  toolCallId: string;
  toolName: string;
}>;

export class BrowserTranscriptError extends Error {
  constructor() {
    super("BROWSER_TRANSCRIPT_PROJECTION_FAILED");
    this.name = "BrowserTranscriptError";
  }
}

/**
 * Convert Mastra's authoritative UI history into the only history shape that
 * may cross the browser boundary. Tool arguments and results deliberately do
 * not survive this projection.
 */
export function projectDurableUiMessages(
  messages: readonly DurableUiMessage[],
): readonly Message[] {
  const projected: Message[] = [];
  for (const message of messages) {
    if (typeof message.id !== "string") throw new BrowserTranscriptError();
    if (message.role === "user") {
      if (typeof message.content !== "string") throw new BrowserTranscriptError();
      projected.push({ content: message.content, id: message.id, role: "user" });
      continue;
    }
    if (message.role !== "assistant" || typeof message.content !== "string") {
      throw new BrowserTranscriptError();
    }

    const invocations = readDurableToolInvocations(message.parts);
    const assistant: Message = invocations.length === 0
      ? { content: message.content, id: message.id, role: "assistant" }
      : {
          content: message.content,
          id: message.id,
          role: "assistant",
          toolCalls: invocations.map(({ invocation }) => ({
            function: {
              arguments: "{}",
              name: invocation.toolName,
            },
            id: invocation.toolCallId,
            type: "function",
          })),
        };
    projected.push(assistant);

    for (const { invocation, terminal } of invocations) {
      if (terminal === null) continue;
      projected.push({
        content: terminal,
        id: safeToolResultMessageId(invocation.toolCallId),
        role: "tool",
        toolCallId: invocation.toolCallId,
      });
    }
  }
  return projected;
}

/** Sanitize an already AG-UI-shaped snapshot without trusting its payload. */
export function safeBrowserMessages(messages: readonly Message[]): readonly Message[] {
  return messages.map((message): Message => {
    if (message.role === "user") {
      if (typeof message.content !== "string") throw new BrowserTranscriptError();
      return { content: message.content, id: message.id, role: "user" };
    }
    if (message.role === "assistant") {
      const content = typeof message.content === "string" ? message.content : "";
      const toolCalls = message.toolCalls?.map((toolCall) => ({
        function: {
          arguments: "{}",
          name: toolCall.function.name,
        },
        id: toolCall.id,
        type: "function" as const,
      }));
      return toolCalls === undefined
        ? { content, id: message.id, role: "assistant" }
        : { content, id: message.id, role: "assistant", toolCalls };
    }
    if (message.role === "tool") {
      const failed = message.error !== undefined || message.content === SAFE_TOOL_FAILED;
      return {
        content: failed ? SAFE_TOOL_FAILED : SAFE_TOOL_COMPLETED,
        id: safeToolResultMessageId(message.toolCallId),
        role: "tool",
        toolCallId: message.toolCallId,
      };
    }
    throw new BrowserTranscriptError();
  });
}

/**
 * Stateful AG-UI event projector. TOOL_CALL_ARGS is replaced by one empty JSON
 * object so AG-UI clients can assemble a valid ToolCall without receiving the
 * real arguments. Raw Tool results are replaced with a terminal marker.
 */
export class BrowserEventProjector {
  private readonly openToolCalls = new Set<string>();

  project(event: BaseEvent, toolFailed = false): readonly BaseEvent[] {
    switch (event.type) {
      case EventType.RUN_STARTED:
        return [{
          runId: requiredString(event.runId),
          threadId: requiredString(event.threadId),
          type: EventType.RUN_STARTED,
        }];
      case EventType.RUN_FINISHED:
        return [{
          runId: requiredString(event.runId),
          threadId: requiredString(event.threadId),
          type: EventType.RUN_FINISHED,
        }];
      case EventType.RUN_ERROR:
        return [safeBrowserRunError()];
      case EventType.MESSAGES_SNAPSHOT:
        if (!Array.isArray(event.messages)) throw new BrowserTranscriptError();
        return [{
          messages: [...safeBrowserMessages(event.messages as Message[])],
          type: EventType.MESSAGES_SNAPSHOT,
        }];
      case EventType.TOOL_CALL_START:
        this.openToolCalls.add(requiredString(event.toolCallId));
        return [{
          ...(typeof event.parentMessageId !== "string"
            ? {}
            : { parentMessageId: event.parentMessageId }),
          toolCallId: requiredString(event.toolCallId),
          toolCallName: requiredString(event.toolCallName),
          type: EventType.TOOL_CALL_START,
        }];
      case EventType.TOOL_CALL_ARGS:
      case EventType.TOOL_CALL_CHUNK:
        return [];
      case EventType.TOOL_CALL_END: {
        const toolCallId = requiredString(event.toolCallId);
        const includeArguments = this.openToolCalls.delete(toolCallId);
        return [
          ...(includeArguments
            ? [{
                delta: "{}",
                toolCallId,
                type: EventType.TOOL_CALL_ARGS,
              } as BaseEvent]
            : []),
          {
            toolCallId,
            type: EventType.TOOL_CALL_END,
          },
        ];
      }
      case EventType.TOOL_CALL_RESULT:
        if (typeof event.toolCallId !== "string") throw new BrowserTranscriptError();
        return [{
          content: toolFailed || isStructuredToolError(event.content)
            ? SAFE_TOOL_FAILED
            : SAFE_TOOL_COMPLETED,
          messageId: safeToolResultMessageId(event.toolCallId),
          role: "tool",
          toolCallId: event.toolCallId,
          type: EventType.TOOL_CALL_RESULT,
        }];
      case EventType.TEXT_MESSAGE_START:
      case EventType.TEXT_MESSAGE_CONTENT:
      case EventType.TEXT_MESSAGE_END:
      case EventType.TEXT_MESSAGE_CHUNK:
        return [withoutRawEvent(event)];
      default:
        // State, reasoning, custom, activity, interrupt, and raw provider events
        // are not part of the Research Chat browser contract.
        return [];
    }
  }
}

function isStructuredToolError(content: unknown): boolean {
  if (typeof content !== "string") return false;
  try {
    const parsed: unknown = JSON.parse(content);
    return isRecord(parsed) && parsed.isError === true;
  } catch {
    return false;
  }
}

export function safeToolResultMessageId(toolCallId: string): string {
  const bytes = createHash("sha256")
    .update("thesistrace:browser-tool-result:")
    .update(toolCallId)
    .digest()
    .subarray(0, 16);
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x50;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function readDurableToolInvocations(parts: unknown): ReadonlyArray<{
  invocation: SafeInvocation;
  terminal: typeof SAFE_TOOL_COMPLETED | typeof SAFE_TOOL_FAILED | null;
}> {
  if (!Array.isArray(parts)) throw new BrowserTranscriptError();
  const result: Array<{
    invocation: SafeInvocation;
    terminal: typeof SAFE_TOOL_COMPLETED | typeof SAFE_TOOL_FAILED | null;
  }> = [];
  for (const part of parts) {
    if (!isRecord(part) || part.type !== "tool-invocation") continue;
    const invocation = part.toolInvocation;
    if (
      !isRecord(invocation)
      || typeof invocation.toolCallId !== "string"
      || invocation.toolCallId.length === 0
      || typeof invocation.toolName !== "string"
      || invocation.toolName.length === 0
    ) {
      throw new BrowserTranscriptError();
    }
    result.push({
      invocation: {
        toolCallId: invocation.toolCallId,
        toolName: invocation.toolName,
      },
      terminal: terminalMarker(invocation),
    });
  }
  return result;
}

function terminalMarker(
  invocation: DurableToolInvocation,
): typeof SAFE_TOOL_COMPLETED | typeof SAFE_TOOL_FAILED | null {
  if (
    invocation.isError === true
    || invocation.state === "output-error"
    || invocation.state === "output-denied"
    || nestedToolResultFailed(invocation.result)
  ) {
    return SAFE_TOOL_FAILED;
  }
  return invocation.state === "result" ? SAFE_TOOL_COMPLETED : null;
}

function nestedToolResultFailed(result: unknown): boolean {
  if (!isRecord(result)) return false;
  if (
    result.isError === true
    || result[DURABLE_TOOL_OUTCOME_FIELD] === DURABLE_TOOL_FAILURE
  ) return true;
  return result.type === "json"
    && isRecord(result.value)
    && (
      result.value.isError === true
      || result.value[DURABLE_TOOL_OUTCOME_FIELD] === DURABLE_TOOL_FAILURE
    );
}

function safeBrowserRunError(): BaseEvent {
  return {
    code: "AGENT_RUN_FAILED",
    message: "The Research Agent could not complete this run.",
    type: EventType.RUN_ERROR,
  };
}

function withoutRawEvent(event: BaseEvent): BaseEvent {
  const { rawEvent: _rawEvent, ...safe } = event;
  return safe as BaseEvent;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function requiredString(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new BrowserTranscriptError();
  }
  return value;
}
