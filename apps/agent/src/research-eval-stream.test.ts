import { afterEach, describe, expect, it, vi } from "vitest";
import { EventType } from "@ag-ui/core";

import { observeResearchEvalStream, observeResearchEvalTurn, requestResearchEvalTurn, researchEvalConversationMeetsOutcome, researchEvalPolledRun, researchEvalToolRetryCount, unresolvedResearchEvalToolFailure } from "./research-eval-stream.js";
import { projectSafeToolResult } from "./safe-tool-result.js";
import { researchA2UITool } from "./research-a2ui-tool.js";
import { ResearchA2UIEventProjector } from "./research-a2ui-events.js";
import { RESEARCH_A2UI_ACTIVITY_TYPE, RESEARCH_A2UI_CATALOG_ID, RESEARCH_A2UI_PROTOCOL_VERSION } from "@thesistrace/contracts/research-a2ui";

const threadId = "433643b2-5aeb-42bc-bbff-f5db8a09f706";
const runId = "dc39ed24-435a-40e2-bf99-c3a89bb1817c";
const frames = [
  { type: "RUN_STARTED", threadId, runId },
  { type: "TEXT_MESSAGE_START", messageId: "message", role: "assistant" },
  { type: "TEXT_MESSAGE_CONTENT", messageId: "message", delta: "private-eval-canary 中文" },
  { type: "TEXT_MESSAGE_END", messageId: "message" },
  { type: "RUN_FINISHED", threadId, runId },
];
const encode = (events: unknown[]) => events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
function surface(components: Record<string, unknown>[], messageId = "a2ui-surface-result") {
  return { type: "ACTIVITY_SNAPSHOT", activityType: RESEARCH_A2UI_ACTIVITY_TYPE, messageId, replace: true, content: {
    a2ui_operations: [
      { version: RESEARCH_A2UI_PROTOCOL_VERSION, createSurface: { surfaceId: "result", catalogId: RESEARCH_A2UI_CATALOG_ID } },
      { version: RESEARCH_A2UI_PROTOCOL_VERSION, updateComponents: { surfaceId: "result", components } },
    ],
  } };
}
function response(text: string, chunkBytes = 7) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream<Uint8Array>({ start(controller) {
    for (let index = 0; index < bytes.length; index += chunkBytes) controller.enqueue(bytes.slice(index, index + chunkBytes));
    controller.close();
  } }), { headers: { "content-type": "text/event-stream; charset=utf-8" } });
}
function oversizedResponse() {
  const chunk = new Uint8Array(64 * 1024).fill("x".charCodeAt(0));
  let remaining = 32 * 1024 * 1024;
  let produced = 0;
  let cancelledAt: number | null = null;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      const size = Math.min(remaining, chunk.byteLength);
      controller.enqueue(size === chunk.byteLength ? chunk : chunk.slice(0, size));
      produced += size;
      remaining -= size;
      if (remaining === 0) controller.close();
    },
    cancel() { cancelledAt = produced; },
  }, { highWaterMark: 0 });
  return {
    response: new Response(body, { headers: { "content-type": "text/event-stream; charset=utf-8" } }),
    cancelledAtBytes: () => cancelledAt,
  };
}
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe("real-model evaluator AG-UI transport", () => {
  it("evaluates the same visible explanation in a validated A2UI-only answer", async () => {
    const explanation = "run_0123456789abcdef0123: Rank IC is unavailable with one stock; coverage is not an estimated IC.";
    const content = await researchA2UITool.execute?.({ surfaceId: "result-explanation",
      components: [{ id: "root", component: "Text", text: explanation }],
    }, { agent: { messages: [], toolCallId: "render-explanation" } } as never);
    const projector = new ResearchA2UIEventProjector();
    projector.project({ type: EventType.TOOL_CALL_START, toolCallId: "render-explanation", toolCallName: "render_a2ui", parentMessageId: "assistant" });
    const rendered = projector.project({ type: EventType.TOOL_CALL_RESULT, toolCallId: "render-explanation", content: JSON.stringify(content) });
    const turn = await observeResearchEvalTurn(response(encode([frames[0], ...rendered.events, frames.at(-1)])));
    expect(turn.terminal).toBe(true);
    expect(turn.failure).toBeNull();
    expect(turn.text).toBe(explanation);
    expect(researchEvalConversationMeetsOutcome({ outcome: "explained-result" }, [turn], { runId: "run_0123456789abcdef0123" })).toBe(true);
  });
  it("counts only visible registered values in layout order, not schema or navigation metadata", async () => {
    const turn = await observeResearchEvalTurn(response(encode([frames[0], surface([
      { id: "root", component: "Column", children: ["visible", "metrics", "table", "provenance", "navigation"] },
      { id: "coverage_rank_ic_unavailable", component: "Divider" },
      { id: "navigation", component: "Navigation", label: "Open", href: "/research-runs/run_0123456789abcdef0123" },
      { id: "visible", component: "Row", children: ["coverage_rank_ic_unavailable", "body"] },
      { id: "body", component: "Text", text: "Evidence", variant: "title" },
      { component: "ResearchComparison", id: "metrics", runIds: ["run_0123456789abcdef0123"] },
      { id: "table", component: "Table", caption: "Observations", summary: "Rows", columns: ["Rank IC"], rows: [["unavailable"]] },
      { component: "DailyTrack", id: "provenance", trackId: "track_0123456789abcdef0123" },
    ]), frames.at(-1)])));
    expect(turn.text).toBe("Evidence\nRows\nObservations\nRank IC\nunavailable\nOpen");
    expect(turn.text).not.toContain("run_0123456789abcdef0123");
    expect(researchEvalConversationMeetsOutcome({ outcome: "explained-result" }, [turn], { runId: "run_0123456789abcdef0123" })).toBe(false);
  });
  it.each(["invalid", "loading", "replacement", "partial"])("does not retain an answer from a superseded %s surface", async (kind) => {
    const first = surface([{ id: "root", component: "Text", text: "Previous complete explanation" }]);
    const replacement: Record<string, unknown> = kind === "replacement"
      ? surface([{ id: "root", component: "Text", text: "Updated" }])
      : { ...first, content: kind === "loading" ? { status: "building" } : { invalid: true }, ...(kind === "partial" ? { replace: false } : {}) };
    const turn = await observeResearchEvalTurn(response(encode([frames[0], first, replacement, frames.at(-1)])));
    expect(turn.text).toBe(kind === "replacement" ? "Updated" : "");
  });
  it("does not borrow A2UI history or count an unregistered activity as this Turn's answer", async () => {
    const activity = surface([{ id: "root", component: "Text", text: "Historical complete explanation" }]);
    const turn = await observeResearchEvalTurn(response(encode([frames[0],
      { type: "MESSAGES_SNAPSHOT", messages: [{ id: activity.messageId, role: "activity", activityType: activity.activityType, content: activity.content }] },
      { ...activity, activityType: "unregistered" }, frames.at(-1),
    ])));
    expect(turn.text).toBe("");
  });
  it("does not qualify a rendered answer that omits the required result explanation", async () => {
    const turn = await observeResearchEvalTurn(response(encode([frames[0], surface([
      { id: "root", component: "Text", text: "run_0123456789abcdef0123: Rank IC and coverage results are displayed here." },
    ]), frames.at(-1)])));
    expect(researchEvalConversationMeetsOutcome({ outcome: "explained-result" }, [turn], { runId: "run_0123456789abcdef0123" })).toBe(false);
  });
  it("returns only the opaque interrupt identity needed to resume an eval Turn", async () => {
    const interruptId = `${runId}::ask-user`;
    const turn = await observeResearchEvalTurn(response(encode([
      frames[0],
      {
        outcome: {
          interrupts: [{ id: interruptId, metadata: { private: "not projected" }, reason: "mastra:tool_suspend", toolCallId: "ask-user" }],
          type: "interrupt",
        },
        runId,
        threadId,
        type: "RUN_FINISHED",
      },
    ])));
    expect(turn).toMatchObject({ interrupt: { id: interruptId }, terminal: true });
    expect(turn.interrupt).toEqual({ id: interruptId });
  });
  it("retains the terminal event after a case misses its quality deadline", async () => {
    vi.useFakeTimers();
    const observed: Array<"completed" | "failed"> = [];
    const turn = requestResearchEvalTurn(async (timeoutMs) => new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(encode([frames[0]])));
        const timeout = setTimeout(() => controller.error(new Error("synthetic transport timeout")), timeoutMs);
        setTimeout(() => {
          clearTimeout(timeout);
          controller.enqueue(new TextEncoder().encode(encode(frames.slice(1))));
          controller.close();
        }, 240_000);
      },
    }), { headers: { "content-type": "text/event-stream" } })).then(
      (result) => { observed.push("completed"); return result; },
      () => { observed.push("failed"); return null; },
    );
    await vi.advanceTimersByTimeAsync(180_000);
    expect(observed).toEqual([]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect((await turn)?.terminal).toBe(true);
    expect(observed).toEqual(["completed"]);
  });
  it("still terminates a stalled observation at the finite Run ceiling plus delivery margin", async () => {
    vi.useFakeTimers();
    let failed = false;
    const turn = requestResearchEvalTurn(async (timeoutMs) => new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(encode([frames[0]])));
        setTimeout(() => controller.error(new Error("private timeout diagnostic")), timeoutMs);
      },
    }), { headers: { "content-type": "text/event-stream" } })).catch((error: unknown) => {
      failed = true;
      expect((error as Error).message).toBe("RESEARCH_EVAL_PROTOCOL_INVALID");
    });
    await vi.advanceTimersByTimeAsync(600_000);
    expect(failed).toBe(false);
    await vi.advanceTimersByTimeAsync(30_000);
    await turn;
    expect(failed).toBe(true);
  });
  const coreId = "run_0123456789abcdef0123";
  function toolFrames(id: string, status: string, resourceId = coreId) {
    return [
      { type: "TOOL_CALL_START", toolCallId: id, toolCallName: "get_research_run" },
      { type: "TOOL_CALL_ARGS", toolCallId: id, delta: "{}" },
      { type: "TOOL_CALL_END", toolCallId: id },
      { type: "TOOL_CALL_RESULT", messageId: `${id}-result`, toolCallId: id, content: projectSafeToolResult({ id: resourceId, status }, false), role: "tool" },
    ];
  }
  it("releases the polling fixture only after an actual nonterminal result, not a started query", async () => {
    const observed: Array<string | null> = [];
    await observeResearchEvalTurn(response(encode([
      frames[0], ...toolFrames("first-read", "queued"), frames.at(-1),
    ])), (call) => { observed.push(call.outcome?.resource?.status ?? null); });
    expect(observed).toEqual(["queued"]);
  });
  it("proves a same-Run nonterminal-to-terminal transition instead of counting repeated reads", async () => {
    for (const [first, last, finalId, expected] of [
      ["queued", "succeeded", coreId, true],
      ["running", "succeeded", coreId, true],
      ["succeeded", "succeeded", coreId, false],
      ["queued", "running", coreId, false],
      ["succeeded", "queued", coreId, false],
      ["queued", "succeeded", "run_1123456789abcdef0123", false],
    ] as const) {
      const turn = await observeResearchEvalTurn(response(encode([
        frames[0], ...toolFrames("first-read", first), ...toolFrames("last-read", last, finalId), frames.at(-1),
      ])));
      expect(researchEvalPolledRun(turn.toolEvents)).toBe(expected);
    }
  });
  it.each([
    ["queued", "succeeded", true],
    ["succeeded", "queued", false],
  ] as const)("measures parallel polling in result order: %s then %s", async (firstResult, lastResult, expected) => {
    const startedFirst = toolFrames("started-first", lastResult);
    const startedSecond = toolFrames("started-second", firstResult);
    const observed: Array<string | null> = [];
    const turn = await observeResearchEvalTurn(response(encode([
      frames[0], ...startedFirst.slice(0, 3), ...startedSecond.slice(0, 3),
      startedSecond[3], startedFirst[3], frames.at(-1),
    ])), (call) => { observed.push(call.outcome?.resource?.status ?? null); });
    expect(observed).toEqual([firstResult, lastResult]);
    expect(researchEvalPolledRun(turn.toolEvents)).toBe(expected);
  });
  it.each([true, false])("attributes parallel Tool failure in result order; recovered=%s", async (recovered) => {
    const failed = toolFrames("failed-parallel-read", "queued");
    failed[3] = { type: "TOOL_CALL_RESULT", toolCallId: "failed-parallel-read", messageId: "failed-parallel-read-result", role: "tool",
      content: projectSafeToolResult({ code: "MCP_TRANSIENT" }, true) };
    const succeeded = toolFrames("successful-parallel-read", "succeeded");
    const [startedFirst, startedSecond] = recovered ? [succeeded, failed] : [failed, succeeded];
    const turn = await observeResearchEvalTurn(response(encode([
      frames[0], ...startedFirst.slice(0, 3), ...startedSecond.slice(0, 3),
      startedSecond[3], startedFirst[3], frames.at(-1),
    ])));
    expect(unresolvedResearchEvalToolFailure(turn.toolEvents)).toBe(recovered ? null : "MCP_TRANSIENT");
    expect(researchEvalToolRetryCount(turn.toolEvents)).toBe(0);
  });
  it("retains unfinished Tool attempts when the Run fails before their results", async () => {
    const turn = await observeResearchEvalTurn(response(encode([
      frames[0], ...toolFrames("unfinished-read", "queued").slice(0, 3),
      { type: "RUN_ERROR", code: "PROVIDER_TIMEOUT", message: "The provider timed out." },
    ])));
    expect(turn.calls).toEqual([{ id: "unfinished-read", name: "get_research_run", failure: null, outcome: null }]);
    expect(turn.failure).toBe("PROVIDER_TIMEOUT");
  });
  it("reports the most recent unresolved failure when a capability fails again", async () => {
    const failures = [
      ["first", "get_research_run", "MCP_TRANSIENT"],
      ["second", "get_alpha_catalog", "TOOL_ERROR"],
      ["third", "get_research_run", "MCP_AUTHENTICATION"],
    ].flatMap(([id, name, code]) => {
      const events = toolFrames(id, "queued");
      events[0] = { type: "TOOL_CALL_START", toolCallId: id, toolCallName: name };
      events[3] = { type: "TOOL_CALL_RESULT", toolCallId: id, messageId: `${id}-result`, role: "tool",
        content: projectSafeToolResult({ code }, true) };
      return events;
    });
    const turn = await observeResearchEvalTurn(response(encode([frames[0], ...failures, frames.at(-1)])));
    expect(unresolvedResearchEvalToolFailure(turn.toolEvents)).toBe("MCP_AUTHENTICATION");
  });
  it("does not attribute a later task failure to a tool error that was already recovered", async () => {
    const failed = toolFrames("failed-read", "queued");
    failed[3] = { type: "TOOL_CALL_RESULT", toolCallId: "failed-read", messageId: "failed-read-result", role: "tool",
      content: projectSafeToolResult({ code: "MCP_TRANSIENT" }, true) };
    const first = await observeResearchEvalTurn(response(encode([frames[0], ...failed, frames.at(-1)])));
    expect(unresolvedResearchEvalToolFailure(first.toolEvents)).toBe("MCP_TRANSIENT");
    const recovered = await observeResearchEvalTurn(response(encode([
      frames[0], ...failed, ...toolFrames("recovered-read", "succeeded"), frames.at(-1),
    ])));
    expect(unresolvedResearchEvalToolFailure(recovered.toolEvents)).toBeNull();
    expect(researchEvalToolRetryCount(recovered.toolEvents)).toBe(1);
    const nextTurn = await observeResearchEvalTurn(response(encode([
      frames[0], ...toolFrames("next-turn-read", "succeeded"), frames.at(-1),
    ])));
    expect(researchEvalToolRetryCount([...first.toolEvents, ...nextTurn.toolEvents])).toBe(1);
    expect(unresolvedResearchEvalToolFailure([...first.toolEvents, ...nextTurn.toolEvents])).toBeNull();
  });
  it("uses native parsing across split UTF-8 and retains callbacks in event order", async () => {
    const events: unknown[] = [];
    await observeResearchEvalStream(response(encode(frames)), async (event) => { events.push(event); });
    expect(events).toEqual(frames);
  });
  it("accepts safe pre-admission errors without inventing a started Run", async () => {
    const events: unknown[] = [];
    await observeResearchEvalStream(response(encode([{ type: "RUN_ERROR", code: "AGENT_CAPACITY", message: "At capacity" }])), (event) => { events.push(event); });
    expect(events).toMatchObject([{ type: "RUN_ERROR", code: "AGENT_CAPACITY" }]);
  });
  it.each([
    () => response('data: {"private-eval-canary":\n\n'),
    () => response(encode(frames.slice(0, 4))),
    () => response(encode([{ type: "private-eval-canary" }])),
    () => new Response("private-eval-canary", { status: 503 }),
    () => new Response(new ReadableStream({ pull(controller) { controller.error(new Error("private-eval-canary")); } }), { headers: { "content-type": "text/event-stream" } }),
  ])("closes malformed, truncated and HTTP failures without logging content", async (makeResponse) => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await expect(observeResearchEvalStream(makeResponse(), () => undefined)).rejects.toThrow("RESEARCH_EVAL_PROTOCOL_INVALID");
    expect(error).not.toHaveBeenCalled(); expect(warning).not.toHaveBeenCalled();
  });
  it("cancels an oversized response without logging content", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const oversized = oversizedResponse();
    await expect(observeResearchEvalStream(oversized.response, () => undefined)).rejects.toThrow("RESEARCH_EVAL_PROTOCOL_INVALID");
    expect(oversized.cancelledAtBytes()).toBe(16 * 1024 * 1024 + 64 * 1024);
    expect(error).not.toHaveBeenCalled(); expect(warning).not.toHaveBeenCalled();
  }, 15_000);
  it("erases callback errors rather than letting framework logging see private values", async () => {
    await expect(observeResearchEvalStream(response(encode(frames)), () => { throw new Error("private-eval-canary"); })).rejects.toThrow("RESEARCH_EVAL_PROTOCOL_INVALID");
  });
});
