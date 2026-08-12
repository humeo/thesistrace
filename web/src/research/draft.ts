export type EditorState = {
  anchor: number;
  head: number;
};

export type ResearchInputs = {
  name: string;
  formula: string;
  hypothesis: string;
  startDate: string;
  endDate: string;
  universe: string;
  neutralization: string;
  holdingsCount: string;
  rebalanceEverySessions: string;
};

export type PendingResearchRun = {
  requestId: string;
  folderId: string;
  inputs: ResearchInputs;
};

export type ResearchRunAdmissionCommand = {
  request_id: string;
  folder_id: string;
  name: string | null;
  formula: string;
  hypothesis: string | null;
  start_date: string;
  end_date: string;
  universe: string;
  neutralization: string;
  holdings_count: number;
  rebalance_every_sessions: number;
};

export type ResearchDraft = ResearchInputs & {
  editor: EditorState;
  lastAdmittedBaseline: ResearchInputs | null;
  pendingAdmission: PendingResearchRun | null;
};

const MAX_DRAFT_BYTES = 64 * 1024;
const MAX_FORMULA_LENGTH = 4_096;
const MAX_TEXT_LENGTH = 10_000;

export function emptyResearchDraft(): ResearchDraft {
  return {
    name: "",
    formula: "",
    hypothesis: "",
    startDate: "",
    endDate: "",
    universe: "",
    neutralization: "",
    holdingsCount: "",
    rebalanceEverySessions: "",
    editor: { anchor: 0, head: 0 },
    lastAdmittedBaseline: null,
    pendingAdmission: null,
  };
}

export function researchDraftKey(folderId: string): string {
  return `thesistrace.research-draft.${folderId}`;
}

export function loadResearchDraft(storage: Pick<Storage, "getItem">, folderId: string): ResearchDraft {
  const stored = storage.getItem(researchDraftKey(folderId));
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
  folderId: string,
  draft: ResearchDraft,
): void {
  const encoded = JSON.stringify(draft);
  if (new TextEncoder().encode(encoded).byteLength > MAX_DRAFT_BYTES) {
    throw new Error("Research Draft exceeds the browser storage limit");
  }
  storage.setItem(researchDraftKey(folderId), encoded);
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
      request_id: pending.requestId,
      folder_id: pending.folderId,
      name: pending.inputs.name.trim() === "" ? null : pending.inputs.name,
      formula: pending.inputs.formula,
      hypothesis: pending.inputs.hypothesis.trim() === "" ? null : pending.inputs.hypothesis,
      start_date: pending.inputs.startDate,
      end_date: pending.inputs.endDate,
      universe: pending.inputs.universe,
      neutralization: pending.inputs.neutralization,
      holdings_count: Number(pending.inputs.holdingsCount),
      rebalance_every_sessions: Number(pending.inputs.rebalanceEverySessions),
    },
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
  folderId: string,
  requestId: string,
): ResearchDraft | null {
  const latest = loadResearchDraft(storage, folderId);
  if (latest.pendingAdmission?.requestId !== requestId) return null;
  const accepted = acceptPendingResearchRun(latest, requestId);
  persistResearchDraft(storage, folderId, accepted);
  return accepted;
}

export function isCompleteResearchInputs(inputs: ResearchInputs): boolean {
  const holdingsCount = Number(inputs.holdingsCount);
  const rebalanceEverySessions = Number(inputs.rebalanceEverySessions);
  return inputs.formula.trim() !== "" &&
    /^\d{4}-\d{2}-\d{2}$/.test(inputs.startDate) &&
    /^\d{4}-\d{2}-\d{2}$/.test(inputs.endDate) &&
    inputs.startDate <= inputs.endDate &&
    ["top300", "top1000", "top2000", "top3000"].includes(inputs.universe) &&
    ["none", "industry"].includes(inputs.neutralization) &&
    Number.isInteger(holdingsCount) && holdingsCount >= 1 && holdingsCount <= 100 &&
    Number.isInteger(rebalanceEverySessions) &&
    rebalanceEverySessions >= 1 && rebalanceEverySessions <= 20;
}

export function hasUnexecutedChanges(draft: ResearchDraft): boolean {
  const current = researchInputs(draft);
  if (draft.lastAdmittedBaseline === null) {
    return Object.values(current).some((value) => value !== "");
  }
  return JSON.stringify(current) !== JSON.stringify(draft.lastAdmittedBaseline);
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
    "name",
    "formula",
    "hypothesis",
    "startDate",
    "endDate",
    "universe",
    "neutralization",
    "holdingsCount",
    "rebalanceEverySessions",
  ] as const;
  if (keys.some((key) => typeof value[key] !== "string")) return null;
  const strings = value as Record<(typeof keys)[number], string>;
  if (
    strings.formula.length > MAX_FORMULA_LENGTH ||
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
