import { describe, expect, it } from "vitest";
import { costInputError } from "./simulationCosts";
import { emptyResearchDraft, researchSpec, researchInputIssues, selectResearchKind,
  selectStrategyMode, persistResearchDraft, loadResearchDraft } from "./draft";

describe("frozen simulation costs", () => {
  it("compares the slippage ceiling without rounding decimal input to a JS number", () => {
    expect(costInputError("slippage_bps", "9999.99999999999999999")).toBeUndefined();
    expect(costInputError("slippage_bps", "10000.00000000000000001")).toBeDefined();
    expect(costInputError("commission_rate_all_in", "-0.000000000000000001")).toBeDefined();
  });
  it("submits the same explicit assumptions in both strategy modes", () => {
    const framework = selectResearchKind(emptyResearchDraft(), "strategy_backtest");
    expect(researchSpec(framework)).toMatchObject({ costs: {
      commission_rate_all_in: "0.0003", commission_min_cny: "5",
      stamp_duty_sell_rate: "0.0005", transfer_fee_rate: "0.00001", slippage_bps: "0",
    } });
    const edited = { ...framework, costs: { ...framework.costs, slippage_bps: "10" } };
    expect(researchSpec(selectStrategyMode(edited, "direct"))).toMatchObject({ costs: edited.costs });
  });

  it("keeps incomplete costs editable in browser storage and locates their errors", () => {
    const draft = selectResearchKind(emptyResearchDraft(), "strategy_backtest");
    draft.costs = { ...draft.costs, commission_min_cny: "", slippage_bps: "10000" };
    const values = new Map<string, string>();
    const storage = { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); } };
    persistResearchDraft(storage, "researcher", "folder", draft);
    expect(loadResearchDraft(storage, "researcher", "folder").costs).toEqual(draft.costs);
    expect(researchInputIssues(draft)).toEqual(expect.arrayContaining([
      expect.objectContaining({ field: "costs.commission_min_cny" }),
      expect.objectContaining({ field: "costs.slippage_bps" }),
    ]));
  });
});
