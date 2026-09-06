import { EventType, type BaseEvent } from "@ag-ui/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatTimelineProjector } from "./chat-timeline-projector.js";
import { SAFE_TOOL_COMPLETED, SAFE_TOOL_FAILED } from "./safe-tool-result.js";
import type { ResearchSessionRepository } from "./session-repository.js";

const THREAD_ID = "00000000-0000-4000-8000-000000000001";
const RUN_ID = "00000000-0000-4000-8000-000000000002";

afterEach(() => vi.useRealTimers());

describe("browser-safe chat timeline projection", () => {
  it("preserves the model response identity for durable recovery links", async () => {
    const persistAssistantMessage = vi.fn(async () => undefined);
    const projector = new ChatTimelineProjector({ persistAssistantMessage } as unknown as ResearchSessionRepository, THREAD_ID, RUN_ID);
    await projector.project(event({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: "response-original", delta: "Partial answer" }));
    await projector.project(event({ type: EventType.TEXT_MESSAGE_END, messageId: "response-original" }));
    expect(persistAssistantMessage).toHaveBeenLastCalledWith(THREAD_ID, RUN_ID, "response-original", "Partial answer");
  });

  it("keeps reused message IDs separate across tool boundaries", async () => {
    const rows = new Map<string, { kind: string; content: string }>();
    const projector = new ChatTimelineProjector({
      persistAssistantMessage: async (_thread: string, _run: string, id: string, content: string) => {
        rows.set(id, { kind: "text", content });
      },
      persistToolActivity: async (_thread: string, _run: string, id: string) => {
        rows.set(id, { kind: "tool", content: id });
      },
    } as unknown as ResearchSessionRepository, THREAD_ID, RUN_ID);
    for (const [index, text] of ["Checking.", "Read the context.", "Finished."].entries()) {
      await projector.project(event({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: "reused-agui-text", delta: text }));
      await projector.project(event({ type: EventType.TEXT_MESSAGE_END, messageId: "reused-agui-text" }));
      if (index < 2) {
        await projector.project(event({ type: EventType.TOOL_CALL_START, toolCallId: `call-${index}`, toolCallName: "get_research_context" }));
        await projector.project(event({ type: EventType.TOOL_CALL_RESULT, toolCallId: `call-${index}`, content: SAFE_TOOL_COMPLETED }));
      }
    }
    await projector.flush();
    expect([...rows.values()]).toEqual([
      { kind: "text", content: "Checking." }, { kind: "tool", content: "call-0" },
      { kind: "text", content: "Read the context." }, { kind: "tool", content: "call-1" },
      { kind: "text", content: "Finished." },
    ]);
  });
  it("coalesces assistant text, flushes at a Tool boundary, and stores no Tool arguments", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const persistAssistantMessage = vi.fn(async () => undefined);
    const persistToolActivity = vi.fn(async () => undefined);
    const projector = new ChatTimelineProjector({
      persistAssistantMessage,
      persistToolActivity,
    } as unknown as ResearchSessionRepository, THREAD_ID, RUN_ID);

    await projector.project(event({
      delta: "Partial answer",
      messageId: "assistant-1",
      type: EventType.TEXT_MESSAGE_CHUNK,
    }));
    expect(persistAssistantMessage).not.toHaveBeenCalled();

    await projector.project(event({
      parentMessageId: "assistant-1",
      toolCallId: "tool-1",
      toolCallName: "get_research_context",
      type: EventType.TOOL_CALL_START,
    }));
    expect(persistAssistantMessage).toHaveBeenCalledWith(
      THREAD_ID,
      RUN_ID,
      expect.any(String),
      "Partial answer",
    );
    expect(persistToolActivity).toHaveBeenCalledWith(
      THREAD_ID,
      RUN_ID,
      "tool-1",
      "get_research_context",
      "running",
    );
    expect(JSON.stringify(persistToolActivity.mock.calls)).not.toContain("private-argument");

    await projector.project(event({
      content: SAFE_TOOL_FAILED,
      messageId: "tool-message",
      role: "tool",
      toolCallId: "tool-1",
      type: EventType.TOOL_CALL_RESULT,
    }));
    expect(persistToolActivity).toHaveBeenLastCalledWith(
      THREAD_ID,
      RUN_ID,
      "tool-1",
      "get_research_context",
      "failed",
    );
    expect(JSON.stringify(persistToolActivity.mock.calls)).not.toContain(SAFE_TOOL_FAILED);

    await projector.project(event({
      parentMessageId: "assistant-1",
      toolCallId: "tool-2",
      toolCallName: "list_research_runs",
      type: EventType.TOOL_CALL_START,
    }));
    await projector.project(event({
      content: SAFE_TOOL_COMPLETED,
      messageId: "tool-message-2",
      role: "tool",
      toolCallId: "tool-2",
      type: EventType.TOOL_CALL_RESULT,
    }));
    expect(persistToolActivity).toHaveBeenLastCalledWith(
      THREAD_ID,
      RUN_ID,
      "tool-2",
      "list_research_runs",
      "complete",
    );
  });

  it("rejects unsafe Tool names and force-flushes text before terminal events", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const persistAssistantMessage = vi.fn(async () => undefined);
    const persistToolActivity = vi.fn(async () => undefined);
    const projector = new ChatTimelineProjector({
      persistAssistantMessage,
      persistToolActivity,
    } as unknown as ResearchSessionRepository, THREAD_ID, RUN_ID);

    await projector.project(event({
      toolCallId: "unsafe-tool",
      toolCallName: "unsafe\ntool",
      type: EventType.TOOL_CALL_START,
    }));
    await projector.project(event({
      delta: "Recoverable output",
      messageId: "assistant-2",
      type: EventType.TEXT_MESSAGE_CHUNK,
    }));
    await projector.project(event({ runId: RUN_ID, threadId: THREAD_ID, type: EventType.RUN_ERROR }));

    expect(persistToolActivity).not.toHaveBeenCalled();
    expect(persistAssistantMessage).toHaveBeenCalledWith(
      THREAD_ID,
      RUN_ID,
      expect.any(String),
      "Recoverable output",
    );
  });

  it("persists framed AG-UI text content when the message ends", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const persistAssistantMessage = vi.fn(async () => undefined);
    const projector = new ChatTimelineProjector({
      persistAssistantMessage,
      persistToolActivity: vi.fn(async () => undefined),
    } as unknown as ResearchSessionRepository, THREAD_ID, RUN_ID);

    await projector.project(event({
      messageId: "assistant-framed",
      role: "assistant",
      type: EventType.TEXT_MESSAGE_START,
    }));
    await projector.project(event({
      delta: "Answer after resume",
      messageId: "assistant-framed",
      type: EventType.TEXT_MESSAGE_CONTENT,
    }));
    expect(persistAssistantMessage).not.toHaveBeenCalled();

    await projector.project(event({
      messageId: "assistant-framed",
      type: EventType.TEXT_MESSAGE_END,
    }));
    expect(persistAssistantMessage).toHaveBeenCalledWith(
      THREAD_ID,
      RUN_ID,
      expect.any(String),
      "Answer after resume",
    );
  });
});

function event(value: Record<string, unknown>): BaseEvent {
  return value as unknown as BaseEvent;
}
