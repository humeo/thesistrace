import Decimal from "decimal.js";

export type TakeProfitTier = { profit_threshold: number; cumulative_reduction: number };
export type TakeProfitTierDraft = { profitThreshold: string; cumulativeReduction: string };
export type TakeProfitField = `takeProfitTiers.${number}.${keyof TakeProfitTierDraft}`;

export function takeProfitIssues(tiers: TakeProfitTierDraft[]): { field: TakeProfitField; code: "takeProfitThreshold" | "takeProfitReduction" | "takeProfitOrder" }[] {
  const issues: { field: TakeProfitField; code: "takeProfitThreshold" | "takeProfitReduction" | "takeProfitOrder" }[] = [];
  tiers.forEach((tier, index) => {
    for (const key of ["profitThreshold", "cumulativeReduction"] as const) {
      const value = tier[key];
      const numeric = Number(value) / 100;
      if (value.length > 128 || !/^[0-9]+(?:\.[0-9]+)?$/.test(value)
        || !Number.isFinite(numeric) || numeric <= 0 || (key === "cumulativeReduction" && numeric > 1)) {
        issues.push({ field: `takeProfitTiers.${index}.${key}`, code: key === "profitThreshold"
          ? "takeProfitThreshold" : "takeProfitReduction" });
      } else if (index > 0 && numeric <= Number(tiers[index - 1][key]) / 100) {
        issues.push({ field: `takeProfitTiers.${index}.${key}`, code: "takeProfitOrder" });
      }
    }
  });
  return issues;
}

export function takeProfitSpec(tiers: TakeProfitTierDraft[]): TakeProfitTier[] {
  const issues = takeProfitIssues(tiers);
  const percentage = (value: string, index: number, key: keyof TakeProfitTierDraft) =>
    issues.some(issue => issue.field === `takeProfitTiers.${index}.${key}`) ? Number.NaN : new Decimal(value).div(100).toNumber();
  return tiers.map((tier, index) => ({
    profit_threshold: percentage(tier.profitThreshold, index, "profitThreshold"),
    cumulative_reduction: percentage(tier.cumulativeReduction, index, "cumulativeReduction"),
  }));
}

export function takeProfitDraft(tiers: TakeProfitTier[]): TakeProfitTierDraft[] {
  return tiers.map(tier => ({ profitThreshold: new Decimal(tier.profit_threshold).mul(100).toString(),
    cumulativeReduction: new Decimal(tier.cumulative_reduction).mul(100).toString() }));
}

export function readTakeProfitDraft(value: unknown): TakeProfitTierDraft[] | null {
  if (!Array.isArray(value) || value.length > 100) return null;
  if (value.some(tier => !tier || typeof tier !== "object" || Array.isArray(tier)
    || Object.keys(tier).length !== 2 || typeof tier.profitThreshold !== "string"
    || typeof tier.cumulativeReduction !== "string"
    || tier.profitThreshold.length > 128 || tier.cumulativeReduction.length > 128)) return null;
  return value.map(tier => ({ profitThreshold: tier.profitThreshold, cumulativeReduction: tier.cumulativeReduction }));
}
