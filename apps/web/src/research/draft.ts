import { costFields, costInputError, defaultSimulationCosts, readCostInputs, type CostField, type SimulationCosts } from "./simulationCosts";
import {
  DIRECT_EXAMPLE, emptyProgramInputs, programDraft, programInputFields, programInputIssues,
  parseProgramParameters, programSpec, type ProgramInputField, type ProgramInputs, type PythonProgram,
} from "./pythonStrategy";
import {
  builtinModulesDraft, frameworkDraft, frameworkSpec, frameworkStages, frozenStopLossPercentage, stopLossInputError,
  type FrameworkModules, type FrameworkModulesDraft, type FrameworkStage,
} from "./frameworkModules";
import { frameworkExample } from "./frameworkExamples";

export type PortfolioWeighting = "equal_weight" | "rank_weight" | "inverse_volatility";

export type EditorState = {
  anchor: number;
  head: number;
};

export type ResearchInputs = ProgramInputs & {
  researchKind: "factor_evaluation" | "strategy_backtest";
  strategyMode: "framework" | "direct";
  frameworkModules: FrameworkModulesDraft;
  stopLossThreshold: string;
  name: string;
  formula: string;
  hypothesis: string;
  startDate: string;
  endDate: string;
  universe: string;
  neutralization: string;
  initialCashCny: string;
  costs: SimulationCosts;
  holdingsCount: string;
  selectionEverySessions: string;
  exposureExpression: string;
  weighting: PortfolioWeighting;
  volatilityWindow: string;
};

type PendingResearchRun = {
  requestId: string;
  folderId: string;
  inputs: ResearchInputs;
};

type CommonResearchRunAdmissionCommand = {
  request_id: string;
  folder_id: string;
  name: string | null;
  hypothesis: string | null;
  start_date: string;
  end_date: string;
  universe: string;
};

export type ResearchRunAdmissionCommand = ResearchSpec & Pick<
  CommonResearchRunAdmissionCommand, "request_id" | "folder_id" | "name"
>;

type CommonFrozenResearchAuthorableInput = {
  hypothesis: string | null;
  start_date: string;
  end_date: string;
  universe: "top300" | "top1000" | "top2000" | "top3000";
};

export type FrozenResearchAuthorableInput = CommonFrozenResearchAuthorableInput & ({
  research_kind: "factor_evaluation";
  formula: string;
  neutralization: "none" | "industry";
} | {
  research_kind: "strategy_backtest";
  strategy_mode: "framework";
  modules: FrameworkModules;
  formula?: string;
  neutralization?: "none" | "industry";
  initial_cash_cny: string;
  costs: SimulationCosts;
  holdings_count?: number;
  selection_every_sessions?: number;
  exposure_expression?: string;
  weighting?: PortfolioWeighting;
  volatility_window?: number;
} | {
  research_kind: "strategy_backtest";
  strategy_mode: "direct";
  initial_cash_cny: string;
  costs: SimulationCosts;
  program: PythonProgram;
});

export type ResearchDraft = ResearchInputs & {
  editor: EditorState;
  lastAdmittedBaseline: ResearchInputs | null;
  pendingAdmission: PendingResearchRun | null;
};

const MAX_DRAFT_BYTES = 2 * 1024 * 1024;
const DRAFT_STORAGE_SCHEMA = "research-draft/v4";
const MAX_FORMULA_LENGTH = 4_096;
export const MAX_HYPOTHESIS_LENGTH = 1_024;
const MAX_TEXT_LENGTH = 10_000;

export function emptyResearchDraft(): ResearchDraft {
  return {
    researchKind: "factor_evaluation",
    strategyMode: "framework",
    stopLossThreshold: "",
    ...emptyProgramInputs(), frameworkModules: builtinModulesDraft(),
    name: "",
    formula: "",
    hypothesis: "",
    startDate: "",
    endDate: "",
    universe: "",
    neutralization: "none",
    initialCashCny: "", costs: defaultSimulationCosts(),
    holdingsCount: "",
    selectionEverySessions: "",
    exposureExpression: "1",
    weighting: "equal_weight",
    volatilityWindow: "20",
    editor: { anchor: 0, head: 0 },
    lastAdmittedBaseline: null,
    pendingAdmission: null,
  };
}

export function researchDraftKey(researcherId: string, folderId: string): string {
  return `thesistrace.research-draft.${researcherId}.${folderId}`;
}

export function loadResearchDraft(
  storage: Pick<Storage, "getItem">,
  researcherId: string,
  folderId: string,
): ResearchDraft {
  const stored = storage.getItem(researchDraftKey(researcherId, folderId));
  if (stored === null || new TextEncoder().encode(stored).byteLength > MAX_DRAFT_BYTES) {
    return emptyResearchDraft();
  }
  try {
    const value: unknown = JSON.parse(stored);
    return readDraft(value) ?? emptyResearchDraft();
  } catch {
    return emptyResearchDraft();
  }
}

export function persistResearchDraft(
  storage: Pick<Storage, "setItem">,
  researcherId: string,
  folderId: string,
  draft: ResearchDraft,
): void {
  // Keep one copy of unchanged source/parameters. Snapshots are differences
  // from the visible inputs, so later edits still preserve accepted/pending input.
  const current = researchInputs(draft);
  const encoded = JSON.stringify({
    ...draft, storageSchema: DRAFT_STORAGE_SCHEMA,
    lastAdmittedBaseline: draft.lastAdmittedBaseline === null ? null : inputChanges(draft.lastAdmittedBaseline, current),
    pendingAdmission: draft.pendingAdmission === null ? null : { ...draft.pendingAdmission,
      inputs: inputChanges(draft.pendingAdmission.inputs, current),
    },
  });
  if (new TextEncoder().encode(encoded).byteLength > MAX_DRAFT_BYTES) {
    throw new Error("Research Draft exceeds the browser storage limit");
  }
  storage.setItem(researchDraftKey(researcherId, folderId), encoded);
}

export function researchInputs(draft: ResearchDraft): ResearchInputs {
  const {
    editor: _editor,
    lastAdmittedBaseline: _baseline,
    pendingAdmission: _pending,
    ...inputs
  } = draft;
  return inputs;
}

export function selectResearchKind(
  draft: ResearchDraft,
  researchKind: ResearchInputs["researchKind"],
): ResearchDraft {
  return researchKind === "factor_evaluation" ? {
    ...draft,
    researchKind, strategyMode: "framework",
    ...emptyProgramInputs(), frameworkModules: builtinModulesDraft(),
    neutralization: draft.neutralization || "none",
    initialCashCny: "", costs: defaultSimulationCosts(),
    holdingsCount: "",
    selectionEverySessions: "",
    exposureExpression: "1",
    weighting: "equal_weight",
    volatilityWindow: "20",
  } : {
    ...draft,
    researchKind,
    initialCashCny: draft.researchKind === "factor_evaluation" ? "100000" : draft.initialCashCny,
    holdingsCount: draft.researchKind === "factor_evaluation" ? "10" : draft.holdingsCount,
    selectionEverySessions: draft.researchKind === "factor_evaluation" ? "5" : draft.selectionEverySessions,
  };
}

export function selectStrategyMode(draft: ResearchDraft, mode: ResearchInputs["strategyMode"]): ResearchDraft {
  if (draft.strategyMode === mode) return draft;
  return mode === "direct" ? {
    ...draft, strategyMode: mode, formula: "", neutralization: "", holdingsCount: "",
    selectionEverySessions: "", exposureExpression: "", weighting: "equal_weight", volatilityWindow: "",
    programSource: DIRECT_EXAMPLE, programParameters: '{"improvement": 0.02}',
    programFields: "price.close.adjusted", programHistorySessions: "6",
    frameworkModules: builtinModulesDraft(),
    editor: { anchor: 0, head: 0 }, pendingAdmission: null,
  } : {
    ...draft, strategyMode: mode, ...emptyProgramInputs(), frameworkModules: builtinModulesDraft(),
    formula: "", neutralization: "none", holdingsCount: "10", selectionEverySessions: "5",
    exposureExpression: "1", weighting: "equal_weight", volatilityWindow: "20",
    editor: { anchor: 0, head: 0 }, pendingAdmission: null,
  };
}

export function selectFrameworkModule(
  draft: ResearchDraft, stage: FrameworkStage, kind: "builtin" | "python",
): ResearchDraft {
  if (draft.frameworkModules[stage].kind === kind) return draft;
  const next: ResearchDraft = {
    ...draft, pendingAdmission: null,
    frameworkModules: { ...draft.frameworkModules, [stage]: {
      kind, program: kind === "python" ? frameworkExample(stage) : emptyProgramInputs(),
    } },
  };
  if (stage === "alpha") Object.assign(next, {
    formula: "", neutralization: kind === "builtin" ? "none" : "", editor: { anchor: 0, head: 0 },
  });
  if (stage === "portfolio_construction") Object.assign(next, {
    holdingsCount: kind === "builtin" ? "10" : "", selectionEverySessions: kind === "builtin" ? "5" : "",
    exposureExpression: kind === "builtin" ? "1" : "", weighting: "equal_weight",
    volatilityWindow: kind === "builtin" ? "20" : "",
  });
  return next;
}

export function usesBuiltinAlpha(inputs: ResearchInputs): boolean {
  return inputs.researchKind === "factor_evaluation" || (inputs.strategyMode === "framework"
    && inputs.frameworkModules.alpha.kind === "builtin");
}

export function usesBuiltinPortfolio(inputs: ResearchInputs): boolean {
  return inputs.researchKind === "strategy_backtest" && inputs.strategyMode === "framework"
    && inputs.frameworkModules.portfolio_construction.kind === "builtin";
}

export function beginResearchRun(
  draft: ResearchDraft,
  folderId: string,
  createRequestId: () => string,
): { draft: ResearchDraft; command: ResearchRunAdmissionCommand } {
  const inputs = researchInputs(draft);
  const existing = draft.pendingAdmission;
  const pending = existing !== null &&
    existing.folderId === folderId &&
    sameInputs(existing.inputs, inputs)
    ? existing
    : { requestId: createRequestId(), folderId, inputs };
  return {
    draft: { ...draft, pendingAdmission: pending },
    command: {
      ...researchSpec(inputs),
      request_id: pending.requestId,
      folder_id: pending.folderId,
      name: inputs.name.trim() === "" ? null : inputs.name,
    },
  };
}

export type ResearchSpec = Omit<CommonResearchRunAdmissionCommand, "request_id" | "folder_id" | "name"> & (
  { research_kind: "factor_evaluation"; formula: string; neutralization: string } | {
    research_kind: "strategy_backtest"; strategy_mode: "framework";
    modules: FrameworkModules;
    formula?: string; neutralization?: string; initial_cash_cny: string; costs: SimulationCosts;
    holdings_count?: number; selection_every_sessions?: number; exposure_expression?: string;
    weighting?: PortfolioWeighting; volatility_window?: number;
  } | {
    research_kind: "strategy_backtest"; strategy_mode: "direct";
    initial_cash_cny: string; costs: SimulationCosts; program: PythonProgram;
  }
);

export function researchSpec(inputs: ResearchInputs): ResearchSpec {
  const common = {
    hypothesis: inputs.hypothesis.trim() === "" ? null : inputs.hypothesis,
    start_date: inputs.startDate, end_date: inputs.endDate, universe: inputs.universe,
  };
  if (inputs.researchKind === "strategy_backtest" && inputs.strategyMode === "direct") return {
    ...common, research_kind: "strategy_backtest", strategy_mode: "direct",
    initial_cash_cny: inputs.initialCashCny, costs: { ...inputs.costs },
    program: programSpec(inputs),
  };
  const alpha = { formula: inputs.formula, neutralization: inputs.neutralization };
  return inputs.researchKind === "factor_evaluation" ? {
    ...common, ...alpha, research_kind: "factor_evaluation",
  } : {
    ...common, research_kind: "strategy_backtest", strategy_mode: "framework",
    modules: frameworkSpec(inputs.frameworkModules, inputs.stopLossThreshold), initial_cash_cny: inputs.initialCashCny, costs: { ...inputs.costs },
    ...(usesBuiltinAlpha(inputs) ? alpha : {}),
    ...(usesBuiltinPortfolio(inputs) ? {
      holdings_count: Number(inputs.holdingsCount), selection_every_sessions: Number(inputs.selectionEverySessions),
      exposure_expression: inputs.exposureExpression, weighting: inputs.weighting, volatility_window: Number(inputs.volatilityWindow),
    } : {}),
  };
}

export function acceptPendingResearchRun(
  draft: ResearchDraft,
  requestId: string,
): ResearchDraft {
  if (draft.pendingAdmission?.requestId !== requestId) return draft;
  return {
    ...draft,
    lastAdmittedBaseline: draft.pendingAdmission.inputs,
    pendingAdmission: null,
  };
}

export function finishResearchRun(
  storage: Pick<Storage, "getItem" | "setItem">,
  researcherId: string,
  folderId: string,
  requestId: string,
): ResearchDraft | null {
  const latest = loadResearchDraft(storage, researcherId, folderId);
  if (latest.pendingAdmission?.requestId !== requestId) return null;
  const accepted = acceptPendingResearchRun(latest, requestId);
  persistResearchDraft(storage, researcherId, folderId, accepted);
  return accepted;
}

export function isValidVolatilityWindow(value: string): boolean {
  const window = Number(value);
  return Number.isInteger(window) && window >= 1 && window <= 252;
}

export function isValidInitialCash(value: string): boolean {
  if (!/^[0-9]+(?:\.[0-9]{1,2})?$/.test(value) || !/[1-9]/.test(value)) return false;
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole + fraction.padEnd(2, "0")) <= 100000000000n;
}

export type ResearchInputField = `costs.${CostField}` | ProgramInputField | `${FrameworkStage}.${ProgramInputField}`
  | "formula" | "hypothesis" | "startDate" | "endDate" | "universe" | "neutralization" | "initialCashCny"
  | "stopLossThreshold" | "holdingsCount" | "selectionEverySessions" | "exposureExpression" | "volatilityWindow";
export type ResearchInputIssue = { field: ResearchInputField; message: string };

export function researchInputIssues(inputs: ResearchInputs): ResearchInputIssue[] {
  const issues: ResearchInputIssue[] = [];
  const direct = inputs.researchKind === "strategy_backtest" && inputs.strategyMode === "direct";
  if (usesBuiltinAlpha(inputs) && !inputs.formula.trim()) issues.push({ field: "formula", message: "Enter an Alpha formula." });
  if (!/^\d{4}-\d{2}-\d{2}$/.test(inputs.startDate)) issues.push({ field: "startDate", message: "Choose a start date." });
  if (!/^\d{4}-\d{2}-\d{2}$/.test(inputs.endDate)) issues.push({ field: "endDate", message: "Choose an end date." });
  else if (inputs.startDate > inputs.endDate) issues.push({ field: "endDate", message: "End date must be on or after start date." });
  if (!["top300", "top1000", "top2000", "top3000"].includes(inputs.universe)) issues.push({ field: "universe", message: "Choose a stock universe." });
  if (usesBuiltinAlpha(inputs) && !["none", "industry"].includes(inputs.neutralization)) issues.push({ field: "neutralization", message: "Choose a neutralization method." });
  if (inputs.researchKind === "strategy_backtest" && !isValidInitialCash(inputs.initialCashCny)) issues.push({ field: "initialCashCny", message: "Initial cash must be 0.01–1,000,000,000 CNY, with up to two decimal places." });
  if (inputs.researchKind === "strategy_backtest") {
    for (const { key } of costFields) {
      const message = costInputError(key, inputs.costs[key]);
      if (message) issues.push({ field: `costs.${key}`, message });
    }
  }
  if (usesBuiltinPortfolio(inputs)) {
    const holdings = Number(inputs.holdingsCount), interval = Number(inputs.selectionEverySessions);
    if (!Number.isInteger(holdings) || holdings < 1 || holdings > 100) issues.push({ field: "holdingsCount", message: "Holdings count must be a whole number from 1 to 100." });
    if (!Number.isInteger(interval) || interval < 1 || interval > 20) issues.push({ field: "selectionEverySessions", message: "Selection interval must be a whole number from 1 to 20 trading days." });
    if (!isValidVolatilityWindow(inputs.volatilityWindow)) issues.push({ field: "volatilityWindow", message: "Volatility window must be a whole number from 1 to 252." });
    if (!inputs.exposureExpression.trim()) issues.push({ field: "exposureExpression", message: "Enter a position sizing formula." });
    else if (Number(inputs.exposureExpression) < 0 || Number(inputs.exposureExpression) > 1) issues.push({ field: "exposureExpression", message: "Position sizing formula must return a value between 0 and 1." });
  }
  if (inputs.researchKind === "strategy_backtest" && inputs.strategyMode === "framework"
    && inputs.frameworkModules.risk_management.kind === "builtin") {
    const message = stopLossInputError(inputs.stopLossThreshold);
    if (message) issues.push({ field: "stopLossThreshold", message });
  }
  if (direct) issues.push(...programInputIssues(inputs));
  else if (inputs.researchKind === "strategy_backtest") {
    for (const stage of frameworkStages) {
      const module = inputs.frameworkModules[stage];
      if (module.kind === "python") issues.push(...programInputIssues(module.program).map(issue => ({
        ...issue, field: `${stage}.${issue.field}` as ResearchInputField,
      })));
    }
  }
  if (Array.from(inputs.hypothesis).length > MAX_HYPOTHESIS_LENGTH) issues.push({ field: "hypothesis", message: "Keep notes within 1,024 characters." });
  return issues;
}

export function isCompleteResearchInputs(inputs: ResearchInputs): boolean {
  return researchInputIssues(inputs).length === 0;
}

export function hasUnexecutedChanges(draft: ResearchDraft): boolean {
  const current = researchInputs(draft);
  return !sameInputs(current, draft.lastAdmittedBaseline ?? researchInputs(emptyResearchDraft()));
}

function sameInputs(left: ResearchInputs, right: ResearchInputs): boolean {
  return (Object.keys(left) as (keyof ResearchInputs)[]).every(key => sameInputValue(key, left[key], right[key]));
}

function sameInputValue(key: string, left: unknown, right: unknown): boolean {
  return JSON.stringify(snapshotInputValue(key, left)) === JSON.stringify(snapshotInputValue(key, right));
}

function snapshotInputValue(key: string, value: unknown): unknown {
  if (key === "programParameters" && typeof value === "string") {
    // Accepted/pending inputs need the parameter values, not the editor's whitespace.
    // Incomplete JSON remains editable and is compared verbatim.
    try { return JSON.stringify(parseProgramParameters(value)); } catch { return value; }
  }
  if (isRecord(value)) return Object.fromEntries(Object.entries(value).map(([child, item]) => [child, snapshotInputValue(child, item)]));
  return value;
}

export function useResearchAsDraft(
  storage: Pick<Storage, "getItem" | "setItem">,
  researcherId: string,
  folderId: string,
  input: FrozenResearchAuthorableInput,
  confirmDiscard: (message: string) => boolean,
): boolean {
  const current = loadResearchDraft(storage, researcherId, folderId);
  const direct = input.research_kind === "strategy_backtest" && input.strategy_mode === "direct";
  const framework = input.research_kind === "strategy_backtest" && input.strategy_mode === "framework";
  const nextInputs: ResearchInputs = {
    ...researchInputs(emptyResearchDraft()), name: current.name,
    formula: "formula" in input ? input.formula ?? "" : "",
    hypothesis: input.hypothesis ?? "", startDate: input.start_date, endDate: input.end_date,
    universe: input.universe, neutralization: "neutralization" in input ? input.neutralization ?? "" : "",
    researchKind: input.research_kind, strategyMode: direct ? "direct" : "framework",
    initialCashCny: input.research_kind === "strategy_backtest" ? input.initial_cash_cny : "",
    costs: input.research_kind === "strategy_backtest" ? { ...input.costs } : defaultSimulationCosts(),
    holdingsCount: framework && input.holdings_count !== undefined ? String(input.holdings_count) : "",
    exposureExpression: framework ? input.exposure_expression ?? "" : direct ? "" : "1",
    volatilityWindow: framework ? input.volatility_window === undefined ? "" : String(input.volatility_window) : direct ? "" : "20",
    weighting: framework ? input.weighting ?? "equal_weight" : "equal_weight",
    selectionEverySessions: framework && input.selection_every_sessions !== undefined ? String(input.selection_every_sessions) : "",
    ...(direct ? programDraft(input.program) : emptyProgramInputs()),
    frameworkModules: framework ? frameworkDraft(input.modules) : builtinModulesDraft(),
    stopLossThreshold: framework ? frozenStopLossPercentage(input.modules) : "",
  };
  if (
    wouldOverwriteUnexecutedAuthorableValue(current, nextInputs) &&
    !confirmDiscard("Use this Research as Draft and discard unexecuted browser changes?")
  ) return false;
  persistResearchDraft(storage, researcherId, folderId, {
    ...current,
    ...nextInputs,
    editor: { anchor: nextInputs.formula.length, head: nextInputs.formula.length },
    pendingAdmission: null,
  });
  return true;
}

function wouldOverwriteUnexecutedAuthorableValue(
  draft: ResearchDraft,
  next: ResearchInputs,
): boolean {
  const current = researchInputs(draft);
  const baseline = draft.lastAdmittedBaseline ?? researchInputs(emptyResearchDraft());
  const copiedKeys = [
    "formula",
    "hypothesis",
    "startDate",
    "endDate",
    "universe",
    "neutralization",
    "researchKind",
    "strategyMode",
    "programSource", "programParameters", "programFields", "programHistorySessions",
    "frameworkModules", "costs", "stopLossThreshold",
    "initialCashCny",
    "holdingsCount",
    "selectionEverySessions",
    "exposureExpression",
    "weighting",
    "volatilityWindow",
  ] as const;
  return copiedKeys.some((key) => !sameInputValue(key, current[key], baseline[key])
    && !sameInputValue(key, current[key], next[key]));
}

function readDraft(value: unknown): ResearchDraft | null {
  if (!isRecord(value) || value.storageSchema !== DRAFT_STORAGE_SCHEMA) return null;
  const empty = emptyResearchDraft();
  const inputs = readInputs(value);
  const editor = value.editor;
  if (inputs === null) return null;
  const baseline = value.lastAdmittedBaseline === null ? null : readInputs(restoreInputs(inputs, value.lastAdmittedBaseline));
  const pending = value.pendingAdmission === null ? null : readPendingResearchRun(value.pendingAdmission, inputs);
  if (
    !isRecord(editor) ||
    !isSafeOffset(editor.anchor) ||
    !isSafeOffset(editor.head) ||
    (value.lastAdmittedBaseline !== null && baseline === null) ||
    (value.pendingAdmission !== null && pending === null)
  ) return null;
  return {
    ...empty,
    ...inputs,
    editor: { anchor: editor.anchor, head: editor.head },
    lastAdmittedBaseline: baseline,
    pendingAdmission: pending,
  };
}

function readPendingResearchRun(value: unknown, current: ResearchInputs): PendingResearchRun | null {
  if (
    !isRecord(value) ||
    typeof value.requestId !== "string" ||
    value.requestId.length < 1 ||
    value.requestId.length > 200 ||
    typeof value.folderId !== "string" ||
    value.folderId.length < 1 ||
    value.folderId.length > 200
  ) return null;
  const inputs = readInputs(restoreInputs(current, value.inputs));
  if (inputs === null) return null;
  return { requestId: value.requestId, folderId: value.folderId, inputs };
}

function inputChanges(snapshot: Record<string, unknown>, current: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(current).flatMap(([key, visible]) => {
    const value = snapshot[key];
    if (isRecord(value) && isRecord(visible)) {
      const changes = inputChanges(value, visible);
      return Object.keys(changes).length === 0 ? [] : [[key, changes]];
    }
    return value === visible ? [] : [[key, snapshotInputValue(key, value)]];
  }));
}

function restoreInputs(current: Record<string, unknown>, changes: unknown): Record<string, unknown> | null {
  if (!isRecord(changes) || Object.keys(changes).some(key => !Object.hasOwn(current, key))) return null;
  return Object.fromEntries(Object.entries(current).map(([key, value]) => {
    if (!Object.hasOwn(changes, key)) return [key, value];
    return [key, isRecord(value) ? restoreInputs(value, changes[key]) : changes[key]];
  }));
}

function readInputs(value: unknown): ResearchInputs | null {
  if (!isRecord(value)) return null;
  const keys = [
    "researchKind",
    "strategyMode", "stopLossThreshold",
    "programSource", "programParameters", "programFields", "programHistorySessions",
    "name",
    "formula",
    "hypothesis",
    "startDate",
    "endDate",
    "universe",
    "neutralization",
    "initialCashCny",
    "holdingsCount",
    "selectionEverySessions",
    "exposureExpression",
    "weighting",
    "volatilityWindow",
  ] as const;
  if (keys.some((key) => typeof value[key] !== "string")) return null;
  const strings = value as Record<(typeof keys)[number], string>;
  if (
    !["factor_evaluation", "strategy_backtest"].includes(strings.researchKind) ||
    !["framework", "direct"].includes(strings.strategyMode) ||
    !["equal_weight", "rank_weight", "inverse_volatility"].includes(strings.weighting) ||
    strings.formula.length > MAX_FORMULA_LENGTH ||
    strings.exposureExpression.length > MAX_FORMULA_LENGTH ||
    keys.some((key) => key === "programSource" || key === "programParameters"
      ? new TextEncoder().encode(strings[key]).byteLength > (key === "programSource" ? 65536 : MAX_DRAFT_BYTES)
      : strings[key].length > MAX_TEXT_LENGTH)
  ) return null;
  const costs = readCostInputs(value.costs);
  if (costs === null) return null;
  const modules = value.frameworkModules;
  if (!isRecord(modules)) return null;
  const parsedModules = builtinModulesDraft();
  for (const stage of frameworkStages) {
    const module = modules[stage];
    if (!isRecord(module) || (module.kind !== "builtin" && module.kind !== "python")) return null;
    const program = module.program;
    if (!isRecord(program) || programInputFields.some(field => typeof program[field] !== "string")) return null;
    const inputs = Object.fromEntries(programInputFields.map(field => [field, program[field]])) as ProgramInputs;
    if (new TextEncoder().encode(inputs.programSource).byteLength > 65536
      || inputs.programFields.length > MAX_TEXT_LENGTH || inputs.programHistorySessions.length > MAX_TEXT_LENGTH) return null;
    parsedModules[stage] = { kind: module.kind, program: inputs };
  }
  return { ...Object.fromEntries(keys.map((key) => [key, strings[key]])), frameworkModules: parsedModules, costs } as ResearchInputs;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSafeOffset(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}
