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

export type ResearchDraft = ResearchInputs & {
  editor: EditorState;
  lastAdmittedBaseline: ResearchInputs | null;
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
  const { editor: _editor, lastAdmittedBaseline: _baseline, ...inputs } = draft;
  return inputs;
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
  if (
    inputs === null ||
    !isRecord(editor) ||
    !isSafeOffset(editor.anchor) ||
    !isSafeOffset(editor.head) ||
    (baseline !== null && readInputs(baseline) === null)
  ) return null;
  return {
    ...empty,
    ...inputs,
    editor: { anchor: editor.anchor, head: editor.head },
    lastAdmittedBaseline: baseline === null ? null : readInputs(baseline),
  };
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
