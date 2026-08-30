import { EventType, type Message } from "@ag-ui/core";
import { convertMessages, type MastraDBMessage } from "@mastra/core/agent";
import { describe, expect, it } from "vitest";

import {
  BrowserEventProjector,
  canonicalSubmittedBrowserMessages,
  projectDurableUiMessages,
  SAFE_TOOL_COMPLETED,
  SAFE_TOOL_FAILED,
  safeToolResultMessageId,
} from "./browser-message-safety.js";
import { parseSafeToolResult } from "./safe-tool-result.js";
import {
  DURABLE_TOOL_FAILURE,
  DURABLE_TOOL_OUTCOME_FIELD,
} from "./tool-outcome.js";

describe("browser message safety", () => {
  it("canonicalizes only CopilotKit's exact split Assistant text shape", () => {
    const assistantId = "00000000-0000-4000-8000-000000000001";
    expect(canonicalSubmittedBrowserMessages([{
      id: assistantId,
      role: "assistant",
      toolCalls: [{
        function: { arguments: "{}", name: "submit_research_run" },
        id: "provider-call-1",
        type: "function",
      }],
    }, {
      content: SAFE_TOOL_COMPLETED,
      id: safeToolResultMessageId("provider-call-1"),
      role: "tool",
      toolCallId: "provider-call-1",
    }, {
      content: "Core Worker continues independently.",
      id: `${assistantId}-agui-text`,
      role: "assistant",
    }])).toEqual([{
      content: "Core Worker continues independently.",
      id: assistantId,
      role: "assistant",
      toolCalls: [{
        function: { arguments: "{}", name: "submit_research_run" },
        id: "provider-call-1",
        type: "function",
      }],
    }, {
      content: SAFE_TOOL_COMPLETED,
      id: safeToolResultMessageId("provider-call-1"),
      role: "tool",
      toolCallId: "provider-call-1",
    }]);

    expect(() => canonicalSubmittedBrowserMessages([{
      content: "orphan",
      id: `${assistantId}-agui-text`,
      role: "assistant",
    }])).toThrow("BROWSER_TRANSCRIPT_PROJECTION_FAILED");
  });

  it("preserves Assistant text emitted before a Tool when joining its continuation", () => {
    const assistantId = "00000000-0000-4000-8000-000000000011";
    const messages = canonicalSubmittedBrowserMessages([{
      content: "I will inspect the current context. ",
      id: assistantId,
      role: "assistant",
      toolCalls: [{
        function: { arguments: "{}", name: "get_research_context" },
        id: "provider-call-before-text",
        type: "function",
      }],
    }, {
      content: SAFE_TOOL_COMPLETED,
      id: safeToolResultMessageId("provider-call-before-text"),
      role: "tool",
      toolCallId: "provider-call-before-text",
    }, {
      content: "The context is now available.",
      id: `${assistantId}-agui-text`,
      role: "assistant",
    }]);

    expect(messages[0]).toMatchObject({
      content: "I will inspect the current context. The context is now available.",
      id: assistantId,
      role: "assistant",
    });
  });

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

  it("allowlists Assistant text event fields and rejects unsafe text roles or ids", () => {
    const projector = new BrowserEventProjector();
    const messageId = "00000000-0000-4000-8000-000000000021";
    expect(projector.project({
      messageId,
      name: "provider-name",
      providerSecret: "must-not-cross",
      rawEvent: { private: true },
      role: "assistant",
      timestamp: 42,
      type: EventType.TEXT_MESSAGE_START,
    })).toEqual([{
      messageId,
      role: "assistant",
      type: EventType.TEXT_MESSAGE_START,
    }]);
    expect(projector.project({
      delta: "Safe text",
      messageId,
      providerSecret: "must-not-cross",
      type: EventType.TEXT_MESSAGE_CONTENT,
    })).toEqual([{
      delta: "Safe text",
      messageId,
      type: EventType.TEXT_MESSAGE_CONTENT,
    }]);
    expect(projector.project({
      messageId,
      providerSecret: "must-not-cross",
      type: EventType.TEXT_MESSAGE_END,
    })).toEqual([{
      messageId,
      type: EventType.TEXT_MESSAGE_END,
    }]);

    expect(() => projector.project({
      messageId: "00000000-0000-4000-8000-000000000022",
      role: "system",
      type: EventType.TEXT_MESSAGE_START,
    })).toThrow("BROWSER_TRANSCRIPT_PROJECTION_FAILED");
    expect(() => projector.project({
      delta: "unsafe",
      messageId: "provider-message-id",
      role: "assistant",
      type: EventType.TEXT_MESSAGE_CHUNK,
    })).toThrow("BROWSER_TRANSCRIPT_PROJECTION_FAILED");
  });

  it("preserves only a validated ResearchRun identity and status across live and durable replay", () => {
    const projector = new BrowserEventProjector();
    const live = projector.project({
      content: JSON.stringify({
        formula: "private-formula",
        replayed: false,
        run_id: "run_0123456789abcdef0123",
        status: "queued",
      }),
      messageId: "raw-result-message",
      role: "tool",
      toolCallId: "submit-call",
      type: EventType.TOOL_CALL_RESULT,
    });
    const liveResult = live[0];
    expect(liveResult?.type).toBe(EventType.TOOL_CALL_RESULT);
    expect(parseSafeToolResult(
      liveResult?.type === EventType.TOOL_CALL_RESULT ? liveResult.content : null,
    )).toEqual({
      outcome: "completed",
      resource: {
        id: "run_0123456789abcdef0123",
        kind: "research_run",
        status: "queued",
      },
    });
    expect(JSON.stringify(live)).not.toMatch(/private-formula|replayed/);

    const durable = projectDurableUiMessages([{
      content: "",
      id: "00000000-0000-4000-8000-000000000009",
      parts: [{
        toolInvocation: {
          args: { request_id: "private-request-id" },
          result: {
            private_worker: "private-worker",
            run_id: "run_0123456789abcdef0123",
            status: "succeeded",
          },
          state: "result",
          toolCallId: "detail-call",
          toolName: "get_research_run",
        },
        type: "tool-invocation",
      }],
      role: "assistant",
    }]);
    const toolMessage = durable.find((message) => message.role === "tool");
    expect(parseSafeToolResult(toolMessage?.content)).toEqual({
      outcome: "completed",
      resource: {
        id: "run_0123456789abcdef0123",
        kind: "research_run",
        status: "succeeded",
      },
    });
    expect(JSON.stringify(durable)).not.toMatch(/private-request-id|private-worker/);
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
        content: SAFE_TOOL_FAILED,
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
