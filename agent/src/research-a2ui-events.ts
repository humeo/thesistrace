import { EventType, type BaseEvent } from "@ag-ui/core";

import {
  isResearchA2UIMessageId,
  projectResearchA2UIContent,
  safeResearchA2UIErrorContent,
  RESEARCH_A2UI_ACTIVITY_TYPE,
} from "../../contracts/research-a2ui.mjs";
import { A2UI_FRAMEWORK_TOOL_NAMES } from "./browser-message-safety.js";

export type PersistableA2UIActivity = Readonly<{
  content: Record<string, unknown>;
  lifecycle: "error" | "loading" | "ready";
  messageId: string;
  ownerMessageId: string;
  sequence: number;
}>;

export type A2UIProjectionBatch = Readonly<{
  activities: readonly PersistableA2UIActivity[];
  events: readonly BaseEvent[];
}>;

/**
 * Final browser boundary after CopilotKit's A2UI middleware. Framework Tool
 * payloads stay private; only validated activity snapshots cross this seam.
 */
export class ResearchA2UIEventProjector {
  private readonly frameworkCalls = new Map<string, Readonly<{
    ownerMessageId: string | null;
    terminal: boolean;
  }>>();
  private nextSequence = 1;

  project(event: BaseEvent): A2UIProjectionBatch {
    if (event.type === EventType.TOOL_CALL_START) {
      if (typeof event.toolCallName !== "string" || typeof event.toolCallId !== "string") {
        return empty();
      }
      if (!A2UI_FRAMEWORK_TOOL_NAMES.has(event.toolCallName)) {
        return unchanged(event);
      }
      this.frameworkCalls.set(event.toolCallId, {
        ownerMessageId: typeof event.parentMessageId === "string"
          && this.isOwnerMessageId(event.parentMessageId)
          ? event.parentMessageId
          : null,
        terminal: false,
      });
      return empty();
    }
    if (
      event.type === EventType.TOOL_CALL_ARGS
      || event.type === EventType.TOOL_CALL_CHUNK
      || event.type === EventType.TOOL_CALL_END
      || event.type === EventType.TOOL_CALL_RESULT
    ) {
      const toolCallId = typeof event.toolCallId === "string" ? event.toolCallId : null;
      if (toolCallId !== null && this.frameworkCalls.has(toolCallId)) {
        if (event.type === EventType.TOOL_CALL_RESULT) {
          return this.completeTool(toolCallId, event.content);
        }
        return empty();
      }
      return unchanged(event);
    }
    if (
      event.type === EventType.ACTIVITY_DELTA
      || event.type === EventType.ACTIVITY_SNAPSHOT
    ) {
      // The pinned middleware derives progressive snapshots from partial Tool
      // arguments before Mastra validates the complete input. They are never
      // an authority to persist or render. Only the correlated server Tool
      // result below can confirm the strict input and product contract.
      return empty();
    }
    if (event.type === EventType.RUN_ERROR || event.type === EventType.RUN_FINISHED) {
      const terminal: PersistableA2UIActivity[] = [];
      for (const [toolCallId, call] of this.frameworkCalls) {
        if (call.terminal) continue;
        terminal.push(...this.completeTool(toolCallId, undefined).activities);
      }
      this.frameworkCalls.clear();
      return {
        activities: terminal,
        events: [...terminal.map(activitySnapshot), event],
      };
    }
    return unchanged(event);
  }

  private isOwnerMessageId(value: string): boolean {
    return value.length > 0 && value.length <= 220 && !/[\u0000-\u001f\u007f]/.test(value);
  }

  private completeTool(toolCallId: string, result: unknown): A2UIProjectionBatch {
    const call = this.frameworkCalls.get(toolCallId);
    if (call === undefined || call.terminal) return empty();
    this.frameworkCalls.set(toolCallId, { ...call, terminal: true });
    const messageId = `a2ui-surface-${toolCallId}`;
    if (!isResearchA2UIMessageId(messageId) || call.ownerMessageId === null) return empty();
    const projected = projectResearchA2UIContent(parseToolResult(result));
    const confirmed = projected.valid && projected.kind === "ready";
    const activity: PersistableA2UIActivity = {
      content: confirmed ? projected.content : safeResearchA2UIErrorContent(),
      lifecycle: confirmed ? "ready" : "error",
      messageId,
      ownerMessageId: call.ownerMessageId,
      sequence: this.nextSequence,
    };
    this.nextSequence += 1;
    return { activities: [activity], events: [activitySnapshot(activity)] };
  }
}

function parseToolResult(result: unknown): unknown {
  if (typeof result !== "string") return undefined;
  try {
    return JSON.parse(result);
  } catch {
    return undefined;
  }
}

function activitySnapshot(activity: PersistableA2UIActivity): BaseEvent {
  return {
    activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
    content: activity.content,
    messageId: activity.messageId,
    replace: true,
    type: EventType.ACTIVITY_SNAPSHOT,
  };
}

function unchanged(event: BaseEvent): A2UIProjectionBatch {
  return { activities: [], events: [event] };
}

function empty(): A2UIProjectionBatch {
  return { activities: [], events: [] };
}
