import { defaultSimulationCosts } from "./simulationCosts";
import { describe, expect, it } from "vitest";
import {
  acceptPendingResearchRun, beginResearchRun, emptyResearchDraft, loadResearchDraft,
  hasUnexecutedChanges, persistResearchDraft, researchInputIssues, researchSpec, selectFrameworkModule,
  selectResearchKind, selectStrategyMode, useResearchAsDraft,
  type FrozenResearchAuthorableInput,
} from "./draft";
import { builtinFrameworkModules, frameworkStages } from "./frameworkModules";
import { type JsonValue } from "./pythonStrategy";

function draft() {
  return { ...selectResearchKind(emptyResearchDraft(), "strategy_backtest"),
    formula: "close", startDate: "2026-08-03", endDate: "2026-08-28", universe: "top300" };
}
function storage() {
  const entries = new Map<string, string>();
  return { getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => { entries.set(key, value); } };
}

describe("Framework authoring contract", () => {
  it.each(["direct", "framework"] as const)("reuses deeply nested legal %s parameters without formatting expansion", mode => {
    let nested: JsonValue = Array(32500).fill(0);
    for (let index = 0; index < 30; index++) nested = { nested };
    const parameters = { values: nested };
    expect(new TextEncoder().encode(JSON.stringify(parameters)).byteLength).toBeLessThan(65536);
    const program = { source: "def decide(context, state, parameters): return {'output': None, 'state': state}",
      parameters, data_requirements: { field_ids: [], history_sessions: 1 } };
    const common = { research_kind: "strategy_backtest" as const, hypothesis: null, start_date: "2026-08-03",
      end_date: "2026-08-28", universe: "top300" as const, initial_cash_cny: "100000", costs: defaultSimulationCosts() };
    const frozen: FrozenResearchAuthorableInput = mode === "direct" ? { ...common, strategy_mode: mode, program }
      : { ...common, strategy_mode: mode, modules: { ...builtinFrameworkModules, alpha: { kind: "python", program },
        portfolio_construction: { kind: "python", program } } };
    const saved = storage();
    expect(useResearchAsDraft(saved, "researcher", "folder", frozen, () => true)).toBe(true);
    const loaded = loadResearchDraft(saved, "researcher", "folder");
    expect(researchInputIssues(loaded)).toEqual([]);
    expect(researchSpec(loaded)).toEqual(frozen);
  });

  it("can run four large formatted modules repeatedly and retain distinct pending and accepted values", () => {
    let current = draft();
    for (const stage of frameworkStages) {
      current = selectFrameworkModule(current, stage, "python");
      current.frameworkModules[stage].program.programParameters = JSON.stringify({ values: Array(30000).fill(0) }, null, 2);
    }
    expect(researchInputIssues(current)).toEqual([]);
    const saved = storage();
    const first = beginResearchRun(current, "folder", () => "first");
    persistResearchDraft(saved, "researcher", "folder", first.draft);
    const accepted = acceptPendingResearchRun(loadResearchDraft(saved, "researcher", "folder"), "first");
    persistResearchDraft(saved, "researcher", "folder", accepted);
    const second = beginResearchRun(loadResearchDraft(saved, "researcher", "folder"), "folder", () => "second");
    persistResearchDraft(saved, "researcher", "folder", second.draft);
    const changed = { ...second.draft, frameworkModules: { ...second.draft.frameworkModules, alpha: {
      ...second.draft.frameworkModules.alpha, program: { ...second.draft.frameworkModules.alpha.program, programSource: "new source" },
    } } };
    persistResearchDraft(saved, "researcher", "folder", changed);
    const loaded = loadResearchDraft(saved, "researcher", "folder");
    expect(loaded.frameworkModules.alpha.program.programSource).toBe("new source");
    expect(loaded.pendingAdmission?.inputs.frameworkModules.alpha.program.programSource).toBe(current.frameworkModules.alpha.program.programSource);
    expect(loaded.lastAdmittedBaseline?.frameworkModules.alpha.program.programParameters).toBe(current.frameworkModules.alpha.program.programParameters);
    const completed = acceptPendingResearchRun(loaded, "second");
    expect(completed.frameworkModules.alpha.program.programSource).toBe("new source");
    expect(completed.lastAdmittedBaseline?.frameworkModules.alpha.program.programSource).toBe(current.frameworkModules.alpha.program.programSource);
  });
  it("preserves three different large parameter snapshots without copying their formatting", () => {
    const parameters = (value: number) => JSON.stringify({ values: Array(30000).fill(value) }, null, 2);
    const changeParameters = (current: ReturnType<typeof draft>, value: number) => ({ ...current,
      frameworkModules: Object.fromEntries(frameworkStages.map(stage => [stage, {
        ...current.frameworkModules[stage], program: { ...current.frameworkModules[stage].program,
          programParameters: parameters(value) },
      }])) as typeof current.frameworkModules,
    });
    let current = draft();
    for (const stage of frameworkStages) current = selectFrameworkModule(current, stage, "python");
    const saved = storage();
    const first = beginResearchRun(changeParameters(current, 0), "folder", () => "first");
    const accepted = acceptPendingResearchRun(first.draft, "first");
    const second = beginResearchRun(changeParameters(accepted, 1), "folder", () => "second");
    persistResearchDraft(saved, "researcher", "folder", changeParameters(second.draft, 2));
    const loaded = loadResearchDraft(saved, "researcher", "folder");
    expect(researchInputIssues(loaded)).toEqual([]);
    for (const stage of frameworkStages) {
      expect(loaded.frameworkModules[stage].program.programParameters).toBe(parameters(2));
      expect(JSON.parse(loaded.lastAdmittedBaseline!.frameworkModules[stage].program.programParameters)).toEqual(JSON.parse(parameters(0)));
      expect(JSON.parse(loaded.pendingAdmission!.inputs.frameworkModules[stage].program.programParameters)).toEqual(JSON.parse(parameters(1)));
    }
    expect(hasUnexecutedChanges(loaded)).toBe(true);
    const restoredPending = changeParameters(loaded, 1);
    expect(beginResearchRun(restoredPending, "folder", () => "third").command.request_id).toBe("second");
    const completed = acceptPendingResearchRun(restoredPending, "second");
    expect(hasUnexecutedChanges(completed)).toBe(false);
  });
  it("submits only selected Alpha and Portfolio configuration and restores the frozen programs", () => {
    let current = selectFrameworkModule(draft(), "alpha", "python");
    current = selectFrameworkModule(current, "portfolio_construction", "python");
    expect(researchInputIssues(current)).toEqual([]);
    const spec = researchSpec(current);
    expect(spec).not.toHaveProperty("formula");
    expect(spec).not.toHaveProperty("neutralization");
    expect(spec).not.toHaveProperty("holdings_count");
    expect(spec).not.toHaveProperty("selection_every_sessions");
    expect(spec).not.toHaveProperty("exposure_expression");
    expect(spec).toMatchObject({ modules: { alpha: { kind: "python" },
      portfolio_construction: { kind: "python" }, universe_selection: "dataset_universe/v1" } });
    const saved = storage();
    expect(useResearchAsDraft(saved, "researcher", "folder", spec as FrozenResearchAuthorableInput,
      () => { throw new Error("Empty draft must not require confirmation"); })).toBe(true);
    expect(researchSpec(loadResearchDraft(saved, "researcher", "folder"))).toEqual(spec);
  });

  it("maps per-module validation and clears inactive programs when changing stages or mode", () => {
    let current = selectFrameworkModule(draft(), "risk_management", "python");
    current = { ...current, frameworkModules: { ...current.frameworkModules, risk_management: {
      kind: "python", program: { ...current.frameworkModules.risk_management.program,
        programParameters: "not JSON", programHistorySessions: "0" },
    } } };
    expect(researchInputIssues(current).map(issue => issue.field)).toEqual([
      "risk_management.programParameters", "risk_management.programHistorySessions",
    ]);
    current = selectFrameworkModule(current, "risk_management", "builtin");
    expect(researchInputIssues(current)).toEqual([]);
    expect(researchSpec(current)).toMatchObject({ modules: builtinFrameworkModules });
    current = selectStrategyMode(selectFrameworkModule(current, "alpha", "python"), "direct");
    expect(researchSpec(current)).not.toHaveProperty("modules");
    expect(Object.values(current.frameworkModules).every(module => module.kind === "builtin"
      && module.program.programSource === "")).toBe(true);
  });

  it("keeps pending admission identity and compares nested frozen values without false discard prompts", () => {
    const saved = storage();
    const started = beginResearchRun(selectFrameworkModule(draft(), "alpha", "python"), "folder", () => "first");
    persistResearchDraft(saved, "researcher", "folder", started.draft);
    const loaded = loadResearchDraft(saved, "researcher", "folder");
    expect(beginResearchRun(loaded, "folder", () => "second").command.request_id).toBe("first");
    const baseline = acceptPendingResearchRun(loaded, "first");
    persistResearchDraft(saved, "researcher", "folder", { ...baseline, name: "Keep my name" });
    const spec = researchSpec(baseline) as FrozenResearchAuthorableInput;
    expect(useResearchAsDraft(saved, "researcher", "folder", spec, () => {
      throw new Error("Equal nested program values are not unexecuted edits");
    })).toBe(true);
    expect(loadResearchDraft(saved, "researcher", "folder").name).toBe("Keep my name");
  });
});
