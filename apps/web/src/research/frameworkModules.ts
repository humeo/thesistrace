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
export type FrameworkModules = {
  [Stage in FrameworkStage]: typeof builtinFrameworkModules[Stage] | { kind: "python"; program: PythonProgram };
};

export function builtinModulesDraft(): FrameworkModulesDraft {
  return Object.fromEntries(frameworkStages.map(stage => [stage, {
    kind: "builtin", program: emptyProgramInputs(),
  }])) as FrameworkModulesDraft;
}
export function frameworkSpec(draft: FrameworkModulesDraft): FrameworkModules {
  return Object.fromEntries(frameworkStages.map(stage => [stage, draft[stage].kind === "builtin"
    ? builtinFrameworkModules[stage] : { kind: "python", program: programSpec(draft[stage].program) }])) as FrameworkModules;
}
export function frameworkDraft(modules: FrameworkModules): FrameworkModulesDraft {
  return Object.fromEntries(frameworkStages.map(stage => {
    const module = modules[stage];
    return [stage, typeof module === "string" ? { kind: "builtin", program: emptyProgramInputs() }
      : { kind: "python", program: programDraft(module.program) }];
  })) as FrameworkModulesDraft;
}
