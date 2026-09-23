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
export type BuiltinRiskModule = { kind: "builtin_risk/v1"; stop_loss_threshold: number };
export type FrameworkModules = {
  [Stage in FrameworkStage]: typeof builtinFrameworkModules[Stage] | { kind: "python"; program: PythonProgram }
    | (Stage extends "risk_management" ? BuiltinRiskModule : never);
};

export function builtinModulesDraft(): FrameworkModulesDraft {
  return Object.fromEntries(frameworkStages.map(stage => [stage, {
    kind: "builtin", program: emptyProgramInputs(),
  }])) as FrameworkModulesDraft;
}
export function frameworkSpec(draft: FrameworkModulesDraft, stopLossThreshold = ""): FrameworkModules {
  return Object.fromEntries(frameworkStages.map(stage => [stage, draft[stage].kind === "builtin"
    ? stage === "risk_management" && stopLossThreshold !== ""
      ? { kind: "builtin_risk/v1", stop_loss_threshold: stopLossInputError(stopLossThreshold) ? Number.NaN : new Decimal(stopLossThreshold).div(100).toNumber() }
      : builtinFrameworkModules[stage] : { kind: "python", program: programSpec(draft[stage].program) }])) as FrameworkModules;
}
export function frameworkDraft(modules: FrameworkModules): FrameworkModulesDraft {
  return Object.fromEntries(frameworkStages.map(stage => {
    const module = modules[stage];
    return [stage, (typeof module === "string" || module.kind === "builtin_risk/v1") ? { kind: "builtin", program: emptyProgramInputs() }
      : { kind: "python", program: programDraft(module.program) }];
  })) as FrameworkModulesDraft;
}

export function frozenStopLossPercentage(modules: FrameworkModules): string {
  const risk = modules.risk_management;
  return typeof risk !== "string" && risk.kind === "builtin_risk/v1"
    ? new Decimal(risk.stop_loss_threshold).mul(100).toString() : "";
}
export function stopLossInputError(value: string): string | undefined {
  if (value === "") return;
  if (value.length <= 128 && /^[0-9]+(?:\.[0-9]+)?$/.test(value)) {
    const percentage = new Decimal(value);
    if (percentage.gt(0) && percentage.lt(100) && Number(value) / 100 > 0 && Number(value) / 100 < 1) return;
  }
  return "Enter a stop loss greater than 0% and less than 100%, or leave blank to disable.";
}
