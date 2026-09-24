import Decimal from "decimal.js";

export const drawdownFields = ["drawdownThreshold", "drawdownMaximumExposure", "drawdownCooldownSessions"] as const;
export type DrawdownField = typeof drawdownFields[number];
export type DrawdownInputs = Record<DrawdownField, string>;
export type PortfolioDrawdownPolicy = { drawdown_threshold: number; maximum_stock_exposure: number; cooldown_sessions: number };
export const emptyDrawdownInputs = (): DrawdownInputs => ({ drawdownThreshold: "", drawdownMaximumExposure: "", drawdownCooldownSessions: "" });
export function drawdownEnabled(inputs: DrawdownInputs) { return drawdownFields.some(field => inputs[field] !== ""); }
export function drawdownIssues(inputs: DrawdownInputs): { field: DrawdownField; code: "drawdownCooldown" | "drawdownThreshold" | "drawdownExposure" }[] {
  if (!drawdownEnabled(inputs)) return [];
  return drawdownFields.flatMap<{ field: DrawdownField; code: "drawdownCooldown" | "drawdownThreshold" | "drawdownExposure" }>(field => {
    const value = inputs[field];
    if (field === "drawdownCooldownSessions") {
      return /^[0-9]+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) > 0 ? []
        : [{ field, code: "drawdownCooldown" }];
    }
    if (value.length <= 128 && /^[0-9]+(?:\.[0-9]+)?$/.test(value)) {
      const percentage = new Decimal(value), fraction = percentage.div(100).toNumber();
      if (percentage.lte(100) && (field === "drawdownThreshold" ? percentage.gt(0) && fraction > 0 : percentage.gte(0))) return [];
    }
    return [{ field, code: field === "drawdownThreshold" ? "drawdownThreshold" : "drawdownExposure" }];
  });
}
export function drawdownSpec(inputs: DrawdownInputs): PortfolioDrawdownPolicy {
  const issues = drawdownIssues(inputs);
  const number = (field: DrawdownField, divisor: number) => issues.some(issue => issue.field === field)
    ? Number.NaN : new Decimal(inputs[field]).div(divisor).toNumber();
  return { drawdown_threshold: number("drawdownThreshold", 100), maximum_stock_exposure: number("drawdownMaximumExposure", 100), cooldown_sessions: number("drawdownCooldownSessions", 1) };
}
export function drawdownDraft(policy?: PortfolioDrawdownPolicy): DrawdownInputs {
  return policy ? { drawdownThreshold: new Decimal(policy.drawdown_threshold).mul(100).toString(),
    drawdownMaximumExposure: new Decimal(policy.maximum_stock_exposure).mul(100).toString(),
    drawdownCooldownSessions: String(policy.cooldown_sessions) } : emptyDrawdownInputs();
}
