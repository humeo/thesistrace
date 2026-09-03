import { describe, expect, it } from "vitest";

import {
  ChatControlError,
  encodeTimelineCursor,
  projectAskUserInterrupt,
  readSteerInput,
  readStopInput,
  readTimelineQuery,
  validateAnswerForQuestion,
  type PendingQuestion,
} from "./chat-control.js";

const THREAD_ID = "00000000-0000-4000-8000-000000000001";
const TURN_ID = "00000000-0000-4000-8000-000000000002";
const INPUT_ID = "00000000-0000-4000-8000-000000000003";

describe("chat control boundary", () => {
  it("accepts only a content-only Steer command with canonical Turn identity", async () => {
    await expect(readSteerInput(jsonRequest({
      content: "Compare turnover as well.",
      expectedTurnId: TURN_ID,
      inputId: INPUT_ID,
    }))).resolves.toMatchObject({
      content: "Compare turnover as well.",
      expectedTurnId: TURN_ID,
      inputId: INPUT_ID,
    });

    await expect(readSteerInput(jsonRequest({
      content: "Compare turnover as well.",
      expectedTurnId: TURN_ID,
      inputId: INPUT_ID,
      modelKey: "smuggled-model",
    }))).rejects.toMatchObject({ code: "INVALID_CHAT_INPUT", status: 400 });
  });

  it("keeps Stop identity separate from Steer input identity", async () => {
    await expect(readStopInput(jsonRequest({
      commandId: INPUT_ID,
      expectedTurnId: TURN_ID,
    }))).resolves.toMatchObject({ commandId: INPUT_ID, expectedTurnId: TURN_ID });
    await expect(readStopInput(jsonRequest({
      commandId: INPUT_ID,
      content: "not allowed",
      expectedTurnId: TURN_ID,
    }))).rejects.toBeInstanceOf(ChatControlError);
  });

  it("projects only one matching ask_user suspension into a sanitized question", () => {
    expect(projectAskUserInterrupt({
      outcome: {
        interrupts: [{
          id: `${TURN_ID}::tool-1`,
          metadata: {
            mastra: {
              runId: TURN_ID,
              suspendPayload: {
                options: [{ description: "  Lower churn  ", label: " Quality " }],
                question: "  Which objective?  ",
                selectionMode: "single_select",
              },
              toolName: "ask_user",
              type: "mastra_suspend",
            },
          },
          reason: "mastra:tool_suspend",
          toolCallId: "tool-1",
        }],
        type: "interrupt",
      },
      type: "RUN_FINISHED",
    }, TURN_ID)).toEqual({
      interruptId: `${TURN_ID}::tool-1`,
      options: [{ description: "Lower churn", label: "Quality" }],
      question: "Which objective?",
      selectionMode: "single_select",
      toolCallId: "tool-1",
    });
  });

  it("validates single, multiple, and free-text answers against the saved question", () => {
    const single = question("single_select");
    expect(() => validateAnswerForQuestion("Quality", single)).not.toThrow();
    expect(() => validateAnswerForQuestion("Unknown", single)).toThrowError(ChatControlError);

    const multiple = question("multi_select");
    expect(() => validateAnswerForQuestion(["Quality", "Risk"], multiple)).not.toThrow();
    expect(() => validateAnswerForQuestion(["Quality", "Quality"], multiple)).toThrowError(ChatControlError);

    expect(() => validateAnswerForQuestion("Explain the trade-off", {
      ...single,
      options: null,
      selectionMode: "free_text",
    })).not.toThrow();
  });

  it("uses opaque, bounded timeline cursors", () => {
    const before = encodeTimelineCursor({
      startedAt: "2026-08-30T02:03:04.123456Z",
      turnId: TURN_ID,
    });
    expect(readTimelineQuery(new Request(
      `http://agent.test/api/agent/sessions/${THREAD_ID}/timeline?before=${before}&limit=20`,
    ))).toEqual({
      before: {
        startedAt: "2026-08-30T02:03:04.123456Z",
        turnId: TURN_ID,
      },
      limit: 20,
    });
    expect(() => readTimelineQuery(new Request(
      `http://agent.test/api/agent/sessions/${THREAD_ID}/timeline?before=51`,
    ))).toThrowError(ChatControlError);
    expect(() => readTimelineQuery(new Request(
      `http://agent.test/api/agent/sessions/${THREAD_ID}/timeline?limit=21`,
    ))).toThrowError(ChatControlError);
    const legacy = Buffer.from(JSON.stringify({ sequence: 51, version: 1 }), "utf8")
      .toString("base64url");
    expect(() => readTimelineQuery(new Request(
      `http://agent.test/api/agent/sessions/${THREAD_ID}/timeline?before=${legacy}`,
    ))).toThrowError(ChatControlError);
  });
});

function question(selectionMode: "single_select" | "multi_select"): PendingQuestion {
  return {
    interruptId: `${TURN_ID}::tool-1`,
    options: [{ label: "Quality" }, { label: "Risk" }],
    question: "Which objective?",
    selectionMode,
    toolCallId: "tool-1",
  };
}

function jsonRequest(body: unknown): Request {
  return new Request("http://agent.test/chat-command", {
    body: JSON.stringify(body),
    headers: { "content-type": "application/json" },
    method: "POST",
  });
}
