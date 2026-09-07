import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { AGENT_FAILURE_CODES } from "@thesistrace/contracts/agent-failure";
import {
  evalBatchWorkerFailure, evalFailureSource, evalStartupRegistry, evalToolCapabilities, maximumEvalTurnCostUsd,
  parseResearchEvalCandidates, parseResearchEvalCorpus, readResearchEvalControls, researchEvalPasses,
  researchEvalRepetitions, summarizeResearchEval, usageCostUsd, validateEvalObservation,
  type ResearchEvalObservation,
} from "./research-eval.js";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../evals/${name}.json`, import.meta.url), "utf8"));
const corpus = parseResearchEvalCorpus(read("research-corpus"));
const candidates = parseResearchEvalCandidates(read("research-candidates"));
const candidate = candidates.candidates[0]!;

function completeObservations(repetitions: number = candidates.qualification_repetitions): ResearchEvalObservation[] {
  return Array.from({ length: repetitions }, (_, index) => corpus.cases.map((testCase) => ({
    case_id: testCase.id, repetition: index + 1, succeeded: true,
    checks: { artifact: true, required_tools: true, forbidden_tools: true, ownership: true, conversation: true, terminal: true, within_time: true, within_cost: true, usage_complete: true },
    failure_source: null, duration_ms: 1000 + index * 100, estimated_cost_usd: 0.01,
    title_cost_upper_bound_usd: 0.02, runs: Array.from({ length: testCase.messages.length }, () => ({
      run_id: "dc39ed24-435a-40e2-bf99-c3a89bb1817c", thread_id: "433643b2-5aeb-42bc-bbff-f5db8a09f706",
      status: "completed" as const, error_category: null, step_count: 4, duration_ms: 1000,
      token_usage: { reported: true as const, inputTokens: { total: 1000, cacheRead: 0, noCache: 1000, cacheWrite: 0 }, outputTokens: { total: 100, reasoning: 50, text: 50 } },
    })),
    tool_calls: 5, invalid_tool_calls: 0, forbidden_tool_calls: 0, tool_errors: 0, tool_retries: 0,
    admission_correction: testCase.outcome === "admission-repaired-factor" ? true : null, artifact_ids: [],
  }))).flat();
}

describe("fixed real-model evaluation contract", () => {
  it("requires all eleven distinct outcomes, unique identities and a single clarification", () => {
    expect(corpus.cases).toHaveLength(11);
    expect(() => parseResearchEvalCorpus({ ...corpus, cases: corpus.cases.slice(1) })).toThrow("CORPUS_INVALID");
    expect(() => parseResearchEvalCorpus({ ...corpus, cases: [...corpus.cases, corpus.cases[0]] })).toThrow("CORPUS_INVALID");
    expect(() => parseResearchEvalCorpus({ ...corpus, prompt: "private-canary" })).toThrow("CORPUS_INVALID");
    const fixture = JSON.parse(readFileSync(new URL("../../../tests/fixtures/tushare-financial-product-replay.json", import.meta.url), "utf8"));
    const prefix = fixture.snapshot.calendar_sse.slice(0, 2).map((item: { cal_date: string }) => item.cal_date.replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3"));
    expect(prefix).toEqual([corpus.admission_window.requested_start, corpus.admission_window.corrected_start]);
  });
  it("never qualifies a scripted provider or expands an unregistered effort", () => {
    expect(() => parseResearchEvalCandidates({ ...candidates, candidates: [{ ...candidate, provider_adapter: "scripted" }] })).toThrow("CONFIG_INVALID");
    expect(() => evalStartupRegistry(candidate, "minimal")).toThrow("CONFIG_INVALID");
    expect(evalStartupRegistry(candidate, "high").models[0]).toMatchObject({ enabled: true, reasoning_efforts: ["high"], secret_env: "THESISTRACE_AGENT_OPENAI_API_KEY" });
    expect(maximumEvalTurnCostUsd(candidate)).toBeGreaterThan(4);
  });
  it("runs one baseline sample per case and reserves repeated trials for qualification", () => {
    const splitRepetitions = {
      baseline_repetitions: 1,
      qualification_repetitions: 3,
      candidates: candidates.candidates,
    };
    expect(parseResearchEvalCandidates(splitRepetitions)).toMatchObject({
      baseline_repetitions: 1,
      qualification_repetitions: 3,
    });
    expect(researchEvalRepetitions(parseResearchEvalCandidates(splitRepetitions), "baseline")).toBe(1);
    expect(researchEvalRepetitions(parseResearchEvalCandidates(splitRepetitions), "qualification")).toBe(3);
    expect(() => parseResearchEvalCandidates({ ...splitRepetitions, repetitions: 3 }))
      .toThrow("CONFIG_INVALID");
    expect(() => parseResearchEvalCandidates({ ...splitRepetitions, qualification_repetitions: 4 }))
      .toThrow("CONFIG_INVALID");
  });
  it("keeps unknown usage unknown and prices known cached input explicitly", () => {
    expect(usageCostUsd({ reported: false }, candidate.pricing)).toBeNull();
    const usage = completeObservations()[0]!.runs[0]!.token_usage;
    if (!usage.reported) throw new Error("Fixture invalid");
    expect(usageCostUsd({ ...usage, inputTokens: { ...usage.inputTokens, cacheRead: 500 } }, candidate.pricing)).toBeCloseTo(0.00045, 8);
    expect(usageCostUsd({ ...usage, inputTokens: { ...usage.inputTokens, total: null } }, candidate.pricing)).toBeNull();
  });
  it("labels Luna accounting as a published-price upper bound including long context and cache writes", () => {
    expect(candidate.pricing).toMatchObject({
      basis: "published-standard-upper-bound",
      input_usd_per_million: 0.5,
      cached_input_usd_per_million: 0.04,
      output_usd_per_million: 1.8,
    });
    expect(usageCostUsd({ reported: true,
      inputTokens: { total: 300000, noCache: 0, cacheRead: 0, cacheWrite: 300000 },
      outputTokens: { total: 10, text: 5, reasoning: 5 },
    }, candidate.pricing)).toBeCloseTo(0.150018, 8);
    expect(maximumEvalTurnCostUsd(candidate)).toBe(Number.POSITIVE_INFINITY);
  });
  it("pins the measured latency allowance only for the two complex workflows", () => {
    expect(candidate.thresholds.max_p95_duration_ms).toBe(250_000);
    const durations = Object.fromEntries(corpus.cases.map((item) => [item.id, item.max_duration_ms]));
    expect(durations["strategy-backtest"]).toBe(250_000);
    expect(durations["alpha-comparison-batch"]).toBe(250_000);
    expect(corpus.cases.filter((item) => !["strategy-backtest", "alpha-comparison-batch"].includes(item.id)))
      .toHaveLength(9);
    expect(corpus.cases.filter((item) => !["strategy-backtest", "alpha-comparison-batch"].includes(item.id))
      .every((item) => item.max_duration_ms === 180_000)).toBe(true);
  });
  it("requires an explicit operator phase and a bounded complete-case spending reserve", () => {
    // A finite approval cannot reserve an unbounded number of provider calls.
    expect(() => readResearchEvalControls(candidate, "baseline", "20")).toThrow("CONFIG_INVALID");
    for (const budget of [undefined, "", "NaN", "-1", "1", "101", "1e2", "20-secret-canary"]) {
      expect(() => readResearchEvalControls(candidate, "baseline", budget)).toThrow("CONFIG_INVALID");
    }
    expect(() => readResearchEvalControls(candidate, undefined, "20")).toThrow("CONFIG_INVALID");
    expect(() => readResearchEvalControls(candidate, "scripted", "20")).toThrow("CONFIG_INVALID");
  });
  it("recognizes the native A2UI renderer without adding an MCP capability or permitting mutations", () => {
    const inventory = ["get_research_context", "submit_research_run"];
    expect(evalToolCapabilities(["get_research_context", "render_a2ui"], inventory, [])).toEqual({ invalid: 0, forbidden: 0 });
    expect(evalToolCapabilities(["invented_tool", "cancel_research_run", "refresh_daily_track", "submit_research_run"], inventory, ["submit_research_run"]))
      .toEqual({ invalid: 3, forbidden: 3 });
  });
  it("summarizes the fixed denominator without treating missing or duplicate attempts as passes", () => {
    const observations = completeObservations();
    const summary = summarizeResearchEval(corpus, 3, observations);
    expect(summary).toMatchObject({ complete: true, task_success_rate: 1, usage_complete: true, total_agent_steps: 144, admission_correction_success_rate: 1 });
    expect(summary.duration_p50_ms).toBe(1100);
    expect(summary.duration_p95_ms).toBe(1200);
    expect(researchEvalPasses(summary, candidate)).toBe(true);
    const incomplete = summarizeResearchEval(corpus, 3, observations.slice(1));
    expect(incomplete.task_success_rate).toBeLessThan(1);
    expect(researchEvalPasses(incomplete, candidate)).toBe(false);
    expect(() => summarizeResearchEval(corpus, 3, [...observations, observations[0]!])).toThrow("REPORT_INVALID");
  });
  it("treats one observation of every case as a complete baseline", () => {
    const repetitions = researchEvalRepetitions(candidates, "baseline");
    const summary = summarizeResearchEval(corpus, repetitions, completeObservations(repetitions));
    expect(summary).toMatchObject({
      complete: true,
      expected_cases: 11,
      observed_cases: 11,
      task_success_rate: 1,
      minimum_case_success_rate: 1,
      repetition_success_rates: [1],
    });
  });
  it("rejects leaked fields and inconsistent success claims before report persistence", () => {
    const observation = completeObservations()[0]!;
    expect(() => validateEvalObservation({ ...observation, prompt: "private-canary" })).toThrow("REPORT_INVALID");
    expect(() => validateEvalObservation({ ...observation, runs: [{ ...observation.runs[0], messages: ["private"] }] })).toThrow("REPORT_INVALID");
    expect(() => validateEvalObservation({ ...observation, checks: { ...observation.checks, ownership: false } })).toThrow("REPORT_INVALID");
    expect(() => validateEvalObservation({ ...observation, runs: [{ ...observation.runs[0], token_usage: { reported: false } }] })).toThrow("REPORT_INVALID");
    expect(() => validateEvalObservation({ ...observation, runs: [], estimated_cost_usd: 0 })).toThrow("REPORT_INVALID");
  });
  it("keeps late completed cases in accounting but does not qualify their latency", () => {
    const observations = completeObservations().map((item) => item.case_id === "alpha-comparison-batch"
      ? validateEvalObservation({ ...item, succeeded: false, duration_ms: 240_000,
        failure_source: evalFailureSource(null), checks: { ...item.checks, within_time: false } }) : item);
    const summary = summarizeResearchEval(corpus, 3, observations);
    expect(summary).toMatchObject({ complete: true, usage_complete: true, duration_p95_ms: 240_000 });
    expect(summary.failures["model-quality"]).toBe(3);
    expect(summary.failures["eval-infrastructure"]).toBe(0);
    expect(summary.estimated_primary_cost_usd).toBeCloseTo(0.33);
    expect(researchEvalPasses(summary, candidate)).toBe(false);
  });
  it("does not omit a repair measurement or one half of a clarification from a complete report", () => {
    const observations = completeObservations();
    const repair = observations.findIndex((item) => item.admission_correction !== null);
    const clarification = observations.findIndex((item) => item.runs.length === 2);
    expect(() => summarizeResearchEval(corpus, 3, observations.map((item, index) => index === repair
      ? { ...item, admission_correction: null } : item))).toThrow("REPORT_INVALID");
    expect(() => summarizeResearchEval(corpus, 3, observations.map((item, index) => index === clarification
      ? { ...item, runs: item.runs.slice(0, 1) } : item))).toThrow("REPORT_INVALID");
  });
  it("fails qualification on unknown accounting, forbidden capabilities or excessive variance", () => {
    const observations = completeObservations();
    const summary = summarizeResearchEval(corpus, 3, observations);
    for (const failed of [
      { ...summary, usage_complete: false }, { ...summary, forbidden_tool_rate: 0.001 },
      { ...summary, invalid_tool_rate: 0.001 }, { ...summary, repetition_success_variance: 0.1 },
      { ...summary, admission_correction_success_rate: 0.5 },
      { ...summary, ownership_failures: 1 },
    ]) expect(researchEvalPasses(failed, candidate)).toBe(false);
    observations[0] = { ...observations[0]!, succeeded: false, failure_source: "provider", estimated_cost_usd: null, checks: { ...observations[0]!.checks, usage_complete: false, within_cost: false } };
    expect(summarizeResearchEval(corpus, 3, observations).estimated_primary_cost_usd).toBeNull();
  });
  it("separates infrastructure, admission and provider failure from task quality", () => {
    expect(evalFailureSource("PROVIDER_RATE_LIMIT")).toBe("provider");
    expect(evalFailureSource("MCP_TRANSIENT")).toBe("mcp");
    expect(evalFailureSource("TOOL_REJECTION")).toBe("core-admission");
    expect(evalFailureSource("TOOL_ERROR")).toBe("mcp");
    expect(evalFailureSource("AGENT_LIMIT")).toBe("model-quality");
    expect(evalFailureSource("AGENT_CAPACITY")).toBe("eval-infrastructure");
  });
  it.each(["PROVIDER_TIMEOUT", "MCP_TRANSIENT", "TOOL_REJECTION"] as const)("retains known %s failures independently of missing accounting", (code) => {
    expect(evalFailureSource(code, { workerFailure: false, transportFailed: true, usageComplete: false }))
      .toBe(evalFailureSource(code));
    expect(evalFailureSource(null, { workerFailure: false, transportFailed: false, usageComplete: false })).toBe("eval-infrastructure");
  });
  it.each(AGENT_FAILURE_CODES)("attributes explicit terminal %s before a pre-existing failed Worker fixture", (code) => {
    const source = evalFailureSource(code);
    expect(source).not.toBe("dataset-worker");
    expect(evalFailureSource(code, { workerFailure: true, transportFailed: false, usageComplete: false })).toBe(source);
  });
  it("attributes actual partially failed Batch outcomes to Dataset/Worker, not model quality", () => {
    expect(evalBatchWorkerFailure("completed_with_failures")).toBe(true);
    expect(evalBatchWorkerFailure("failed")).toBe(true);
    for (const status of ["queued", "running", "cancelling", "cancelled", "succeeded"]) {
      expect(evalBatchWorkerFailure(status)).toBe(false);
    }
  });
});
