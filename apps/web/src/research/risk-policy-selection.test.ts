import { describe, expect, it } from "vitest";
import {
  acceptPendingResearchRun, beginResearchRun, emptyResearchDraft, hasUnexecutedChanges,
  loadResearchDraft, persistResearchDraft, researchInputIssues, researchInputs, researchSpec, selectRiskPolicy,
} from "./draft";
import { riskPolicies, riskPolicyEnabled } from "./riskPolicies";

const valid = () => ({ ...emptyResearchDraft(), researchKind: "strategy_backtest" as const,
  formula: "close", startDate: "2026-08-03", endDate: "2026-08-04", universe: "top300" });
const configured = () => ({ ...valid(), stopLossThreshold: "10", maximumHoldingSessions: "20",
  takeProfitTiers: [{ profitThreshold: "20", cumulativeReduction: "50" }],
  drawdownThreshold: "10", drawdownMaximumExposure: "30", drawdownCooldownSessions: "5" });
function storage() {
  const items = new Map<string, string>();
  return { getItem: (key: string) => items.get(key) ?? null, setItem: (key: string, value: string) => { items.set(key, value); } };
}

describe("Optional risk policy selection", () => {
  it("starts off and enables supplied policies without changing their values", () => {
    for (const policy of riskPolicies) {
      expect(riskPolicyEnabled(valid(), policy)).toBe(false);
      expect(riskPolicyEnabled(configured(), policy)).toBe(true);
    }
  });

  it("retains disabled policy parameters but omits all of them from the run", () => {
    let current = configured();
    for (const policy of riskPolicies) current = selectRiskPolicy(current, policy, false) as typeof current;
    expect(current.stopLossThreshold).toBe("10");
    expect(current.takeProfitTiers).toEqual([{ profitThreshold: "20", cumulativeReduction: "50" }]);
    expect(researchSpec(current)).toHaveProperty("modules.risk_management", "no_risk/v1");
    const store = storage();
    persistResearchDraft(store, "researcher", "folder", current);
    const restored = loadResearchDraft(store, "researcher", "folder");
    expect(restored.drawdownMaximumExposure).toBe("30");
    expect(riskPolicies.map(policy => riskPolicyEnabled(restored, policy))).toEqual([false, false, false, false]);
    expect(researchSpec(selectRiskPolicy(restored, "stopLoss", true))).toHaveProperty("modules.risk_management", {
      kind: "builtin_risk/v1", stop_loss_threshold: 0.1,
    });
  });

  it("requires values only for enabled policies, including an empty drawdown rule", () => {
    for (const policy of riskPolicies) {
      const enabled = selectRiskPolicy(valid(), policy, true);
      expect(researchInputIssues(enabled).length).toBeGreaterThan(0);
      expect(researchInputIssues(selectRiskPolicy(enabled, policy, false))).toEqual([]);
    }
    const disabled = selectRiskPolicy({ ...configured(), maximumHoldingSessions: "0", minimumHoldingSessions: "50" }, "maximumHolding", false);
    expect(researchInputIssues(disabled)).toEqual([]);
  });

  it("preserves the accepted baseline and pending request while switching off cached policies", () => {
    const store = storage();
    const admitted = beginResearchRun(configured(), "folder", () => "first");
    let current = acceptPendingResearchRun(admitted.draft, "first");
    current = selectRiskPolicy(current, "stopLoss", false);
    persistResearchDraft(store, "researcher", "folder", current);
    current = loadResearchDraft(store, "researcher", "folder");
    expect(hasUnexecutedChanges(current)).toBe(true);
    current = selectRiskPolicy(current, "stopLoss", true);
    expect(hasUnexecutedChanges(current)).toBe(false);
    const pending = beginResearchRun(current, "folder", () => "second");
    persistResearchDraft(store, "researcher", "folder", pending.draft);
    current = loadResearchDraft(store, "researcher", "folder");
    expect(beginResearchRun(current, "folder", () => "unused").command.request_id).toBe("second");
    expect(researchInputs(current).riskPolicySelection).toEqual({ stopLoss: true, maximumHolding: true, takeProfit: true, drawdown: true });
  });
});
