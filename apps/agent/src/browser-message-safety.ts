import { isSessionControlMessageId } from "./session-control-message.js";
import { createHash } from "node:crypto";
import { runFailureEvent } from "./run-failure.js";
import { readRunSelection } from "@thesistrace/contracts/agent-run-selection";

import {
  EventType,
  type BaseEvent,
  type Message,
} from "@ag-ui/core";

import {
  isResearchA2UIMessageId,
  projectResearchA2UIContent,
  RESEARCH_A2UI_ACTIVITY_TYPE,
} from "@thesistrace/contracts/research-a2ui";

import {
  DURABLE_TOOL_FAILURE,
  DURABLE_TOOL_OUTCOME_FIELD,
} from "./tool-outcome.js";
import {
  parseSafeToolResult,
  projectSafeToolResult,
} from "./safe-tool-result.js";
import { isCanonicalUuid } from "./uuid.js";

export { SAFE_TOOL_COMPLETED, SAFE_TOOL_FAILED } from "./safe-tool-result.js";

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

export const A2UI_FRAMEWORK_TOOL_NAMES = Object.freeze(new Set([
  "render_a2ui",
]));

class BrowserTranscriptError extends Error {
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
    if (isSessionControlMessageId(message.id)) continue;
    if (message.role === "user") {
      if (typeof message.content !== "string") throw new BrowserTranscriptError();
      projected.push({ content: message.content, id: message.id, role: "user" });
      continue;
    }
    if (message.role !== "assistant" || typeof message.content !== "string") {
      throw new BrowserTranscriptError();
    }

    // Mastra's content convenience field can hold only the final step's text.
    // Ordered text parts preserve the complete streamed Assistant response.
    const content = readDurableAssistantText(message.parts);
    const invocations = readDurableToolInvocations(message.parts).filter(
      ({ invocation }) => !A2UI_FRAMEWORK_TOOL_NAMES.has(invocation.toolName),
    );
    const assistant: Message = invocations.length === 0
      ? { content, id: message.id, role: "assistant" }
      : {
          content,
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
      const marker = parseSafeToolResult(message.content);
      const failed = message.error !== undefined || marker?.outcome === "failed";
      return {
        content: marker?.resource === undefined
          ? projectSafeToolResult(message.content, failed)
          : projectSafeToolResult({
              run_id: marker.resource.id,
              status: marker.resource.status,
            }, failed),
        id: safeToolResultMessageId(message.toolCallId),
        role: "tool",
        toolCallId: message.toolCallId,
      };
    }
    if (message.role === "activity") {
      if (
        message.activityType !== RESEARCH_A2UI_ACTIVITY_TYPE
        || !isResearchA2UIMessageId(message.id)
      ) {
        throw new BrowserTranscriptError();
      }
      const projected = projectResearchA2UIContent(message.content);
      return {
        activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
        content: projected.content,
        id: message.id,
        role: "activity",
      };
    }
    throw new BrowserTranscriptError();
  });
}

/**
 * CopilotKit represents the final text of a Tool-calling Assistant message as
 * a second message whose id is `<assistant-id>-agui-text`. Collapse only that
 * exact shape before comparing browser history with the durable projection.
 */
export function canonicalSubmittedBrowserMessages(
  messages: readonly Message[],
): readonly Message[] {
  const safe = safeBrowserMessages(messages);
  const canonical: Message[] = [];
  for (const message of safe) {
    const parentId = message.role === "assistant"
      ? splitAssistantTextParentId(message.id)
      : null;
    if (parentId === null) {
      canonical.push(message);
      continue;
    }

    const parentIndex = canonical.findIndex((candidate) => (
      candidate.role === "assistant" && candidate.id === parentId
    ));
    const parent = canonical[parentIndex];
    if (
      message.role !== "assistant"
      || parent?.role !== "assistant"
      || parent.toolCalls === undefined
      || parent.toolCalls.length === 0
      || message.toolCalls !== undefined
      || typeof message.content !== "string"
    ) {
      throw new BrowserTranscriptError();
    }

    const expectedToolCalls = new Set(parent.toolCalls.map((toolCall) => toolCall.id));
    const intervening = canonical.slice(parentIndex + 1);
    if (
      intervening.length !== expectedToolCalls.size
      || intervening.some((candidate) => (
        candidate.role !== "tool"
        || !expectedToolCalls.delete(candidate.toolCallId)
      ))
      || expectedToolCalls.size !== 0
    ) {
      throw new BrowserTranscriptError();
    }
    canonical[parentIndex] = {
      ...parent,
      content: `${parent.content ?? ""}${message.content}`,
    };
  }
  return canonical;
}

function splitAssistantTextParentId(messageId: string): string | null {
  const suffix = "-agui-text";
  return messageId.endsWith(suffix)
    ? messageId.slice(0, -suffix.length)
    : null;
}

/**
 * Stateful AG-UI event projector. TOOL_CALL_ARGS is replaced by one empty JSON
 * object so AG-UI clients can assemble a valid ToolCall without receiving the
 * real arguments. Raw Tool results are replaced with a terminal marker.
 */
export class BrowserEventProjector {
  private readonly openToolCalls = new Set<string>();
  private readonly openTextMessages = new Set<string>();
  private readonly passthroughToolCalls = new Set<string>();

  constructor(
    private readonly passthroughToolNames: ReadonlySet<string> = new Set(),
  ) {}

  project(event: BaseEvent, toolFailed = false): readonly BaseEvent[] {
    switch (event.type) {
      case EventType.RUN_STARTED:
        return [{
          runId: requiredString(event.runId),
          threadId: requiredString(event.threadId),
          type: EventType.RUN_STARTED,
          ...(readRunSelection(event.selection) === null ? {} : { selection: readRunSelection(event.selection) }),
        }];
      case EventType.RUN_FINISHED:
        return [{
          runId: requiredString(event.runId),
          threadId: requiredString(event.threadId),
          type: EventType.RUN_FINISHED,
        }];
      case EventType.RUN_ERROR:
        return [runFailureEvent(event.code)];
      case EventType.MESSAGES_SNAPSHOT:
        if (!Array.isArray(event.messages)) throw new BrowserTranscriptError();
        return [{
          messages: [...safeBrowserMessages(event.messages as Message[])],
          type: EventType.MESSAGES_SNAPSHOT,
        }];
      case EventType.TOOL_CALL_START:
        if (this.passthroughToolNames.has(requiredString(event.toolCallName))) {
          const toolCallId = requiredString(event.toolCallId);
          this.passthroughToolCalls.add(toolCallId);
          return [{
            ...(typeof event.parentMessageId !== "string"
              ? {}
              : { parentMessageId: event.parentMessageId }),
            toolCallId,
            toolCallName: event.toolCallName,
            type: EventType.TOOL_CALL_START,
          }];
        }
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
        if (this.passthroughToolCalls.has(requiredString(event.toolCallId))) {
          if (typeof event.delta !== "string") throw new BrowserTranscriptError();
          return [{
            delta: event.delta,
            toolCallId: event.toolCallId,
            type: EventType.TOOL_CALL_ARGS,
          }];
        }
        return [];
      case EventType.TOOL_CALL_CHUNK:
        if (
          typeof event.toolCallId === "string"
          && this.passthroughToolCalls.has(event.toolCallId)
        ) {
          return [{
            ...(typeof event.delta === "string" ? { delta: event.delta } : {}),
            toolCallId: event.toolCallId,
            ...(typeof event.toolCallName === "string"
              ? { toolCallName: event.toolCallName }
              : {}),
            type: EventType.TOOL_CALL_CHUNK,
          }];
        }
        return [];
      case EventType.TOOL_CALL_END: {
        const toolCallId = requiredString(event.toolCallId);
        if (this.passthroughToolCalls.has(toolCallId)) {
          return [{ toolCallId, type: EventType.TOOL_CALL_END }];
        }
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
        if (this.passthroughToolCalls.delete(event.toolCallId)) {
          return [{
            content: requiredString(event.content),
            messageId: requiredString(event.messageId),
            role: "tool",
            toolCallId: event.toolCallId,
            type: EventType.TOOL_CALL_RESULT,
          }];
        }
        return [{
          content: projectSafeToolResult(
            event.content,
            toolFailed || isStructuredToolError(event.content),
          ),
          messageId: safeToolResultMessageId(event.toolCallId),
          role: "tool",
          toolCallId: event.toolCallId,
          type: EventType.TOOL_CALL_RESULT,
        }];
      case EventType.CUSTOM: {
        if (event.name !== "session_recovery_changed" || !isRecord(event.value)
          || typeof event.value.runId !== "string" || !isCanonicalUuid(event.value.runId)) return [];
        return [{ type: EventType.CUSTOM, name: "session_recovery_changed", value: { runId: event.value.runId } }];
      }
      case EventType.TEXT_MESSAGE_START: {
        const messageId = safeAssistantMessageId(event.messageId);
        if (event.role !== "assistant" || this.openTextMessages.has(messageId)) {
          throw new BrowserTranscriptError();
        }
        this.openTextMessages.add(messageId);
        return [{ messageId, role: "assistant", type: EventType.TEXT_MESSAGE_START }];
      }
      case EventType.TEXT_MESSAGE_CONTENT: {
        const messageId = safeAssistantMessageId(event.messageId);
        if (!this.openTextMessages.has(messageId) || typeof event.delta !== "string") {
          throw new BrowserTranscriptError();
        }
        return [{ delta: event.delta, messageId, type: EventType.TEXT_MESSAGE_CONTENT }];
      }
      case EventType.TEXT_MESSAGE_END: {
        const messageId = safeAssistantMessageId(event.messageId);
        if (!this.openTextMessages.delete(messageId)) throw new BrowserTranscriptError();
        return [{ messageId, type: EventType.TEXT_MESSAGE_END }];
      }
      case EventType.TEXT_MESSAGE_CHUNK:
        if (
          event.role !== "assistant"
          || typeof event.delta !== "string"
        ) {
          throw new BrowserTranscriptError();
        }
        return [{
          delta: event.delta,
          messageId: safeAssistantMessageId(event.messageId),
          role: "assistant",
          type: EventType.TEXT_MESSAGE_CHUNK,
        }];
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

function readDurableAssistantText(parts: unknown): string {
  if (!Array.isArray(parts)) throw new BrowserTranscriptError();
  return parts.map((part: unknown) => {
    if (!isRecord(part) || part.type !== "text") return "";
    if (typeof part.text !== "string") throw new BrowserTranscriptError();
    return part.text;
  }).join("");
}

function readDurableToolInvocations(parts: unknown): ReadonlyArray<{
  invocation: SafeInvocation;
  terminal: string | null;
}> {
  if (!Array.isArray(parts)) throw new BrowserTranscriptError();
  const result: Array<{
    invocation: SafeInvocation;
    terminal: string | null;
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

function terminalMarker(invocation: DurableToolInvocation): string | null {
  if (
    invocation.isError === true
    || invocation.state === "output-error"
    || invocation.state === "output-denied"
    || nestedToolResultFailed(invocation.result)
  ) {
    return projectSafeToolResult(invocation.result, true);
  }
  return invocation.state === "result"
    ? projectSafeToolResult(invocation.result, false)
    : null;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function safeAssistantMessageId(value: unknown): string {
  if (typeof value !== "string") throw new BrowserTranscriptError();
  const parentId = splitAssistantTextParentId(value);
  if (
    !isCanonicalUuid(value)
    && (parentId === null || !isCanonicalUuid(parentId))
  ) {
    throw new BrowserTranscriptError();
  }
  return value;
}

function requiredString(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new BrowserTranscriptError();
  }
  return value;
}
