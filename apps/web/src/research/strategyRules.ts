import Decimal from "decimal.js";
import type { AlphaCatalog } from "../alphaCatalog";

export type ScoringRule = { kind: "momentum" | "reversal"; sessions: string };

export function scoringRuleFormula(rule: ScoringRule): string {
  const change = `close / lag(close, ${rule.sessions}) - 1`;
  return rule.kind === "reversal" ? `-(${change})` : change;
}

export function readScoringRule(formula: string): ScoringRule | null {
  const match = /^(?:-\()?close \/ lag\(close, (-?[0-9]*(?:\.[0-9]*)?)\) - 1\)?$/.exec(formula);
  if (!match) return null;
  const rule: ScoringRule = { kind: formula.startsWith("-(") ? "reversal" : "momentum", sessions: match[1] };
  return scoringRuleFormula(rule) === formula ? rule : null;
}

export function supportsScoringRules(catalog: AlphaCatalog): boolean {
  return catalog.fields.some(field => field.identifier === "close" && field.field_id === "price.close.adjusted")
    && catalog.builtins.some(builtin => builtin.identifier === "lag");
}

export function exposurePercentage(expression: string): string | null {
  if (!/^-?[0-9]+(?:\.[0-9]+)?$/.test(expression.trim())) return null;
  return new Decimal(expression.trim()).mul(100).toString();
}

export function percentageExposure(value: string): string {
  if (value === "" || !/^-?[0-9]+(?:\.[0-9]*)?$/.test(value)) return "";
  return new Decimal(value).div(100).toString();
}
