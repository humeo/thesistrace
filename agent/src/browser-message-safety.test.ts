import { EventType, type Message } from "@ag-ui/core";
import { convertMessages, type MastraDBMessage } from "@mastra/core/agent";
import { describe, expect, it } from "vitest";

import {
  BrowserEventProjector,
  projectDurableUiMessages,
  SAFE_TOOL_COMPLETED,
  SAFE_TOOL_FAILED,
  safeToolResultMessageId,
} from "./browser-message-safety.js";
import {
  DURABLE_TOOL_FAILURE,
  DURABLE_TOOL_OUTCOME_FIELD,
} from "./tool-outcome.js";

describe("browser message safety", () => {
  it("projects durable Tool history without arguments or results", () => {
    const messages = projectDurableUiMessages([{
      content: "",
      id: "00000000-0000-4000-8000-000000000001",
      parts: [{
        toolInvocation: {
          args: { formula: "secret input" },
          result: { rows: ["secret result"] },
          state: "result",
          toolCallId: "provider-call-1",
          toolName: "get_alpha_catalog",
        },
        type: "tool-invocation",
      }],
      role: "assistant",
    }]);

    expect(messages).toEqual([{
      content: "",
      id: "00000000-0000-4000-8000-000000000001",
      role: "assistant",
      toolCalls: [{
        function: { arguments: "{}", name: "get_alpha_catalog" },
        id: "provider-call-1",
        type: "function",
      }],
    }, {
      content: SAFE_TOOL_COMPLETED,
      id: safeToolResultMessageId("provider-call-1"),
      role: "tool",
      toolCallId: "provider-call-1",
    }]);
    expect(JSON.stringify(messages)).not.toContain("secret");
  });

  it("replaces live Tool payloads with an empty argument object and marker", () => {
    const projector = new BrowserEventProjector();
    expect(projector.project({
      parentMessageId: "00000000-0000-4000-8000-000000000001",
      toolCallId: "provider-call-1",
      toolCallName: "get_alpha_catalog",
      type: EventType.TOOL_CALL_START,
    })).toHaveLength(1);
    expect(projector.project({
      delta: '{"formula":"secret"}',
      toolCallId: "provider-call-1",
      type: EventType.TOOL_CALL_ARGS,
    })).toEqual([]);
    expect(projector.project({
      toolCallId: "provider-call-1",
      type: EventType.TOOL_CALL_END,
    })).toEqual([{
      delta: "{}",
      toolCallId: "provider-call-1",
      type: EventType.TOOL_CALL_ARGS,
    }, {
      toolCallId: "provider-call-1",
      type: EventType.TOOL_CALL_END,
    }]);

    expect(projector.project({
      content: "raw disconnect detail with result-canary",
      messageId: "raw-result-message-2",
      role: "tool",
      toolCallId: "provider-call-2",
      type: EventType.TOOL_CALL_RESULT,
    }, true)).toEqual([{
      content: SAFE_TOOL_FAILED,
      messageId: safeToolResultMessageId("provider-call-2"),
      role: "tool",
      toolCallId: "provider-call-2",
      type: EventType.TOOL_CALL_RESULT,
    }]);
    const result = projector.project({
      content: '{"rows":["secret"]}',
      messageId: "random-bridge-id",
      role: "tool",
      toolCallId: "provider-call-1",
      type: EventType.TOOL_CALL_RESULT,
    });
    expect(result).toEqual([{
      content: SAFE_TOOL_COMPLETED,
      messageId: safeToolResultMessageId("provider-call-1"),
      role: "tool",
      toolCallId: "provider-call-1",
      type: EventType.TOOL_CALL_RESULT,
    }]);
    expect(JSON.stringify(result)).not.toContain("secret");

    const structuredError = projector.project({
      content: JSON.stringify({
        content: [{
          text: "private retry guidance",
          type: "text",
        }],
        isError: true,
      }),
      messageId: "raw-result-message-3",
      role: "tool",
      toolCallId: "provider-call-3",
      type: EventType.TOOL_CALL_RESULT,
    });
    expect(structuredError).toEqual([{
      content: SAFE_TOOL_FAILED,
      messageId: safeToolResultMessageId("provider-call-3"),
      role: "tool",
      toolCallId: "provider-call-3",
      type: EventType.TOOL_CALL_RESULT,
    }]);
    expect(JSON.stringify(structuredError)).not.toContain("private retry guidance");
  });

  it("sanitizes reconnect snapshots and rejects unsupported roles", () => {
    const projector = new BrowserEventProjector();
    const messages: Message[] = [{
      content: "raw result",
      error: "raw error",
      id: "random-id",
      role: "tool",
      toolCallId: "provider-call-2",
    }];
    expect(projector.project({
      messages,
      type: EventType.MESSAGES_SNAPSHOT,
    })).toEqual([{
      messages: [{
        content: "Tool failed.",
        id: safeToolResultMessageId("provider-call-2"),
        role: "tool",
        toolCallId: "provider-call-2",
      }],
      type: EventType.MESSAGES_SNAPSHOT,
    }]);
    expect(() => projectDurableUiMessages([{
      content: "hidden",
      id: "system-id",
      parts: [],
      role: "system",
    }])).toThrow("BROWSER_TRANSCRIPT_PROJECTION_FAILED");
  });

  it("replays a persisted Mastra Tool failure without its arguments or error", () => {
    const persisted: MastraDBMessage[] = [{
      content: {
        format: 2,
        parts: [{
          toolInvocation: {
            args: { formula: "private-formula" },
            errorText: "private-tool-error",
            state: "output-error",
            toolCallId: "provider-call-3",
            toolName: "diagnose_alpha_formula",
          },
          type: "tool-invocation",
        }],
      },
      createdAt: new Date("2026-08-29T00:00:00.000Z"),
      id: "00000000-0000-4000-8000-000000000003",
      resourceId: "00000000-0000-4000-8000-000000000010",
      role: "assistant",
      threadId: "00000000-0000-4000-8000-000000000020",
    }];
    const durable = projectDurableUiMessages(
      convertMessages(persisted).to("AIV4.UI"),
    );
    const projector = new BrowserEventProjector();
    const reconnect = projector.project({
      messages: [...durable],
      type: EventType.MESSAGES_SNAPSHOT,
    });

    expect(reconnect).toEqual([{
      messages: [{
        content: "",
        id: "00000000-0000-4000-8000-000000000003",
        role: "assistant",
        toolCalls: [{
          function: {
            arguments: "{}",
            name: "diagnose_alpha_formula",
          },
          id: "provider-call-3",
          type: "function",
        }],
      }, {
        content: SAFE_TOOL_FAILED,
        id: safeToolResultMessageId("provider-call-3"),
        role: "tool",
        toolCallId: "provider-call-3",
      }],
      type: EventType.MESSAGES_SNAPSHOT,
    }]);
    expect(JSON.stringify(reconnect)).not.toContain("private-");
  });

  it("replays a resolved internal MCP failure as failed rather than completed", () => {
    const projected = projectDurableUiMessages([{
      content: "",
      id: "00000000-0000-4000-8000-000000000004",
      parts: [{
        toolInvocation: {
          args: {},
          result: {
            [DURABLE_TOOL_OUTCOME_FIELD]: DURABLE_TOOL_FAILURE,
            code: "private-transport-detail",
          },
          state: "result",
          toolCallId: "provider-call-4",
          toolName: "get_research_context",
        },
        type: "tool-invocation",
      }],
      role: "assistant",
    }]);

    expect(projected.at(-1)).toMatchObject({
      content: SAFE_TOOL_FAILED,
      role: "tool",
      toolCallId: "provider-call-4",
    });
    expect(JSON.stringify(projected)).not.toContain("private-transport-detail");
  });
});
