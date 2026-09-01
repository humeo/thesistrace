import { describe, expect, it } from "vitest";

import {
  parseSessionTitleEvalCorpus,
  sessionTitleMeetsEvalOutcome,
  summarizeSessionTitleEval,
} from "./session-title-eval.js";

const testCase = {
  forbidden_terms: ["private-canary"],
  id: "quality-alpha",
  message: "Build a quality Alpha.",
  required_terms: ["quality"],
};

describe("Session title real-model Eval contract", () => {
  it("accepts semantic variation without matching exact title prose", () => {
    expect(sessionTitleMeetsEvalOutcome("Quality signal research", testCase)).toBe(true);
    expect(sessionTitleMeetsEvalOutcome("Alpha quality screen", testCase)).toBe(true);
    expect(sessionTitleMeetsEvalOutcome("PRIVATE-CANARY quality", testCase)).toBe(false);
    expect(sessionTitleMeetsEvalOutcome("Unrelated research", testCase)).toBe(false);
  });

  it("requires every case-specific concept instead of accepting a generic Alpha", () => {
    const specificCase = {
      ...testCase,
      required_terms: ["volatility", "quality"],
    };

    expect(sessionTitleMeetsEvalOutcome("Alpha", specificCase)).toBe(false);
    expect(sessionTitleMeetsEvalOutcome("Low-volatility quality research", specificCase))
      .toBe(true);
  });

  it("validates one fixed, unique, bounded corpus", () => {
    expect(parseSessionTitleEvalCorpus({
      cases: [testCase],
      version: "session-title-v1",
    }).cases).toHaveLength(1);
    expect(() => parseSessionTitleEvalCorpus({
      cases: [testCase, testCase],
      version: "session-title-v1",
    })).toThrow("SESSION_TITLE_EVAL_CORPUS_INVALID");
  });

  it("reports success, cost, P95 latency, and run-to-run variance", () => {
    expect(summarizeSessionTitleEval([{
      caseId: "quality-alpha",
      durationMs: 10,
      estimatedCostUsd: 0.001,
      inputTokens: 10,
      outputTokens: 5,
      succeeded: true,
      titleCharacters: 14,
    }, {
      caseId: "quality-alpha",
      durationMs: 30,
      estimatedCostUsd: 0.002,
      inputTokens: 20,
      outputTokens: 7,
      succeeded: false,
      titleCharacters: 10,
    }])).toEqual({
      duration_p50_ms: 10,
      duration_p95_ms: 30,
      duration_stddev_ms: 10,
      estimated_cost_usd: 0.003,
      input_tokens: 30,
      invocation_count: 2,
      output_tokens: 12,
      success_rate: 0.5,
      success_variance: 0.25,
      title_length_stddev: 2,
      usage_complete: true,
    });
  });

  it("does not turn an unreported paid invocation into zero cost", () => {
    expect(summarizeSessionTitleEval([{
      caseId: "quality-alpha", durationMs: 10, estimatedCostUsd: null,
      inputTokens: null, outputTokens: null, succeeded: false, titleCharacters: 0,
    }])).toMatchObject({ usage_complete: false, estimated_cost_usd: null, input_tokens: null, output_tokens: null });
  });
});
