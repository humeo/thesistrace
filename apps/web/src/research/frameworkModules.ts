import { takeProfitSpec, type TakeProfitTier, type TakeProfitTierDraft } from "./takeProfit";
import Decimal from "decimal.js";
import { emptyProgramInputs, programDraft, programSpec, type ProgramInputs, type PythonProgram } from "./pythonStrategy";

export const builtinFrameworkModules = {
  universe_selection: "dataset_universe/v1",
  alpha: "alpha_formula/v1",
  portfolio_construction: "periodic_top_n/v1",
  risk_management: "no_risk/v1",
} as const;
export type FrameworkStage = keyof typeof builtinFrameworkModules;
export const frameworkStages = Object.keys(builtinFrameworkModules) as FrameworkStage[];
export const frameworkStageLabels: Record<FrameworkStage, string> = {
  universe_selection: "Universe Selection", alpha: "Alpha / Signals",
  portfolio_construction: "Portfolio Construction", risk_management: "Risk Management",
};
export type ModuleDraft = { kind: "builtin" | "python"; program: ProgramInputs };
export type FrameworkModulesDraft = Record<FrameworkStage, ModuleDraft>;
export type BuiltinRiskModule = { kind: "builtin_risk/v1"; stop_loss_threshold?: number; maximum_holding_sessions?: number; take_profit_tiers?: TakeProfitTier[] };
export type BuiltinPortfolioModule = { kind: "periodic_top_n/v1"; minimum_holding_sessions: number };
export type FrameworkModules = {
  [Stage in FrameworkStage]: typeof builtinFrameworkModules[Stage] | { kind: "python"; program: PythonProgram }
    | (Stage extends "risk_management" ? BuiltinRiskModule : never)
    | (Stage extends "portfolio_construction" ? BuiltinPortfolioModule : never);
};

export function builtinModulesDraft(): FrameworkModulesDraft {
  return Object.fromEntries(frameworkStages.map(stage => [stage, {
    kind: "builtin", program: emptyProgramInputs(),
  }])) as FrameworkModulesDraft;
}
export function frameworkSpec(draft: FrameworkModulesDraft, policies: {
  stopLossThreshold: string; maximumHoldingSessions: string; minimumHoldingSessions: string; takeProfitTiers: TakeProfitTierDraft[];
}): FrameworkModules {
  const { stopLossThreshold, maximumHoldingSessions, minimumHoldingSessions, takeProfitTiers } = policies;
  return Object.fromEntries(frameworkStages.map(stage => [stage, draft[stage].kind === "builtin"
    ? stage === "portfolio_construction" && minimumHoldingSessions !== ""
      ? { kind: "periodic_top_n/v1", minimum_holding_sessions: holdingSessionsInputError(minimumHoldingSessions) ? Number.NaN : Number(minimumHoldingSessions) }
    : stage === "risk_management" && (stopLossThreshold !== "" || maximumHoldingSessions !== "" || takeProfitTiers.length > 0)
      ? { kind: "builtin_risk/v1",
        ...(takeProfitTiers.length ? { take_profit_tiers: takeProfitSpec(takeProfitTiers) } : {}),
        ...(stopLossThreshold !== "" ? { stop_loss_threshold: stopLossInputError(stopLossThreshold) ? Number.NaN : new Decimal(stopLossThreshold).div(100).toNumber() } : {}),
        ...(maximumHoldingSessions !== "" ? { maximum_holding_sessions: holdingSessionsInputError(maximumHoldingSessions) ? Number.NaN : Number(maximumHoldingSessions) } : {}) }
      : builtinFrameworkModules[stage] : { kind: "python", program: programSpec(draft[stage].program) }])) as FrameworkModules;
}
export function frameworkDraft(modules: FrameworkModules): FrameworkModulesDraft {
  return Object.fromEntries(frameworkStages.map(stage => {
    const module = modules[stage];
    return [stage, (typeof module === "string" || module.kind !== "python") ? { kind: "builtin", program: emptyProgramInputs() }
      : { kind: "python", program: programDraft(module.program) }];
  })) as FrameworkModulesDraft;
}

export function frozenStopLossPercentage(modules: FrameworkModules): string {
  const risk = modules.risk_management;
  return typeof risk !== "string" && risk.kind === "builtin_risk/v1" && risk.stop_loss_threshold !== undefined
    ? new Decimal(risk.stop_loss_threshold).mul(100).toString() : "";
}
export function frozenMaximumHoldingSessions(modules: FrameworkModules): string {
  const risk = modules.risk_management;
  return typeof risk !== "string" && risk.kind === "builtin_risk/v1" && risk.maximum_holding_sessions !== undefined
    ? String(risk.maximum_holding_sessions) : "";
}
export function holdingSessionsInputError(value: string): string | undefined {
  if (value === "" || (/^[0-9]+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) > 0)) return;
  return "Enter a positive whole number of trading sessions, or leave blank to disable.";
}
export function stopLossInputError(value: string): string | undefined {
  if (value === "") return;
  if (value.length <= 128 && /^[0-9]+(?:\.[0-9]+)?$/.test(value)) {
    const percentage = new Decimal(value);
    if (percentage.gt(0) && percentage.lt(100) && Number(value) / 100 > 0 && Number(value) / 100 < 1) return;
  }
  return "Enter a stop loss greater than 0% and less than 100%, or leave blank to disable.";
}

export function frozenMinimumHoldingSessions(modules: FrameworkModules): string {
  const portfolio = modules.portfolio_construction;
  return typeof portfolio !== "string" && portfolio.kind === "periodic_top_n/v1"
    ? String(portfolio.minimum_holding_sessions) : "";
}
