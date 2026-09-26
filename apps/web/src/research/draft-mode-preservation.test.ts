import { describe, expect, it } from "vitest";
import {
  emptyResearchDraft, loadResearchDraft, persistResearchDraft, researchInputIssues, researchSpec,
  selectFrameworkModule, selectResearchKind, selectStrategyMode,
} from "./draft";
import { frameworkStages } from "./frameworkModules";

function frameworkDraft() {
  return { ...selectResearchKind(emptyResearchDraft(), "strategy_backtest"),
    formula: "rank(close)", startDate: "2026-08-03", endDate: "2026-08-28", universe: "top300" };
}

describe("Research mode draft preservation", () => {
  it("retains each Python module while its built-in implementation is selected", () => {
    let draft = frameworkDraft();
    for (const stage of frameworkStages) {
      draft = selectFrameworkModule(draft, stage, "python");
      draft.frameworkModules[stage].program = { programSource: `# ${stage}\ndef decide(context, state, parameters):\n    return {\"output\": None, \"state\": state}`,
        programParameters: "invalid unfinished JSON", programFields: "price.close.adjusted", programHistorySessions: "7" };
    }
    const programs = structuredClone(draft.frameworkModules);
    for (const stage of frameworkStages) draft = selectFrameworkModule(draft, stage, "builtin");
    expect(researchInputIssues(draft)).toEqual([]);
    for (const stage of frameworkStages) {
      expect(draft.frameworkModules[stage].program).toEqual(programs[stage].program);
      draft = selectFrameworkModule(draft, stage, "python");
      expect(draft.frameworkModules[stage]).toEqual(programs[stage]);
    }
    expect(researchInputIssues(draft).map(issue => issue.field)).toEqual(
      frameworkStages.map(stage => `${stage}.programParameters`),
    );
  });

  it("retains built-in Alpha and Portfolio settings without submitting them for Python modules", () => {
    const original = { ...frameworkDraft(), editor: { anchor: 2, head: 8 }, neutralization: "industry",
      holdingsCount: "23", selectionEverySessions: "7", exposureExpression: "0.65",
      weighting: "rank_weight" as const, volatilityWindow: "31", minimumHoldingSessions: "3" };
    let draft = selectFrameworkModule(selectFrameworkModule(original, "alpha", "python"), "portfolio_construction", "python");
    expect(researchSpec(draft)).not.toHaveProperty("formula");
    expect(researchSpec(draft)).not.toHaveProperty("holdings_count");
    draft = selectFrameworkModule(selectFrameworkModule(draft, "alpha", "builtin"), "portfolio_construction", "builtin");
    expect(draft).toMatchObject({ formula: original.formula, editor: original.editor, neutralization: "industry",
      holdingsCount: "23", selectionEverySessions: "7", exposureExpression: "0.65",
      weighting: "rank_weight", volatilityWindow: "31", minimumHoldingSessions: "3" });
    expect(researchSpec(draft)).toEqual(researchSpec(original));
  });

  it("keeps Framework and Direct inputs through research-kind and strategy-mode changes", () => {
    let draft = selectFrameworkModule(frameworkDraft(), "risk_management", "python");
    draft = { ...draft, holdingsCount: "17", initialCashCny: "250000" };
    const framework = structuredClone(draft);
    draft = selectStrategyMode(draft, "direct");
    draft = { ...draft, programSource: "# custom direct source", programParameters: '{"threshold": 3}',
      programFields: "price.open.adjusted", programHistorySessions: "9" };
    draft = selectResearchKind(selectResearchKind(draft, "factor_evaluation"), "strategy_backtest");
    expect(draft.strategyMode).toBe("direct");
    expect(draft).toMatchObject({ programSource: "# custom direct source", programParameters: '{"threshold": 3}',
      programFields: "price.open.adjusted", programHistorySessions: "9", initialCashCny: "250000" });
    draft = selectStrategyMode(draft, "framework");
    expect(draft.formula).toBe(framework.formula);
    expect(draft.frameworkModules).toEqual(framework.frameworkModules);
    expect(draft.holdingsCount).toBe("17");
    draft = selectStrategyMode(draft, "direct");
    expect(draft.programSource).toBe("# custom direct source");
    expect(researchSpec(draft)).not.toHaveProperty("modules");
  });

  it("retains an invalid inactive volatility window while submitting the default for non-inverse weighting", () => {
    const draft = { ...frameworkDraft(), weighting: "inverse_volatility" as const, volatilityWindow: "253" };
    expect(researchInputIssues(draft)).toContainEqual({ field: "volatilityWindow", code: "volatilityRange" });
    for (const weighting of ["equal_weight", "rank_weight"] as const) {
      const switched = { ...draft, weighting };
      expect(researchInputIssues(switched)).toEqual([]);
      expect(researchSpec(switched)).toMatchObject({ weighting, volatility_window: 20 });
      expect(switched.volatilityWindow).toBe("253");
    }
  });

  it("restores inactive module drafts from the same Browser Draft storage key", () => {
    const entries = new Map<string, string>();
    const storage = { getItem: (key: string) => entries.get(key) ?? null,
      setItem: (key: string, value: string) => { entries.set(key, value); } };
    let draft = selectFrameworkModule(frameworkDraft(), "alpha", "python");
    draft.frameworkModules.alpha.program = { programSource: "# retained source", programParameters: "{",
      programFields: "", programHistorySessions: "" };
    draft = selectFrameworkModule(draft, "alpha", "builtin");
    persistResearchDraft(storage, "researcher", "folder", draft);
    const restored = selectFrameworkModule(loadResearchDraft(storage, "researcher", "folder"), "alpha", "python");
    expect(restored.frameworkModules.alpha.program).toEqual({ programSource: "# retained source",
      programParameters: "{", programFields: "", programHistorySessions: "" });
    expect([...entries.keys()]).toEqual(["thesistrace.research-draft.researcher.folder"]);
  });
});
