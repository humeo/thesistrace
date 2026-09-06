import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";
import { expect, test } from "vitest";

import { BATCH_ID, BATCH_TOOL_NAMES, CHILD_IDS, batchDetail, batchFixtureOutput } from "../test-fixtures/batch-research.js";
import { runScriptedTrajectory, scriptedCallOptions, type RecordedToolCall } from "../test-fixtures/scripted-trajectory.js";
import {
  SCRIPTED_AMBIGUOUS_BATCH_PROMPT,
  SCRIPTED_BATCH_LIST_PROMPT,
  SCRIPTED_BATCH_OBSERVATIONS_PROMPT,
  SCRIPTED_FACTOR_BATCH_PROMPT,
  SCRIPTED_RESUME_BATCH_PROMPT,
  SCRIPTED_STRATEGY_SWEEP_PROMPT,
} from "./scripted-language-model.js";
import { projectResearchA2UIContent, RESEARCH_A2UI_CATALOG_ID, RESEARCH_A2UI_PROTOCOL_VERSION } from "../../contracts/research-a2ui.mjs";

test.each([
  ["factor_evaluation", SCRIPTED_FACTOR_BATCH_PROMPT],
  ["strategy_sweep", SCRIPTED_STRATEGY_SWEEP_PROMPT],
] as const)("the model owns %s admission and composes ordered authoritative child comparisons", async (mode, prompt) => {
  const output = await runScriptedTrajectory(options(prompt), (call) => batchFixtureOutput(mode, call));
  const admission = output.calls.find((call) => call.name === "submit_research_batch");
  expect(admission?.input).toMatchObject({
    batch_kind: mode, request_id: "agent_00000000000040008000000000000041_batch_v1",
    start_date: "2024-01-02", end_date: "2024-01-31", universe: "top1000", neutralization: "none",
  });
  expect(admission?.input).not.toHaveProperty("folder_id");
  expect(admission?.input).not.toHaveProperty("items");
  const items = admission?.input[mode === "factor_evaluation" ? "factors" : "strategies"] as Record<string, unknown>[];
  expect(items).toHaveLength(2);
  expect(new Set(items.map((item) => item.item_key)).size).toBe(2);
  if (mode === "strategy_sweep") {
    expect(items.map((item) => item.holdings_count)).toEqual([10, 20]);
    expect(items.map((item) => item.rebalance_every_sessions)).toEqual([5, 5]);
  } else expect(items.map((item) => item.formula)).toEqual(["rank(close)", "-rank(close)"]);
  expect(output.calls.filter((call) => call.name === "get_research_run_result").map((call) => call.input.run_id)).toEqual(CHILD_IDS);
  const surfaces = output.calls.filter((call) => call.name === "render_a2ui");
  expect(surfaces).toHaveLength(1);
  for (const surface of surfaces) expect(validSurface(surface.input)).toMatchObject({ kind: "ready", valid: true });
  const table = (surfaces[0]?.input.components as Record<string, unknown>[]).find((component) => component.component === "Table");
  expect((table?.rows as string[][]).map((row) => row[2])).toEqual(CHILD_IDS);
  expect(JSON.stringify(table)).toContain(mode === "factor_evaluation" ? "-0.1200" : "1.2300");
  expect(output.text).toContain(BATCH_ID);
  expect(output.text).toContain("not a combined Batch Result");
  expect(JSON.stringify(surfaces)).not.toContain("private-batch-core-provenance");
  expect(output.calls.length + 1).toBeLessThanOrEqual(16);
});

test("partial child failure preserves the successful sibling evidence without inventing zero metrics", async () => {
  const output = await trajectory((call) => call.name === "get_research_batch"
    ? batchDetail("factor_evaluation", "completed_with_failures") : batchFixtureOutput("factor_evaluation", call));
  expect(output.calls.filter((call) => call.name === "get_research_run_result").map((call) => call.input.run_id)).toEqual([CHILD_IDS[0]]);
  const surfaces = output.calls.filter((call) => call.name === "render_a2ui");
  const table = (surfaces.at(-1)?.input.components as Record<string, unknown>[]).find((component) => component.component === "Table");
  expect((table?.rows as string[][])[1]).toEqual(["2", "negative-price-rank", CHILD_IDS[1], "failed", "No successful Result"]);
  expect(output.text).toContain("Some children failed");
  expect(output.text).not.toContain("0.0000");
});

test.each(["queued", "running"])("the model follows retry guidance for %s then ends without a Host watcher", async (status) => {
  const output = await trajectory((call) => call.name === "get_research_batch"
    ? batchDetail("factor_evaluation", status) : batchFixtureOutput("factor_evaluation", call));
  expect(output.waits).toEqual([2, 2]);
  expect(output.calls.filter((call) => call.name === "get_research_batch")).toHaveLength(3);
  expect(output.calls.filter((call) => call.name === "render_a2ui"
    && String(call.input.surfaceId).startsWith("batch-progress-"))).toHaveLength(1);
  expect(output.calls.some((call) => call.name === "get_research_run_result")).toBe(false);
  expect(output.text).toContain(`is ${status}`);
  expect(output.text).toContain("Core continues independently");
});

test("a terminal Resume skips stale progress and reads each authoritative Child Result", async () => {
  const request = options(SCRIPTED_FACTOR_BATCH_PROMPT);
  const interrupted = await runScriptedTrajectory(request, (call) => call.name === "get_research_batch"
    ? batchDetail("factor_evaluation", "queued") : batchFixtureOutput("factor_evaluation", call));
  expect(interrupted.text).toContain("Core continues independently");

  followUp(request, SCRIPTED_RESUME_BATCH_PROMPT);
  const resumed = await runScriptedTrajectory(request, (call) => batchFixtureOutput("factor_evaluation", call));

  expect(resumed.calls[0]?.name).toBe("get_research_batch");
  expect(resumed.calls.filter((call) => call.name === "render_a2ui"
    && String(call.input.surfaceId).startsWith("batch-progress-"))).toEqual([]);
  expect(resumed.calls.filter((call) => call.name === "get_research_run_result")
    .map((call) => call.input.run_id)).toEqual(CHILD_IDS);
  expect(resumed.calls.filter((call) => call.name === "render_a2ui"
    && String(call.input.surfaceId).startsWith("batch-results-"))).toHaveLength(1);
  expect(resumed.text).toContain("not a combined Batch Result");
  expect(resumed.calls.length + 1).toBeLessThanOrEqual(9);
});

test("a failed Batch never fabricates child Results", async () => {
  const output = await trajectory((call) => call.name === "get_research_batch"
    ? batchDetail("factor_evaluation", "failed") : batchFixtureOutput("factor_evaluation", call));
  expect(output.calls.some((call) => call.name === "get_research_run_result")).toBe(false);
  expect(output.text).toContain("is failed");
  expect(output.text).not.toContain("0.1200");
});

test.each(["INVALID_CARDINALITY", "DUPLICATE_ITEM_KEY", "RESEARCH_BATCH_EXCEEDS_WORKER_CAPACITY"])("structured %s admission rejection does not invent or retry an admitted Batch", async (code) => {
  const output = await trajectory((call) => call.name === "submit_research_batch"
    ? { outcome: "rejected", replayed: false, issues: [{ code, field: "factors" }] }
    : batchFixtureOutput("factor_evaluation", call));
  expect(output.calls.filter((call) => call.name === "submit_research_batch")).toHaveLength(1);
  expect(output.calls.some((call) => call.name === "get_research_batch")).toBe(false);
  expect(output.text).toContain(code);
  expect(output.text).not.toContain(BATCH_ID);
});

test("transient submission repeats exactly the same request and ordered item keys", async () => {
  const output = await trajectory((call) => call.name === "submit_research_batch" && call.occurrence === 1
    ? { code: "TEMPORARILY_UNAVAILABLE", retry_after_seconds: 3 }
    : batchFixtureOutput("factor_evaluation", call));
  const submissions = output.calls.filter((call) => call.name === "submit_research_batch");
  expect(submissions).toHaveLength(2);
  expect(submissions[1]?.input).toEqual(submissions[0]?.input);
  expect(output.waits).toContain(3);
});

test("an explicitly resumed disconnected admission replays its original command even under a new Agent Run", async () => {
  const request = options(SCRIPTED_FACTOR_BATCH_PROMPT);
  const interrupted = await runScriptedTrajectory(request, (call) => call.name === "submit_research_batch"
    ? { code: "MCP_TRANSIENT" } : batchFixtureOutput("factor_evaluation", call));
  const original = interrupted.calls.find((call) => call.name === "submit_research_batch");
  expect(original).toBeDefined();
  request.prompt.push({ role: "assistant", content: [{ type: "text", text: "Agent Run identity: 00000000-0000-4000-8000-000000000099." }] });
  followUp(request, SCRIPTED_RESUME_BATCH_PROMPT);
  const resumed = await runScriptedTrajectory(request, (call) => batchFixtureOutput("factor_evaluation", call));
  expect(resumed.calls[0]).toEqual(original);
  expect(resumed.calls.filter((call) => call.name === "submit_research_batch")).toHaveLength(1);
  expect(resumed.text).toContain(BATCH_ID);
  // PostgreSQL JSONB may normalize nested object key order. This is still the
  // same successful replay, not another unresolved admission to repeat.
  for (const message of request.prompt) {
    if (message.role !== "assistant") continue;
    for (const part of message.content) {
      if (part.type !== "tool-call" || part.toolName !== "submit_research_batch") continue;
      const input = part.input as Record<string, unknown>;
      if (Array.isArray(input.factors)) {
        input.factors = input.factors.map((item: Record<string, unknown>) =>
          Object.fromEntries(Object.entries(item).reverse()));
      }
      break;
    }
    // Change only the original failed admission, not the successful replay.
    if (message.content.some((part) => part.type === "tool-call" && part.toolName === "submit_research_batch")) break;
  }
  followUp(request, SCRIPTED_RESUME_BATCH_PROMPT);
  const reattached = await runScriptedTrajectory(request, (call) => batchFixtureOutput("factor_evaluation", call));
  expect(reattached.calls.some((call) => call.name === "submit_research_batch")).toBe(false);
});

test("the fixture uses List discovery and clarifies missing comparison intent", async () => {
  const listed = await runScriptedTrajectory(options(SCRIPTED_BATCH_LIST_PROMPT), (call) => batchFixtureOutput("factor_evaluation", call));
  expect(listed.calls.map((call) => call.name)).toEqual(["list_research_batches"]);
  expect(listed.text).toContain(BATCH_ID);
  const clarified = await runScriptedTrajectory(options(SCRIPTED_AMBIGUOUS_BATCH_PROMPT), () => { throw new Error("No Tool needed"); });
  expect(clarified.calls).toEqual([]);
  expect(clarified.text).toMatch(/Which.*compare/);
});

test("a missing discovered capability never becomes a fabricated Tool call", async () => {
  const request = options(SCRIPTED_FACTOR_BATCH_PROMPT);
  request.tools = request.tools?.filter((tool) => tool.name !== "submit_research_batch");
  const output = await runScriptedTrajectory(request, (call) => batchFixtureOutput("factor_evaluation", call));
  expect(output.calls.some((call) => call.name === "submit_research_batch")).toBe(false);
  expect(output.text).toContain("did not provide");
});

test("List errors retain their meaning instead of creating an endless discovery loop", async () => {
  const output = await runScriptedTrajectory(options(SCRIPTED_BATCH_LIST_PROMPT), () => ({ code: "FORBIDDEN" }));
  expect(output.calls).toHaveLength(1);
  expect(output.text).toContain("FORBIDDEN");
});

test.each(["missing-child", "mismatched-result", "missing-metric", "duplicate-ordinal"])("malformed authoritative %s data fails closed", async (scenario) => {
  const output = await trajectory((call) => {
    const value = batchFixtureOutput("factor_evaluation", call);
    if (scenario === "missing-child" && call.name === "get_research_run") delete value.id;
    if (scenario === "mismatched-result" && call.name === "get_research_run_result") value.run_id = CHILD_IDS[1];
    if (scenario === "missing-metric" && call.name === "get_research_run_result") value.factor = {};
    if (scenario === "duplicate-ordinal" && call.name === "get_research_batch") (value.items as Record<string, unknown>[])[1]!.ordinal = 1;
    return value;
  });
  expect(output.text).toContain("incomplete");
  expect(output.calls.filter((call) => call.name === "render_a2ui").some((call) => String(call.input.surfaceId).startsWith("batch-results"))).toBe(false);
});

test.each([false, true])("opaque Result pagination stays on the same child and reports bounded completeness: %s", async (morePages) => {
  const request = options(SCRIPTED_STRATEGY_SWEEP_PROMPT);
  await runScriptedTrajectory(request, (call) => batchFixtureOutput("strategy_sweep", call));
  followUp(request, SCRIPTED_BATCH_OBSERVATIONS_PROMPT);
  const output = await runScriptedTrajectory(request, (call) => ({
    run_id: call.input.run_id, section: call.input.section,
    items: [{ session: `2024-01-${String(call.occurrence + 2).padStart(2, "0")}` }],
    next_cursor: call.occurrence === 3 && !morePages ? null : `opaque-page-${call.occurrence}`,
  }));
  expect(output.calls.map((call) => call.input)).toEqual([
    { run_id: CHILD_IDS[0], section: "strategy_observations", limit: 20 },
    { run_id: CHILD_IDS[0], section: "strategy_observations", limit: 20, cursor: "opaque-page-1" },
    { run_id: CHILD_IDS[0], section: "strategy_observations", limit: 20, cursor: "opaque-page-2" },
  ]);
  expect(output.text).toContain(morePages ? "not a complete series" : "section is complete");
});

test("a repeated pagination cursor stops without an unbounded loop", async () => {
  const request = options(SCRIPTED_STRATEGY_SWEEP_PROMPT);
  await runScriptedTrajectory(request, (call) => batchFixtureOutput("strategy_sweep", call));
  followUp(request, SCRIPTED_BATCH_OBSERVATIONS_PROMPT);
  const output = await runScriptedTrajectory(request, (call) => ({
    run_id: call.input.run_id, section: call.input.section, items: [], next_cursor: "same-cursor",
  }));
  expect(output.calls).toHaveLength(2);
  expect(output.text).toContain("repeated a pagination cursor");
});

test("a renderer is required and invalid progress cannot become an A2UI fact", async () => {
  const request = options(SCRIPTED_FACTOR_BATCH_PROMPT);
  request.tools = request.tools?.filter((tool) => tool.name !== "render_a2ui");
  const unavailable = await runScriptedTrajectory(request, (call) => batchFixtureOutput("factor_evaluation", call));
  expect(unavailable.text).toContain("required render_a2ui capability");
  const invalid = await trajectory((call) => call.name === "get_research_batch"
    ? { ...batchDetail("factor_evaluation"), progress: { completed_factor_tasks: 9, total_factor_tasks: 2 } }
    : batchFixtureOutput("factor_evaluation", call));
  expect(invalid.calls.some((call) => call.name === "render_a2ui")).toBe(false);
});

function options(prompt: string): LanguageModelV3CallOptions {
  return scriptedCallOptions(prompt, [...BATCH_TOOL_NAMES, "render_a2ui"].map((name) => ({
    type: "function", name, description: name,
    inputSchema: { type: "object", properties: {}, additionalProperties: true },
  })));
}

function trajectory(resolve: (call: RecordedToolCall & { occurrence: number }) => unknown) {
  return runScriptedTrajectory(options(SCRIPTED_FACTOR_BATCH_PROMPT), resolve);
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
