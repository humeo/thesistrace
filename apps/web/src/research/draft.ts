import { DIRECT_EXAMPLE, parseProgramFields, parseProgramParameters, type PythonProgram } from "./pythonStrategy";

export type PortfolioWeighting = "equal_weight" | "rank_weight" | "inverse_volatility";

export type EditorState = {
  anchor: number;
  head: number;
};

export type ResearchInputs = {
  researchKind: "factor_evaluation" | "strategy_backtest";
  strategyMode: "framework" | "direct";
  programSource: string;
  programParameters: string;
  programFields: string;
  programHistorySessions: string;
  name: string;
  formula: string;
  hypothesis: string;
  startDate: string;
  endDate: string;
  universe: string;
  neutralization: string;
  initialCashCny: string;
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
  formula: string;
  neutralization: "none" | "industry";
  initial_cash_cny: string;
  holdings_count: number;
  selection_every_sessions: number;
  exposure_expression: string;
  weighting: PortfolioWeighting;
  volatility_window: number;
} | {
  research_kind: "strategy_backtest";
  strategy_mode: "direct";
  initial_cash_cny: string;
  program: PythonProgram;
});

export type ResearchDraft = ResearchInputs & {
  editor: EditorState;
  lastAdmittedBaseline: ResearchInputs | null;
  pendingAdmission: PendingResearchRun | null;
};

const MAX_DRAFT_BYTES = 2 * 1024 * 1024;
const MAX_FORMULA_LENGTH = 4_096;
export const MAX_HYPOTHESIS_LENGTH = 1_024;
const MAX_TEXT_LENGTH = 10_000;

export function emptyResearchDraft(): ResearchDraft {
  return {
    researchKind: "factor_evaluation",
    strategyMode: "framework",
    programSource: "", programParameters: "", programFields: "", programHistorySessions: "",
    name: "",
    formula: "",
    hypothesis: "",
    startDate: "",
    endDate: "",
    universe: "",
    neutralization: "none",
    initialCashCny: "",
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
  const encoded = JSON.stringify(draft);
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
    programSource: "", programParameters: "", programFields: "", programHistorySessions: "",
    neutralization: draft.neutralization || "none",
    initialCashCny: "",
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
    editor: { anchor: 0, head: 0 }, pendingAdmission: null,
  } : {
    ...draft, strategyMode: mode, programSource: "", programParameters: "", programFields: "", programHistorySessions: "",
    formula: "", neutralization: "none", holdingsCount: "10", selectionEverySessions: "5",
    exposureExpression: "1", weighting: "equal_weight", volatilityWindow: "20",
    editor: { anchor: 0, head: 0 }, pendingAdmission: null,
  };
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
    JSON.stringify(existing.inputs) === JSON.stringify(inputs)
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
    formula: string; neutralization: string; initial_cash_cny: string;
    holdings_count: number; selection_every_sessions: number; exposure_expression: string;
    weighting: PortfolioWeighting; volatility_window: number;
  } | {
    research_kind: "strategy_backtest"; strategy_mode: "direct";
    initial_cash_cny: string; program: PythonProgram;
  }
);

export function researchSpec(inputs: ResearchInputs): ResearchSpec {
  const common = {
    hypothesis: inputs.hypothesis.trim() === "" ? null : inputs.hypothesis,
    start_date: inputs.startDate, end_date: inputs.endDate, universe: inputs.universe,
  };
  if (inputs.researchKind === "strategy_backtest" && inputs.strategyMode === "direct") return {
    ...common, research_kind: "strategy_backtest", strategy_mode: "direct",
    initial_cash_cny: inputs.initialCashCny,
    program: {
      source: inputs.programSource, parameters: parseProgramParameters(inputs.programParameters),
      data_requirements: { field_ids: parseProgramFields(inputs.programFields), history_sessions: Number(inputs.programHistorySessions) },
    },
  };
  const alpha = { ...common, formula: inputs.formula, neutralization: inputs.neutralization };
  return inputs.researchKind === "factor_evaluation" ? {
    ...alpha, research_kind: "factor_evaluation",
  } : {
    ...alpha, research_kind: "strategy_backtest", strategy_mode: "framework",
    initial_cash_cny: inputs.initialCashCny, holdings_count: Number(inputs.holdingsCount),
    selection_every_sessions: Number(inputs.selectionEverySessions), exposure_expression: inputs.exposureExpression,
    weighting: inputs.weighting, volatility_window: Number(inputs.volatilityWindow),
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

export type ResearchInputField = "programSource" | "programParameters" | "programFields" | "programHistorySessions" | "formula" | "hypothesis" | "startDate" | "endDate" | "universe" | "neutralization" | "initialCashCny" | "holdingsCount" | "selectionEverySessions" | "exposureExpression" | "volatilityWindow";
export type ResearchInputIssue = { field: ResearchInputField; message: string };

export function researchInputIssues(inputs: ResearchInputs): ResearchInputIssue[] {
  const issues: ResearchInputIssue[] = [];
  const direct = inputs.researchKind === "strategy_backtest" && inputs.strategyMode === "direct";
  if (!direct && !inputs.formula.trim()) issues.push({ field: "formula", message: "Enter an Alpha formula." });
  if (!/^\d{4}-\d{2}-\d{2}$/.test(inputs.startDate)) issues.push({ field: "startDate", message: "Choose a start date." });
  if (!/^\d{4}-\d{2}-\d{2}$/.test(inputs.endDate)) issues.push({ field: "endDate", message: "Choose an end date." });
  else if (inputs.startDate > inputs.endDate) issues.push({ field: "endDate", message: "End date must be on or after start date." });
  if (!["top300", "top1000", "top2000", "top3000"].includes(inputs.universe)) issues.push({ field: "universe", message: "Choose a stock universe." });
  if (!direct && !["none", "industry"].includes(inputs.neutralization)) issues.push({ field: "neutralization", message: "Choose a neutralization method." });
  if (inputs.researchKind === "strategy_backtest" && !isValidInitialCash(inputs.initialCashCny)) issues.push({ field: "initialCashCny", message: "Initial cash must be 0.01–1,000,000,000 CNY, with up to two decimal places." });
  if (inputs.researchKind === "strategy_backtest" && !direct) {
    const holdings = Number(inputs.holdingsCount), interval = Number(inputs.selectionEverySessions);
    if (!Number.isInteger(holdings) || holdings < 1 || holdings > 100) issues.push({ field: "holdingsCount", message: "Holdings count must be a whole number from 1 to 100." });
    if (!Number.isInteger(interval) || interval < 1 || interval > 20) issues.push({ field: "selectionEverySessions", message: "Selection interval must be a whole number from 1 to 20 trading days." });
    if (!isValidVolatilityWindow(inputs.volatilityWindow)) issues.push({ field: "volatilityWindow", message: "Volatility window must be a whole number from 1 to 252." });
    if (!inputs.exposureExpression.trim()) issues.push({ field: "exposureExpression", message: "Enter a position sizing formula." });
    else if (Number(inputs.exposureExpression) < 0 || Number(inputs.exposureExpression) > 1) issues.push({ field: "exposureExpression", message: "Position sizing formula must return a value between 0 and 1." });
  }
  if (direct) {
    if (!inputs.programSource.trim() || new TextEncoder().encode(inputs.programSource).byteLength > 65536) issues.push({ field: "programSource", message: "Enter Python source within 64 KiB." });
    try {
      const parameters = parseProgramParameters(inputs.programParameters);
      if (new TextEncoder().encode(JSON.stringify(parameters)).byteLength > 65536) throw new Error();
    } catch { issues.push({ field: "programParameters", message: "Enter a parameters JSON object within 64 KiB." }); }
    const fields = parseProgramFields(inputs.programFields);
    if (fields.length > 32 || new Set(fields).size !== fields.length || fields.some(field => field.length > 200)) issues.push({ field: "programFields", message: "Declare up to 32 unique canonical field IDs." });
    const history = Number(inputs.programHistorySessions);
    if (!Number.isInteger(history) || history < 1 || history > 253) issues.push({ field: "programHistorySessions", message: "History must be a whole number from 1 to 253 sessions, including the decision day." });
  }
  if (Array.from(inputs.hypothesis).length > MAX_HYPOTHESIS_LENGTH) issues.push({ field: "hypothesis", message: "Keep notes within 1,024 characters." });
  return issues;
}

export function isCompleteResearchInputs(inputs: ResearchInputs): boolean {
  return researchInputIssues(inputs).length === 0;
}

export function hasUnexecutedChanges(draft: ResearchDraft): boolean {
  const current = researchInputs(draft);
  if (draft.lastAdmittedBaseline === null) {
    return JSON.stringify(current) !== JSON.stringify(researchInputs(emptyResearchDraft()));
  }
  return JSON.stringify(current) !== JSON.stringify(draft.lastAdmittedBaseline);
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
    formula: "formula" in input ? input.formula : "",
    hypothesis: input.hypothesis ?? "", startDate: input.start_date, endDate: input.end_date,
    universe: input.universe, neutralization: "neutralization" in input ? input.neutralization : "",
    researchKind: input.research_kind, strategyMode: direct ? "direct" : "framework",
    initialCashCny: input.research_kind === "strategy_backtest" ? input.initial_cash_cny : "",
    holdingsCount: framework ? String(input.holdings_count) : "",
    exposureExpression: framework ? input.exposure_expression : direct ? "" : "1",
    volatilityWindow: framework ? String(input.volatility_window) : direct ? "" : "20",
    weighting: framework ? input.weighting : "equal_weight",
    selectionEverySessions: framework ? String(input.selection_every_sessions) : "",
    programSource: direct ? input.program.source : "",
    programParameters: direct ? JSON.stringify(input.program.parameters) : "",
    programFields: direct ? input.program.data_requirements.field_ids.join("\n") : "",
    programHistorySessions: direct ? String(input.program.data_requirements.history_sessions) : "",
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
    "initialCashCny",
    "holdingsCount",
    "selectionEverySessions",
    "exposureExpression",
    "weighting",
    "volatilityWindow",
  ] as const;
  return copiedKeys.some((key) => current[key] !== baseline[key] && current[key] !== next[key]);
}

function readDraft(value: unknown): ResearchDraft | null {
  if (!isRecord(value)) return null;
  const empty = emptyResearchDraft();
  const inputs = readInputs(value);
  const editor = value.editor;
  const baseline = value.lastAdmittedBaseline;
  const pending = value.pendingAdmission;
  if (
    inputs === null ||
    !isRecord(editor) ||
    !isSafeOffset(editor.anchor) ||
    !isSafeOffset(editor.head) ||
    (baseline !== null && readInputs(baseline) === null) ||
    (pending !== null && readPendingResearchRun(pending) === null)
  ) return null;
  return {
    ...empty,
    ...inputs,
    editor: { anchor: editor.anchor, head: editor.head },
    lastAdmittedBaseline: baseline === null ? null : readInputs(baseline),
    pendingAdmission: pending === null ? null : readPendingResearchRun(pending),
  };
}

function readPendingResearchRun(value: unknown): PendingResearchRun | null {
  if (
    !isRecord(value) ||
    typeof value.requestId !== "string" ||
    value.requestId.length < 1 ||
    value.requestId.length > 200 ||
    typeof value.folderId !== "string" ||
    value.folderId.length < 1 ||
    value.folderId.length > 200
  ) return null;
  const inputs = readInputs(value.inputs);
  if (inputs === null) return null;
  return { requestId: value.requestId, folderId: value.folderId, inputs };
}

function readInputs(value: unknown): ResearchInputs | null {
  if (!isRecord(value)) return null;
  const keys = [
    "researchKind",
    "strategyMode",
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
  return Object.fromEntries(keys.map((key) => [key, strings[key]])) as ResearchInputs;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSafeOffset(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}
