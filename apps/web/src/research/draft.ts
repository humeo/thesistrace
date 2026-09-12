export type PortfolioWeighting = "equal_weight" | "rank_weight" | "inverse_volatility";

export type EditorState = {
  anchor: number;
  head: number;
};

export type ResearchInputs = {
  researchKind: "factor_evaluation" | "strategy_backtest";
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
  formula: string;
  hypothesis: string | null;
  start_date: string;
  end_date: string;
  universe: string;
  neutralization: string;
};

export type ResearchRunAdmissionCommand = ResearchSpec & Pick<
  CommonResearchRunAdmissionCommand, "request_id" | "folder_id" | "name"
>;

type CommonFrozenResearchAuthorableInput = {
  formula: string;
  hypothesis: string | null;
  start_date: string;
  end_date: string;
  universe: "top300" | "top1000" | "top2000" | "top3000";
  neutralization: "none" | "industry";
};

export type FrozenResearchAuthorableInput = CommonFrozenResearchAuthorableInput & ({
  research_kind: "factor_evaluation";
} | {
  research_kind: "strategy_backtest";
  initial_cash_cny: string;
  holdings_count: number;
  selection_every_sessions: number;
  exposure_expression: string;
  weighting: PortfolioWeighting;
  volatility_window: number;
});

export type ResearchDraft = ResearchInputs & {
  editor: EditorState;
  lastAdmittedBaseline: ResearchInputs | null;
  pendingAdmission: PendingResearchRun | null;
};

const MAX_DRAFT_BYTES = 64 * 1024;
const MAX_FORMULA_LENGTH = 4_096;
export const MAX_HYPOTHESIS_LENGTH = 1_024;
const MAX_TEXT_LENGTH = 10_000;

export function emptyResearchDraft(): ResearchDraft {
  return {
    researchKind: "factor_evaluation",
    name: "",
    formula: "",
    hypothesis: "",
    startDate: "",
    endDate: "",
    universe: "",
    neutralization: "",
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
    researchKind,
    initialCashCny: "",
    holdingsCount: "",
    selectionEverySessions: "",
    exposureExpression: "1",
    weighting: "equal_weight",
    volatilityWindow: "20",
  } : {
    ...draft,
    researchKind,
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
  { research_kind: "factor_evaluation" } | {
    research_kind: "strategy_backtest";
    initial_cash_cny: string;
    holdings_count: number;
    selection_every_sessions: number;
    exposure_expression: string;
  weighting: PortfolioWeighting;
  volatility_window: number;
  }
);

export function researchSpec(inputs: ResearchInputs): ResearchSpec {
  const common = {
    formula: inputs.formula,
    hypothesis: inputs.hypothesis.trim() === "" ? null : inputs.hypothesis,
    start_date: inputs.startDate,
    end_date: inputs.endDate,
    universe: inputs.universe,
    neutralization: inputs.neutralization,
  };
  return inputs.researchKind === "factor_evaluation" ? {
    ...common, research_kind: "factor_evaluation",
  } : {
    ...common, research_kind: "strategy_backtest",
    initial_cash_cny: inputs.initialCashCny,
    holdings_count: Number(inputs.holdingsCount),
    selection_every_sessions: Number(inputs.selectionEverySessions),
    exposure_expression: inputs.exposureExpression,
    weighting: inputs.weighting,
    volatility_window: Number(inputs.volatilityWindow),
  };
}

export function exposurePercentage(source: string): string {
  if (!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(source.trim())) return "";
  const value = Number(source);
  return Number.isFinite(value) ? String(Number((value * 100).toPrecision(12))) : "";
}

export function percentageExposureSource(percentage: string): string {
  if (percentage.trim() === "") return "";
  const value = Number(percentage);
  return Number.isFinite(value) ? String(value / 100) : "";
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

export function isCompleteResearchInputs(inputs: ResearchInputs): boolean {
  const holdingsCount = Number(inputs.holdingsCount);
  const selectionEverySessions = Number(inputs.selectionEverySessions);
  const commonComplete = inputs.formula.trim() !== "" &&
    Array.from(inputs.hypothesis).length <= MAX_HYPOTHESIS_LENGTH &&
    /^\d{4}-\d{2}-\d{2}$/.test(inputs.startDate) &&
    /^\d{4}-\d{2}-\d{2}$/.test(inputs.endDate) &&
    inputs.startDate <= inputs.endDate &&
    ["top300", "top1000", "top2000", "top3000"].includes(inputs.universe) &&
    ["none", "industry"].includes(inputs.neutralization);
  return commonComplete && (inputs.researchKind === "factor_evaluation" || (
    inputs.exposureExpression.trim() !== "" &&
    isValidInitialCash(inputs.initialCashCny) &&
    isValidVolatilityWindow(inputs.volatilityWindow) &&
    Number.isInteger(holdingsCount) && holdingsCount >= 1 && holdingsCount <= 100 &&
    Number.isInteger(selectionEverySessions) &&
    selectionEverySessions >= 1 && selectionEverySessions <= 20
  ));
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
  const nextInputs: ResearchInputs = {
    ...researchInputs(current),
    formula: input.formula,
    hypothesis: input.hypothesis ?? "",
    startDate: input.start_date,
    endDate: input.end_date,
    universe: input.universe,
    neutralization: input.neutralization,
    researchKind: input.research_kind,
    initialCashCny: input.research_kind === "strategy_backtest" ? input.initial_cash_cny : "",
    holdingsCount: input.research_kind === "strategy_backtest"
      ? String(input.holdings_count)
      : "",
    exposureExpression: input.research_kind === "strategy_backtest" ? input.exposure_expression : "1",
    volatilityWindow: input.research_kind === "strategy_backtest" ? String(input.volatility_window) : "20",
    weighting: input.research_kind === "strategy_backtest" ? input.weighting : "equal_weight",
    selectionEverySessions: input.research_kind === "strategy_backtest"
      ? String(input.selection_every_sessions)
      : "",
  };
  if (
    wouldOverwriteUnexecutedAuthorableValue(current, nextInputs) &&
    !confirmDiscard("Use this Research as Draft and discard unexecuted browser changes?")
  ) return false;
  persistResearchDraft(storage, researcherId, folderId, {
    ...current,
    ...nextInputs,
    editor: { anchor: input.formula.length, head: input.formula.length },
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
    !["equal_weight", "rank_weight", "inverse_volatility"].includes(strings.weighting) ||
    strings.formula.length > MAX_FORMULA_LENGTH ||
    strings.exposureExpression.length > MAX_FORMULA_LENGTH ||
    keys.some((key) => strings[key].length > MAX_TEXT_LENGTH)
  ) return null;
  return Object.fromEntries(keys.map((key) => [key, strings[key]])) as ResearchInputs;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSafeOffset(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}
