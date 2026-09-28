import { describe, expect, it } from "vitest";
import { exposurePercentage, percentageExposure, readScoringRule, scoringRuleFormula } from "./strategyRules";
import { emptyResearchDraft, researchSpec } from "./draft";

describe("rules-first strategy definition", () => {
  it("submits the selected momentum rule through the current framework contract", () => {
    const draft = { ...emptyResearchDraft(), researchKind: "strategy_backtest" as const,
      formula: scoringRuleFormula({ kind: "momentum", sessions: "20" }),
      exposureExpression: percentageExposure("60"), stopLossThreshold: "10",
      universe: "top300", startDate: "2026-08-03", endDate: "2026-08-05" };
    expect(researchSpec(draft)).toMatchObject({
      strategy_mode: "framework", formula: "close / lag(close, 20) - 1",
      exposure_expression: "0.6",
      modules: { risk_management: { kind: "builtin_risk/v1", stop_loss_threshold: 0.1 } },
    });
  });

  it("recovers built-in rules from frozen formulas without treating custom code as a preset", () => {
    expect(readScoringRule("-(close / lag(close, 5) - 1)")).toEqual({ kind: "reversal", sessions: "5" });
    for (const formula of ["close", "close / lag(close, 20) - 1 + volume", "-close / lag(close, 5) - 1", "close / lag(close, 5) - 1)"]) {
      expect(readScoringRule(formula)).toBeNull();
    }
  });

  it("converts precise percentages without rounding or disguising an invalid allocation", () => {
    expect(percentageExposure("33.33")).toBe("0.3333");
    expect(exposurePercentage("0.3333")).toBe("33.33");
    expect(exposurePercentage("1.0")).toBe("100");
    expect(exposurePercentage("if_else(universe_return(1) > 0, 1, 0.3)")).toBeNull();
    expect(exposurePercentage("1.5")).toBe("150");
    expect(percentageExposure("-5")).toBe("-0.05");
    expect(exposurePercentage("-0.05")).toBe("-5");
    expect(percentageExposure("")).toBe("");
  });

  it("never includes configured form rules when the complete Python strategy is active", () => {
    const draft = { ...emptyResearchDraft(), researchKind: "strategy_backtest" as const, strategyMode: "direct" as const,
      formula: scoringRuleFormula({ kind: "momentum", sessions: "20" }), stopLossThreshold: "10" };
    const spec = researchSpec(draft);
    expect(spec).toHaveProperty("strategy_mode", "direct");
    expect(spec).not.toHaveProperty("formula");
    expect(spec).not.toHaveProperty("modules");
  });
});
