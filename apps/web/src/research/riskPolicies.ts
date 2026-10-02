import type { DrawdownInputs } from "./portfolioDrawdown";
import type { TakeProfitTierDraft } from "./takeProfit";

export const riskPolicies = ["stopLoss", "maximumHolding", "takeProfit", "drawdown"] as const;
export type RiskPolicy = typeof riskPolicies[number];
export type RiskPolicySelection = Partial<Record<RiskPolicy, boolean>>;
export type RiskPolicyInputs = DrawdownInputs & {
  stopLossThreshold: string;
  maximumHoldingSessions: string;
  takeProfitTiers: TakeProfitTierDraft[];
  // An absent choice uses the supplied policy's state, including result-to-draft inputs.
  riskPolicySelection?: RiskPolicySelection;
};

export function riskPolicyEnabled(inputs: RiskPolicyInputs, policy: RiskPolicy): boolean {
  const selected = inputs.riskPolicySelection?.[policy];
  if (selected !== undefined) return selected;
  switch (policy) {
    case "stopLoss": return inputs.stopLossThreshold !== "";
    case "maximumHolding": return inputs.maximumHoldingSessions !== "";
    case "takeProfit": return inputs.takeProfitTiers.length > 0;
    case "drawdown": return inputs.drawdownThreshold !== "" || inputs.drawdownMaximumExposure !== "" || inputs.drawdownCooldownSessions !== "";
  }
}

export function activeRiskPolicies(inputs: RiskPolicyInputs): RiskPolicyInputs {
  return {
    ...inputs,
    stopLossThreshold: riskPolicyEnabled(inputs, "stopLoss") ? inputs.stopLossThreshold : "",
    maximumHoldingSessions: riskPolicyEnabled(inputs, "maximumHolding") ? inputs.maximumHoldingSessions : "",
    takeProfitTiers: riskPolicyEnabled(inputs, "takeProfit") ? inputs.takeProfitTiers : [],
    ...(!riskPolicyEnabled(inputs, "drawdown") ? {
      drawdownThreshold: "", drawdownMaximumExposure: "", drawdownCooldownSessions: "",
    } : {}),
  };
}

export function readRiskPolicySelection(value: unknown): RiskPolicySelection | undefined | null {
  if (value === undefined) return undefined;
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  if (Object.entries(value).some(([key, enabled]) => !riskPolicies.includes(key as RiskPolicy) || typeof enabled !== "boolean")) return null;
  return { ...value } as RiskPolicySelection;
}
