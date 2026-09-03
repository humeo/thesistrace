import { EventType, type BaseEvent } from "@ag-ui/core";

import { parseSafeToolResult } from "./safe-tool-result.js";
import type { ResearchSessionRepository } from "./session-repository.js";

const FLUSH_INTERVAL_MS = 75;
const FLUSH_BYTES = 512;
const SAFE_TOOL_NAME = /^[A-Za-z0-9_.:-]{1,128}$/;

type AssistantBuffer = {
  content: string;
  lastFlushAt: number;
  persistedBytes: number;
};

/**
 * Produces the browser-safe timeline projection while an AG-UI stream runs.
 * Tool arguments, model reasoning, raw events, and provider payloads never
 * enter this boundary.
 */
export class ChatTimelineProjector {
  private readonly assistants = new Map<string, AssistantBuffer>();
  private readonly tools = new Map<string, string>();

  constructor(
    private readonly repository: ResearchSessionRepository,
    private readonly threadId: string,
    private readonly runId: string,
  ) {}

  async project(event: BaseEvent): Promise<void> {
    if (
      event.type === EventType.TEXT_MESSAGE_CHUNK
      || event.type === EventType.TEXT_MESSAGE_CONTENT
    ) {
      if (typeof event.messageId !== "string" || typeof event.delta !== "string") return;
      const buffer = this.assistants.get(event.messageId) ?? {
        content: "",
        lastFlushAt: 0,
        persistedBytes: 0,
      };
      buffer.content += event.delta;
      this.assistants.set(event.messageId, buffer);
      const bytes = Buffer.byteLength(buffer.content, "utf8");
      if (
        bytes - buffer.persistedBytes >= FLUSH_BYTES
        || Date.now() - buffer.lastFlushAt >= FLUSH_INTERVAL_MS
      ) {
        await this.flushAssistant(event.messageId, buffer);
      }
      return;
    }

    if (event.type === EventType.TEXT_MESSAGE_END) {
      if (typeof event.messageId !== "string") return;
      const buffer = this.assistants.get(event.messageId);
      if (buffer !== undefined) await this.flushAssistant(event.messageId, buffer);
      return;
    }

    if (event.type === EventType.TOOL_CALL_START) {
      await this.flushAssistants();
      if (
        typeof event.toolCallId !== "string"
        || typeof event.toolCallName !== "string"
        || !SAFE_TOOL_NAME.test(event.toolCallName)
      ) {
        return;
      }
      this.tools.set(event.toolCallId, event.toolCallName);
      await this.repository.persistToolActivity(
        this.threadId,
        this.runId,
        event.toolCallId,
        event.toolCallName,
        "running",
      );
      return;
    }

    if (event.type === EventType.TOOL_CALL_RESULT) {
      const name = typeof event.toolCallId === "string"
        ? this.tools.get(event.toolCallId)
        : undefined;
      if (name !== undefined && typeof event.toolCallId === "string") {
        const result = parseSafeToolResult(event.content);
        await this.repository.persistToolActivity(
          this.threadId,
          this.runId,
          event.toolCallId,
          name,
          result?.outcome === "failed" ? "failed" : "complete",
        );
        this.tools.delete(event.toolCallId);
      }
      return;
    }

    if (
      event.type === EventType.RUN_FINISHED
      || event.type === EventType.RUN_ERROR
      || event.type === EventType.MESSAGES_SNAPSHOT
    ) {
      await this.flushAssistants();
    }
  }

  async flush(): Promise<void> {
    await this.flushAssistants();
  }

  private async flushAssistants(): Promise<void> {
    for (const [messageId, buffer] of this.assistants) {
      await this.flushAssistant(messageId, buffer);
    }
  }

  private async flushAssistant(messageId: string, buffer: AssistantBuffer): Promise<void> {
    if (buffer.content.length === 0) return;
    await this.repository.persistAssistantMessage(
      this.threadId,
      this.runId,
      messageId,
      buffer.content,
    );
    buffer.lastFlushAt = Date.now();
    buffer.persistedBytes = Buffer.byteLength(buffer.content, "utf8");
  }
}
