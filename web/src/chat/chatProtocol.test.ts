// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ChatApiError,
  ChatCommandAcceptanceUnknownError,
  decodeChatTurn,
  decodeCommandReceipt,
  decodeTimelinePage,
  loadTimelinePage,
  steerChat,
} from "./chatProtocol";

const threadId = "00000000-0000-4000-8000-000000000001";
const turnId = "00000000-0000-4000-8000-000000000002";
const inputId = "00000000-0000-4000-8000-000000000003";

afterEach(() => vi.unstubAllGlobals());

describe("Chat API decoding", () => {
  it("decodes current Turn identity and a sanitized waiting question", () => {
    expect(decodeChatTurn({
      id: turnId,
      kind: "prompt",
      model_key: "primary",
      question: {
        interrupt_id: `${turnId}::ask-1`,
        options: [{ description: "Broad liquid universe", label: "CSI 1000" }],
        question: "Which universe?",
        selection_mode: "single_select",
      },
      reasoning_effort: "medium",
      started_at: "2026-09-02T00:00:00.000000Z",
      status: "waiting_for_user",
      terminal_error_code: null,
    })).toMatchObject({ id: turnId, status: "waiting_for_user" });
  });

  it("accepts every public timeline variant and rejects private Tool details", () => {
    const page = decodeTimelinePage({
      entries: [
        entry("user_input", { content: "Check quality", inputId, source: "prompt" }, "user:1"),
        entry("assistant_message", { content: "Working", status: "streaming" }, "assistant:1"),
        entry("tool_activity", { name: "get_research_context", status: "complete" }, "tool:1"),
        entry("a2ui", { activityType: "a2ui-surface", content: { status: "loading" }, status: "loading" }, "a2ui:1"),
        entry("question", {
          interrupt_id: `${turnId}::ask-1`, options: null, question: "Which universe?",
          selection_mode: "free_text", status: "pending",
        }, "question:1"),
        entry("turn_outcome", { status: "completed" }, "outcome:1"),
      ],
      next_cursor: null,
    });
    expect(page.entries.map((item) => item.kind)).toEqual([
      "user_input", "assistant_message", "tool_activity", "a2ui", "question", "turn_outcome",
    ]);
    expect(() => decodeTimelinePage({
      entries: [entry("tool_activity", {
        arguments: { formula: "private" },
        name: "get_research_context",
        status: "complete",
      }, "tool:private")],
      next_cursor: null,
    })).toThrow(ChatApiError);
  });

  it("rejects unknown fields and invalid command identities", () => {
    expect(() => decodeCommandReceipt({
      command_id: inputId,
      error_code: null,
      kind: "steer",
      status: "accepted",
      turn_id: turnId,
      model: "must-not-appear",
    })).toThrow(ChatApiError);
  });
});

describe("Chat API requests", () => {
  it("sends Steer with only content and Turn identities", async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => Response.json({
      command_id: inputId,
      error_code: null,
      kind: "steer",
      status: "accepted",
      turn_id: turnId,
    }));
    vi.stubGlobal("fetch", fetch);
    await steerChat(threadId, { content: "Also compare turnover", expectedTurnId: turnId, inputId });
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual({
      content: "Also compare turnover",
      expectedTurnId: turnId,
      inputId,
    });
  });

  it("requests only the latest 50 timeline entries by default", async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL) => (
      Response.json({ entries: [], next_cursor: null })
    ));
    vi.stubGlobal("fetch", fetch);
    await loadTimelinePage(threadId);
    expect(String(fetch.mock.calls[0]?.[0])).toBe(`/api/agent/sessions/${threadId}/timeline?limit=50`);
  });

  it("treats a command storage response as unknown acceptance", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(
      { code: "CHAT_STORAGE_FAILURE" },
      { status: 503 },
    )));

    await expect(steerChat(threadId, {
      content: "Also compare turnover",
      expectedTurnId: turnId,
      inputId,
    })).rejects.toBeInstanceOf(ChatCommandAcceptanceUnknownError);
  });
});

function entry(kind: string, payload: object, entryId: string) {
  return {
    created_at: "2026-09-02T00:00:00.000000Z",
    entry_id: entryId,
    kind,
    payload,
    turn_id: turnId,
  };
}
