import { EventType, type BaseEvent } from "@ag-ui/core";
import { describe, expect, it } from "vitest";

import {
  RESEARCH_A2UI_ACTIVITY_TYPE,
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_PROTOCOL_VERSION,
  safeResearchA2UIErrorContent,
} from "@thesistrace/contracts/research-a2ui";
import { ResearchA2UIEventProjector } from "./research-a2ui-events.js";

describe("ResearchA2UIEventProjector", () => {
  it("withholds progressive UI until the complete server Tool result confirms it", () => {
    const projector = new ResearchA2UIEventProjector();
    expect(projector.project(toolStart("render-call", "render_a2ui"))).toEqual({
      activities: [],
      events: [],
    });
    expect(projector.project({
      delta: '{"private":"model-authored"}',
      toolCallId: "render-call",
      type: EventType.TOOL_CALL_ARGS,
    })).toEqual({ activities: [], events: [] });

    expect(projector.project({
      activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
      content: readyContent(),
      messageId: "a2ui-surface-render-call",
      replace: true,
      type: EventType.ACTIVITY_SNAPSHOT,
    })).toEqual({ activities: [], events: [] });
    const projected = projector.project(toolResult("render-call", readyContent()));
    expect(projected.activities).toEqual([{
      content: readyContent(),
      lifecycle: "ready",
      messageId: "a2ui-surface-render-call",
      ownerMessageId: "assistant-message",
      sequence: 1,
    }]);
    expect(projected.events).toEqual([{
      activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
      content: readyContent(),
      messageId: "a2ui-surface-render-call",
      replace: true,
      type: EventType.ACTIVITY_SNAPSHOT,
    }]);
    expect(JSON.stringify(projected)).not.toContain("model-authored");

    expect(projector.project({
      content: JSON.stringify(readyContent()),
      messageId: "raw-tool-result",
      role: "tool",
      toolCallId: "render-call",
      type: EventType.TOOL_CALL_RESULT,
    })).toEqual({ activities: [], events: [] });
  });

  it("rejects an early renderable snapshot when the complete Tool input failed", () => {
    const invalid = new ResearchA2UIEventProjector();
    invalid.project(toolStart("invalid-call", "render_a2ui"));
    expect(invalid.project({
      activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
      content: readyContent(),
      messageId: "a2ui-surface-invalid-call",
      replace: true,
      type: EventType.ACTIVITY_SNAPSHOT,
    })).toEqual({ activities: [], events: [] });
    expect(invalid.project(toolResult("invalid-call", {
      error: "Strict input validation rejected unexpected top-level fields",
    }))).toEqual(safeErrorBatch("invalid-call"));
    expect(invalid.project({
      runId: "00000000-0000-4000-8000-000000000002",
      threadId: "00000000-0000-4000-8000-000000000003",
      type: EventType.RUN_FINISHED,
    }).activities).toEqual([]);
  });

  it("turns delta, loading, and missing Tool outcomes into a terminal safe error", () => {
    const delta = new ResearchA2UIEventProjector();
    delta.project(toolStart("delta-call", "render_a2ui"));
    expect(delta.project({
      activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
      delta: '{"partial":true}',
      messageId: "a2ui-surface-delta-call",
      type: EventType.ACTIVITY_DELTA,
    })).toEqual({ activities: [], events: [] });
    expect(delta.project(toolResult("delta-call", { status: "rendered" })))
      .toEqual(safeErrorBatch("delta-call"));

    const incomplete = new ResearchA2UIEventProjector();
    incomplete.project(toolStart("loading-call", "render_a2ui"));
    expect(incomplete.project({
      activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
      content: { debugExposure: "hidden", status: "building" },
      messageId: "a2ui-surface-loading-call",
      replace: true,
      type: EventType.ACTIVITY_SNAPSHOT,
    })).toEqual({ activities: [], events: [] });
    const terminal = incomplete.project({
      runId: "00000000-0000-4000-8000-000000000002",
      threadId: "00000000-0000-4000-8000-000000000003",
      type: EventType.RUN_FINISHED,
    });
    expect(terminal.activities).toEqual([{
      content: safeResearchA2UIErrorContent(),
      lifecycle: "error",
      messageId: "a2ui-surface-loading-call",
      ownerMessageId: "assistant-message",
      sequence: 1,
    }]);
    expect(terminal.events).toHaveLength(2);
    expect(terminal.events[0]).toMatchObject({
      content: safeResearchA2UIErrorContent(),
      type: EventType.ACTIVITY_SNAPSHOT,
    });
    expect(terminal.events[1]?.type).toBe(EventType.RUN_FINISHED);
  });

  it("assigns deterministic sequence in confirmed emission order for one owner", () => {
    const projector = new ResearchA2UIEventProjector();
    projector.project(toolStart("z-call", "render_a2ui"));
    projector.project(toolStart("a-call", "render_a2ui"));
    const first = projector.project(toolResult("z-call", readyContent()));
    const second = projector.project(toolResult("a-call", readyContent()));
    expect([...first.activities, ...second.activities].map((activity) => ({
      id: activity.messageId,
      sequence: activity.sequence,
    }))).toEqual([
      { id: "a2ui-surface-z-call", sequence: 1 },
      { id: "a2ui-surface-a-call", sequence: 2 },
    ]);
  });

  it("does not forward unknown Activities and leaves ordinary MCP lifecycle intact", () => {
    const projector = new ResearchA2UIEventProjector();
    const ordinary = toolStart("mcp-call", "get_research_context");
    expect(projector.project(ordinary)).toEqual({ activities: [], events: [ordinary] });
    expect(projector.project({
      activityType: "unregistered-activity",
      content: { html: "<script>alert(1)</script>" },
      messageId: "unsafe-activity",
      replace: true,
      type: EventType.ACTIVITY_SNAPSHOT,
    })).toEqual({ activities: [], events: [] });
    expect(projector.project({
      activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
      content: readyContent(),
      messageId: "a2ui-surface-unowned-call",
      replace: true,
      type: EventType.ACTIVITY_SNAPSHOT,
    })).toEqual({ activities: [], events: [] });
  });
});

function toolStart(toolCallId: string, toolCallName: string): BaseEvent {
  return {
    parentMessageId: "assistant-message",
    toolCallId,
    toolCallName,
    type: EventType.TOOL_CALL_START,
  };
}

function toolResult(toolCallId: string, content: unknown): BaseEvent {
  return {
    content: JSON.stringify(content),
    messageId: `result-${toolCallId}`,
    role: "tool",
    toolCallId,
    type: EventType.TOOL_CALL_RESULT,
  };
}

function readyContent(): Record<string, unknown> {
  return {
    a2ui_operations: [
      {
        createSurface: {
          catalogId: RESEARCH_A2UI_CATALOG_ID,
          surfaceId: "research-result",
        },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      },
      {
        updateComponents: {
          components: [{
            component: "Text",
            id: "root",
            text: "Authoritative result available",
          }],
          surfaceId: "research-result",
        },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      },
    ],
  };
}

function safeErrorBatch(callId: string) {
  const messageId = `a2ui-surface-${callId}`;
  return {
    activities: [{
      content: safeResearchA2UIErrorContent(),
      lifecycle: "error",
      messageId,
      ownerMessageId: "assistant-message",
      sequence: 1,
    }],
    events: [{
      activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
      content: safeResearchA2UIErrorContent(),
      messageId,
      replace: true,
      type: EventType.ACTIVITY_SNAPSHOT,
    }],
  };
}
