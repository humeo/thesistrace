import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";
import { expect, test } from "vitest";

import { projectResearchA2UIContent, RESEARCH_A2UI_CATALOG_ID, RESEARCH_A2UI_PROTOCOL_VERSION } from "../../contracts/research-a2ui.mjs";
import { DAILY_TRACK_TOOL_NAMES, ORIGIN_RUN_ID, TRACK_ID, dailyTrackDetail, dailyTrackFixtureOutput } from "../test-fixtures/daily-track.js";
import { appendExchange, runScriptedTrajectory, scriptedCallOptions, type RecordedToolCall } from "../test-fixtures/scripted-trajectory.js";
import {
  SCRIPTED_LIST_DAILY_TRACKS_PROMPT, SCRIPTED_RELOAD_DAILY_TRACK_PROMPT,
  SCRIPTED_RESUME_DAILY_TRACK_PROMPT, SCRIPTED_START_DAILY_TRACK_PROMPT,
  SCRIPTED_STOP_DAILY_TRACK_PROMPT,
} from "./scripted-language-model.js";

const startPrompt = `Start daily tracking for ${ORIGIN_RUN_ID}.`;
const reloadPrompt = `Reload DailyTrack ${TRACK_ID}.`;
const retryPrompt = `Retry blocked DailyTrack ${TRACK_ID}.`;

test.each([false, true])("the model verifies the %s Origin and presents current Track facts without private internals", async (fromThread) => {
  const request = options(fromThread ? SCRIPTED_START_DAILY_TRACK_PROMPT : startPrompt);
  if (fromThread) {
    request.prompt.splice(1, 1);
    const input = { run_id: ORIGIN_RUN_ID };
    appendExchange(request, "prior-origin", "get_research_run", input, dailyTrackFixtureOutput({ name: "get_research_run", input }));
    followUp(request, SCRIPTED_START_DAILY_TRACK_PROMPT);
  }
  const output = await runScriptedTrajectory(request, dailyTrackFixtureOutput);
  expect(output.calls.slice(0, 4).map((call) => call.name)).toEqual(["get_research_run", "list_daily_tracks", "start_daily_track", "get_daily_track"]);
  expect(output.calls.find((call) => call.name === "start_daily_track")?.input).toEqual({
    run_id: ORIGIN_RUN_ID, request_id: "agent_00000000000040008000000000000041_track_start_v1",
  });
  const surface = output.calls.find((call) => call.name === "render_a2ui")!;
  expect(validSurface(surface.input)).toMatchObject({ valid: true, kind: "ready" });
  expect(JSON.stringify(surface)).toContain(`/daily-tracks/${TRACK_ID}`);
  expect(JSON.stringify(surface)).toContain(ORIGIN_RUN_ID);
  expect(JSON.stringify(surface)).toContain("1.2300");
  expect(JSON.stringify(surface)).toContain("1.17");
  expect(JSON.stringify(surface)).not.toContain("private-daily-track-provenance");
  expect(output.text).toContain("not a new immutable Research Result");
  expect(output.calls.length + 1).toBeLessThanOrEqual(16);
});

test.each(["factor_evaluation", "queued", "failed", "cancelled", "running"])("ineligible %s Origin never produces a Track", async (state) => {
  const output = await runScriptedTrajectory(options(startPrompt), (call) => call.name === "get_research_run" ? {
    id: ORIGIN_RUN_ID, status: state === "factor_evaluation" ? "succeeded" : state,
    input: { research_kind: state === "factor_evaluation" ? "factor_evaluation" : "strategy_backtest" },
  } : dailyTrackFixtureOutput(call));
  expect(output.calls.map((call) => call.name)).toEqual(["get_research_run"]);
  expect(output.text).toContain("requires a succeeded Strategy");
});

test("an existing Origin on a later List page is reused, never restarted", async () => {
  const output = await runScriptedTrajectory(options(startPrompt), (call) => call.name === "list_daily_tracks" ? {
    items: call.occurrence === 1 ? [] : [{ id: TRACK_ID, seed_run_id: ORIGIN_RUN_ID, status: "active" }],
    next_cursor: call.occurrence === 1 ? "opaque-next" : null,
  } : dailyTrackFixtureOutput(call));
  expect(output.calls.filter((call) => call.name === "list_daily_tracks").map((call) => call.input)).toEqual([{ limit: 20 }, { limit: 20, cursor: "opaque-next" }]);
  expect(output.calls.some((call) => call.name === "start_daily_track")).toBe(false);
  expect(output.text).toContain(TRACK_ID);
});

test.each(["get_research_run", "list_daily_tracks", "start_daily_track", "get_daily_track", "get_daily_track_result"])("transient %s preserves the exact call and retry guidance", async (name) => {
  const output = await runScriptedTrajectory(options(startPrompt), (call) => call.name === name && call.occurrence === 1
    ? { code: "TEMPORARILY_UNAVAILABLE", retryable: true, retry_after_seconds: 2 }
    : dailyTrackFixtureOutput(call));
  const attempts = output.calls.filter((call) => call.name === name);
  expect(attempts.length).toBeGreaterThanOrEqual(2);
  expect(attempts[1]?.input).toEqual(attempts[0]?.input);
  expect(output.waits).toContain(2);
  expect(output.text).toContain(TRACK_ID);
});

test.each(["STATE_CONFLICT", "IDEMPOTENCY_CONFLICT", "FORBIDDEN", "NOT_FOUND", "INTERNAL"])("structured %s failure is not silently retried", async (code) => {
  const output = await runScriptedTrajectory(options(startPrompt), (call) => call.name === "start_daily_track" ? { code } : dailyTrackFixtureOutput(call));
  expect(output.calls.filter((call) => call.name === "start_daily_track")).toHaveLength(1);
  expect(output.calls.some((call) => call.name === "get_daily_track")).toBe(false);
  expect(output.text).toContain(code);
});

test("repeated dependency failures end within a bounded model turn", async () => {
  const output = await runScriptedTrajectory(options(startPrompt), () => ({ code: "TEMPORARILY_UNAVAILABLE", retry_after_seconds: 2 }));
  expect(output.calls).toHaveLength(3);
  expect(output.waits).toEqual([2, 2]);
  expect(output.text).toContain("TEMPORARILY_UNAVAILABLE");
});

test.each(["start_daily_track", "retry_daily_track"])("explicit recovery replays an uncertain %s under the original Request ID", async (action) => {
  const request = options(action === "start_daily_track" ? startPrompt : retryPrompt);
  const resolve = (call: RecordedToolCall) => call.name === "get_daily_track" && action === "retry_daily_track"
    ? dailyTrackDetail("blocked", "blocked") : dailyTrackFixtureOutput(call);
  const interrupted = await runScriptedTrajectory(request, (call) => call.name === action ? { code: "MCP_TRANSPORT_UNAVAILABLE" } : resolve(call));
  const original = interrupted.calls.find((call) => call.name === action);
  expect(original).toBeDefined();
  request.prompt[0] = { role: "system", content: "Agent Run identity: 00000000-0000-4000-8000-000000000099." };
  followUp(request, SCRIPTED_RESUME_DAILY_TRACK_PROMPT);
  const resumed = await runScriptedTrajectory(request, dailyTrackFixtureOutput);
  expect(resumed.calls[0]).toEqual(original);
  expect(resumed.calls.filter((call) => call.name === action)).toHaveLength(1);
  expect(resumed.text).toContain(TRACK_ID);
  followUp(request, SCRIPTED_RESUME_DAILY_TRACK_PROMPT);
  const reconnected = await runScriptedTrajectory(request, dailyTrackFixtureOutput);
  expect(reconnected.calls.some((call) => call.name === action)).toBe(false);
});

test.each(["active", "blocked"])("Retry acceptance can remain %s, without reissuing the action", async (status) => {
  const output = await runScriptedTrajectory(options(retryPrompt), (call) => call.name === "get_daily_track"
    ? dailyTrackDetail(call.occurrence === 1 ? "blocked" : status, call.occurrence === 1 || status === "blocked" ? "blocked" : "up_to_date")
    : call.name === "retry_daily_track" ? { outcome: "accepted", track_id: TRACK_ID, status, replayed: false, retry_after_seconds: status === "blocked" ? null : 2 }
    : dailyTrackFixtureOutput(call));
  expect(output.calls.filter((call) => call.name === "retry_daily_track").map((call) => call.input)).toEqual([{
    track_id: TRACK_ID, request_id: "agent_00000000000040008000000000000041_track_retry_v1",
  }]);
  expect(output.text).toContain(`is ${status}`);
});

test.each(["active", "stopping", "stopped"])("Retry is not submitted in the %s lifecycle", async (status) => {
  const output = await runScriptedTrajectory(options(retryPrompt), (call) => call.name === "get_daily_track"
    ? dailyTrackDetail(status, status === "active" ? "up_to_date" : status) : dailyTrackFixtureOutput(call));
  expect(output.calls.some((call) => call.name === "retry_daily_track")).toBe(false);
  expect(output.text).toContain("not eligible for Retry");
});

test.each(["queued", "calculating", "retry_wait"])("active %s advances are read with guidance, then the Agent ends independently", async (phase) => {
  const output = await runScriptedTrajectory(options(reloadPrompt), (call) => call.name === "get_daily_track"
    ? dailyTrackDetail("active", phase) : dailyTrackFixtureOutput(call));
  expect(output.calls.filter((call) => call.name === "get_daily_track")).toHaveLength(3);
  expect(output.waits).toEqual([2, 2]);
  expect(output.calls.some((call) => call.name === "refresh_daily_track" || call.name === "retry_daily_track")).toBe(false);
  expect(output.text).toContain("Core Tracking Worker continues independently");
});

test("reloading creates a new read-only current surface without rewriting prior observations", async () => {
  const request = options(startPrompt);
  const initial = await runScriptedTrajectory(request, dailyTrackFixtureOutput);
  const prior = JSON.stringify(request.prompt);
  const originalSurface = initial.calls.find((call) => call.name === "render_a2ui")!;
  followUp(request, SCRIPTED_RELOAD_DAILY_TRACK_PROMPT);
  const refreshed = await runScriptedTrajectory(request, (call) => dailyTrackFixtureOutput(call, "2024-02-01"));
  expect(refreshed.calls.map((call) => call.name)).toEqual(["get_daily_track", "get_daily_track_result", "get_daily_track_result", "get_daily_track_result", "render_a2ui"]);
  expect(JSON.stringify(refreshed.calls.at(-1))).toContain("2024-02-01");
  expect(JSON.stringify(originalSurface)).toContain("2024-01-31");
  expect(JSON.stringify(request.prompt).startsWith(prior.slice(0, -1))).toBe(true);
});

test.each([false, true])("Observation pagination distinguishes a latest row from a bounded partial view: %s", async (partial) => {
  const output = await runScriptedTrajectory(options(reloadPrompt), (call) => {
    const value = dailyTrackFixtureOutput(call);
    if (call.name === "get_daily_track_result" && call.input.section === "strategy_observations") {
      value.next_cursor = call.input.cursor === "second" && !partial ? null : call.input.cursor === undefined ? "first" : "second";
    }
    return value;
  });
  const pages = output.calls.filter((call) => call.name === "get_daily_track_result" && call.input.section === "strategy_observations");
  expect(pages.map((call) => call.input)).toEqual([
    { track_id: TRACK_ID, section: "strategy_observations", limit: 50 },
    { track_id: TRACK_ID, section: "strategy_observations", limit: 50, cursor: "first" },
    { track_id: TRACK_ID, section: "strategy_observations", limit: 50, cursor: "second" },
  ]);
  expect(JSON.stringify(output.calls.at(-1))).toContain(partial ? "Latest retrieved Observation (partial)" : "Latest DailyTrack Observation");
});

test.each(["wrong-track", "missing-summary", "changed-head", "private-section", "bad-observation"])("inconsistent %s data never becomes a surface fact", async (scenario) => {
  const output = await runScriptedTrajectory(options(reloadPrompt), (call) => {
    const value = dailyTrackFixtureOutput(call);
    if (call.name === "get_daily_track_result") {
      if (scenario === "wrong-track") value.track_id = "track_abcdef0123456789abcd";
      if (scenario === "missing-summary" && call.input.section === "strategy_summary") value.summary = {};
      if (scenario === "changed-head" && call.input.section === "provenance") value.tracking_strategy_session = "2024-02-01";
      if (scenario === "bad-observation" && call.input.section === "strategy_observations") value.items = [{ session: "2024-01-31", net_nav: "NaN" }];
    }
    if (scenario === "private-section" && call.name === "get_daily_track") value.available_result_sections = ["checkpoint"];
    return value;
  });
  expect(output.calls.some((call) => call.name === "render_a2ui")).toBe(false);
  expect(output.text).toContain("incomplete");
});

test("List, missing intent and absent Stop remain explicit, with no invisible business action", async () => {
  const listed = await runScriptedTrajectory(options(SCRIPTED_LIST_DAILY_TRACKS_PROMPT), () => ({ items: [{ id: TRACK_ID, seed_run_id: ORIGIN_RUN_ID, status: "active" }], next_cursor: "more" }));
  expect(listed.calls.map((call) => call.name)).toEqual(["list_daily_tracks"]);
  expect(listed.text).toContain("More DailyTracks");
  for (const prompt of [SCRIPTED_START_DAILY_TRACK_PROMPT, SCRIPTED_STOP_DAILY_TRACK_PROMPT]) {
    const output = await runScriptedTrajectory(options(prompt), () => { throw new Error("No Tool expected"); });
    expect(output.calls).toEqual([]);
    expect(output.text).toContain(prompt === SCRIPTED_STOP_DAILY_TRACK_PROMPT ? "tracking:stop" : "successful Strategy");
  }
});

test("Discovery removal is respected even for a previously known Start capability", async () => {
  const request = options(startPrompt);
  request.tools = request.tools?.filter((tool) => tool.name !== "start_daily_track");
  const output = await runScriptedTrajectory(request, dailyTrackFixtureOutput);
  expect(output.calls.some((call) => call.name === "start_daily_track")).toBe(false);
  expect(output.text).toContain("did not provide");
});

function options(prompt: string): LanguageModelV3CallOptions {
  return scriptedCallOptions(prompt, [...DAILY_TRACK_TOOL_NAMES, "render_a2ui"].map((name) => ({
    type: "function", name, description: name,
    inputSchema: { type: "object", properties: {}, additionalProperties: true },
  })));
}

function followUp(request: LanguageModelV3CallOptions, prompt: string): void {
  request.prompt.push({ role: "user", content: [{ type: "text", text: prompt }] });
}

function validSurface(input: Record<string, unknown>) {
  return projectResearchA2UIContent({ a2ui_operations: [
    { version: RESEARCH_A2UI_PROTOCOL_VERSION, createSurface: { catalogId: RESEARCH_A2UI_CATALOG_ID, surfaceId: input.surfaceId } },
    { version: RESEARCH_A2UI_PROTOCOL_VERSION, updateComponents: { surfaceId: input.surfaceId, components: input.components } },
  ] });
}
