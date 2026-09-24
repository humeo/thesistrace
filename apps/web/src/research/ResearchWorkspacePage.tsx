import { drawdownFields, type DrawdownField } from "./portfolioDrawdown";
import type { TakeProfitField } from "./takeProfit";
import {
  CalendarBlank,
  CaretDown,
  FolderSimple,
  Minus,
  Play,
  Plus,
  SlidersHorizontal,
  Info,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode, type Ref } from "react";

import type { AlphaCatalog } from "../alphaCatalog";
import { coreFetch } from "../auth/coreFetch";
import type { BrowserLocation } from "../auth/routing";
import { ResearchFieldCatalog, type DataOverview } from "../data/DataPage";
import { AlphaFormulaEditor, type AlphaFormulaEditorHandle } from "./AlphaFormulaEditor";
import { PythonStrategyAuthoring } from "./PythonStrategyAuthoring";
import { FrameworkAuthoring } from "./FrameworkAuthoring";
import { SimulationCostSettings } from "./SimulationCostSettings";
import type { CostField } from "./simulationCosts";
import { frameworkStages, type FrameworkStage } from "./frameworkModules";
import { programInputFields, type ProgramInputField } from "./pythonStrategy";
import { buildResearchDatePresets } from "./dateRange";
import {
  createDiagnosticsScheduler,
  type DiagnosticState,
  type FormulaDiagnostic,
} from "./diagnostics";
import {
  beginResearchRun,
  emptyResearchDraft,
  researchSpec,
  finishResearchRun,
  hasUnexecutedChanges,
  researchInputIssues,
  type ResearchInputField,
  isValidInitialCash,
  isValidVolatilityWindow,
  MAX_HYPOTHESIS_LENGTH,
  loadResearchDraft,
  persistResearchDraft,
  researchInputs,
  researchDraftKey,
  selectResearchKind,
  selectStrategyMode,
  selectFrameworkModule,
  usesBuiltinAlpha,
  usesBuiltinPortfolio,
  type ResearchDraft,
} from "./draft";

export type ResearchFolder = {
  id: string;
  name: string;
  is_default: boolean;
  created_at: string;
};
type ResearchFolderList = { items: ResearchFolder[]; next_cursor: null };
type WorkspaceResources = {
  folder: ResearchFolder;
  folders: ResearchFolder[];
  catalog: AlphaCatalog;
  data: DataOverview;
};

export function ResearchWorkspacePage({ location, researcherId }: { location: BrowserLocation; researcherId: string }) {
  const [resources, setResources] = useState<WorkspaceResources | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [folderError, setFolderError] = useState<string | null>(null);
  const resourceRequest = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    resourceRequest.current?.abort();
    const controller = new AbortController();
    resourceRequest.current = controller;
    setError(null);
    setResources(null);
    try {
      const [folderResponse, dataResponse] = await Promise.all([
        coreFetch("/api/research-folders", { signal: controller.signal }),
        coreFetch("/api/data", { signal: controller.signal }),
      ]);
      if (!folderResponse.ok || !dataResponse.ok) {
        throw new Error("Research workspace unavailable");
      }
      const folders = (await folderResponse.json()) as ResearchFolderList;
      const defaults = folders.items.filter((folder) => folder.is_default);
      if (defaults.length !== 1) throw new Error("Default Folder unavailable");
      const parameters = new URLSearchParams(location.search);
      const requestedFolderId = parameters.has("new") ? null : parameters.get("folder");
      const selected = folders.items.find((folder) => folder.id === requestedFolderId) ?? defaults[0];
      const { catalog, ...data } = await dataResponse.json();
      if (controller.signal.aborted) return;
      setResources({
        folder: selected,
        folders: folders.items,
        catalog: catalog as AlphaCatalog,
        data: data as DataOverview,
      });
    } catch (reason: unknown) {
      if (controller.signal.aborted) return;
      setResources(null);
      setError(reason instanceof Error ? reason.message : "Research workspace unavailable");
    }
  }, [location]);

  useEffect(() => {
    void load();
    return () => resourceRequest.current?.abort();
  }, [load]);

  if (error !== null) return (
    <section aria-label="Research" className="page-section state-section">
      <p role="alert">{error}</p>
      <button onClick={() => void load()}>Retry</button>
    </section>
  );
  if (resources === null) return (
    <section aria-label="Research" className="page-section state-section">
      <p>Opening Research…</p>
    </section>
  );
  async function createFolder(name: string): Promise<void> {
    setFolderError(null);
    try {
      const response = await coreFetch("/api/research-folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!response.ok) {
        setFolderError(await folderMutationError(response));
        return;
      }
      const folder = (await response.json()) as ResearchFolder;
      setResources((current) => current === null ? current : {
        ...current,
        folder,
        folders: [...current.folders, folder],
      });
      window.history.replaceState(null, "", `/research?folder=${folder.id}`);
    } catch {
      setFolderError("Research Folders unavailable");
    }
  }

  async function renameFolder(folderId: string, name: string): Promise<void> {
    setFolderError(null);
    try {
      const response = await coreFetch(`/api/research-folders/${folderId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!response.ok) {
        setFolderError(await folderMutationError(response));
        return;
      }
      const renamed = (await response.json()) as ResearchFolder;
      setResources((current) => current === null ? current : {
        ...current,
        folder: current.folder.id === renamed.id ? renamed : current.folder,
        folders: current.folders.map((folder) => folder.id === renamed.id ? renamed : folder),
      });
    } catch {
      setFolderError("Research Folders unavailable");
    }
  }

  async function deleteFolder(folder: ResearchFolder): Promise<void> {
    const currentResources = resources;
    if (currentResources === null) return;
    if (!window.confirm(`Delete the empty ${folder.name} Folder and its browser Draft?`)) return;
    setFolderError(null);
    try {
      const response = await coreFetch(`/api/research-folders/${folder.id}`, { method: "DELETE" });
      if (!response.ok) {
        setFolderError(await folderMutationError(response));
        return;
      }
      window.localStorage.removeItem(researchDraftKey(researcherId, folder.id));
      const defaultFolder = currentResources.folders.find((item) => item.is_default);
      if (defaultFolder === undefined) throw new Error("Default Folder unavailable");
      setResources({
        ...currentResources,
        folder: defaultFolder,
        folders: currentResources.folders.filter((item) => item.id !== folder.id),
      });
      window.history.replaceState(null, "", "/research");
    } catch {
      setFolderError("Research Folders unavailable");
    }
  }

  return (
    <section aria-label="Research workspace" className="research-folder-layout">
      <ResearchDraftWorkspace
        key={`${researcherId}:${resources.folder.id}`}
        researcherId={researcherId}
        folderNavigation={
          <ResearchFolderNavigation
            activeFolder={resources.folder}
            error={folderError}
            folders={resources.folders}
            onCreate={createFolder}
            onDelete={deleteFolder}
            onRename={renameFolder}
          />
        }
        {...resources}
      />
    </section>
  );
}

export function ResearchFolderNavigation({
  activeFolder,
  folders,
  error,
  onCreate,
  onRename,
  onDelete,
}: {
  activeFolder: ResearchFolder;
  folders: ResearchFolder[];
  error: string | null;
  onCreate: (name: string) => Promise<void>;
  onRename: (folderId: string, name: string) => Promise<void>;
  onDelete: (folder: ResearchFolder) => Promise<void>;
}) {
  const [newName, setNewName] = useState("");
  const [renameName, setRenameName] = useState(activeFolder.name);
  useEffect(() => setRenameName(activeFolder.name), [activeFolder.id, activeFolder.name]);
  return (
    <div className="research-folder-control">
      <details aria-label="Research Folders" className="research-folder-navigation">
        <summary>
          <FolderSimple aria-hidden="true" size={18} weight="regular" />
          <span>{activeFolder.name} folder</span>
          <CaretDown aria-hidden="true" className="folder-menu-caret" size={16} weight="regular" />
        </summary>
        <div className="folder-menu-panel">
          <div className="folder-navigation-heading">
            <span>Folders</span>
          </div>
          <nav aria-label="Research Folder navigation">
            {folders.map((folder) => (
              <a
                aria-current={folder.id === activeFolder.id ? "page" : undefined}
                href={folder.is_default ? "/research" : `/research?folder=${folder.id}`}
                key={folder.id}
              >
                <span>{folder.name}</span>
                {folder.is_default ? <small>Default</small> : null}
              </a>
            ))}
          </nav>
          <form onSubmit={(event) => {
            event.preventDefault();
            if (newName.trim() === "") return;
            void onCreate(newName).then(() => setNewName(""));
          }}>
            <label htmlFor="new-folder-name">New Folder</label>
            <div className="folder-inline-action">
              <input id="new-folder-name" maxLength={120} onChange={(event) => setNewName(event.target.value)} value={newName} />
              <button aria-label="Create Folder" disabled={newName.trim() === ""} type="submit">
                <Plus aria-hidden="true" size={16} weight="regular" />
                Create
              </button>
            </div>
          </form>
          {!activeFolder.is_default ? (
            <section aria-label="Selected Folder actions" className="folder-actions">
              <label htmlFor="rename-folder-name">Folder name</label>
              <input id="rename-folder-name" maxLength={120} onChange={(event) => setRenameName(event.target.value)} value={renameName} />
              <button disabled={renameName.trim() === "" || renameName.trim() === activeFolder.name} onClick={() => void onRename(activeFolder.id, renameName)}>Rename Folder</button>
              <button className="folder-delete" onClick={() => void onDelete(activeFolder)}>Delete Folder</button>
            </section>
          ) : null}
          {error !== null ? <p className="inline-status inline-status-error" role="alert">{error}</p> : null}
        </div>
      </details>
    </div>
  );
}

async function folderMutationError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") return payload.detail;
  } catch {
    // The public status remains enough when an upstream response has no JSON body.
  }
  return `Folder request failed (${response.status})`;
}

function nextBoundedInteger(
  value: string,
  minimum: number,
  maximum: number,
  direction: -1 | 1,
): string {
  const current = value.trim() === "" ? null : Number(value);
  if (current === null || !Number.isFinite(current)) {
    return direction === 1 ? String(minimum) : value;
  }
  const candidate = direction === 1
    ? Math.floor(current) + 1
    : Math.ceil(current) - 1;
  return String(Math.min(maximum, Math.max(minimum, candidate)));
}

function ResearchNumberStepper({
  actionLabel,
  id,
  label,
  maximum,
  minimum,
  onChange,
  value,
  error,
}: {
  error?: string;
  actionLabel: string;
  id: string;
  label: string;
  maximum: number;
  minimum: number;
  onChange: (value: string) => void;
  value: string;
}) {
  const numericValue = value.trim() === "" ? null : Number(value);
  const hasFiniteValue = numericValue !== null && Number.isFinite(numericValue);
  const canDecrease = hasFiniteValue && numericValue > minimum;
  const canIncrease = !hasFiniteValue || numericValue < maximum;

  return (
    <div className="research-number-field">
      <label htmlFor={id}>{label}</label>
      <div className="research-number-stepper">
        <button
          aria-controls={id}
          aria-label={`Decrease ${actionLabel}`}
          disabled={!canDecrease}
          onClick={() => onChange(nextBoundedInteger(value, minimum, maximum, -1))}
          type="button"
        >
          <Minus aria-hidden="true" size={16} weight="regular" />
        </button>
        <input
          id={id}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          inputMode="numeric"
          max={maximum}
          min={minimum}
          onChange={(event) => onChange(event.target.value)}
          required
          step={1}
          type="number"
          value={value}
        />
        <button
          aria-controls={id}
          aria-label={`Increase ${actionLabel}`}
          disabled={!canIncrease}
          onClick={() => onChange(nextBoundedInteger(value, minimum, maximum, 1))}
          type="button"
        >
          <Plus aria-hidden="true" size={16} weight="regular" />
        </button>
      </div>
      {error && <small id={`${id}-error`} className="inline-status-error">{error}</small>}
    </div>
  );
}

export function ResearchDraftWorkspace({
  researcherId,
  folder,
  catalog,
  data,
  folderNavigation,
  storage = window.localStorage,
  confirmDiscard = (message) => window.confirm(message),
  startNewOnOpen = typeof window !== "undefined" && new URLSearchParams(window.location.search).has("new"),
}: Omit<WorkspaceResources, "folders"> & {
  researcherId: string;
  folderNavigation?: ReactNode;
  storage?: Storage;
  confirmDiscard?: (message: string) => boolean;
  startNewOnOpen?: boolean;
}) {
  const [draft, setDraft] = useState<ResearchDraft>(() =>
    loadResearchDraft(storage, researcherId, folder.id));
  const [storageError, setStorageError] = useState<string | null>(null);
  const [diagnosticState, setDiagnosticState] = useState<DiagnosticState>({ kind: "idle", result: null });
  const [admissionFeedback, setAdmissionFeedback] = useState<AdmissionFeedback | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const workspace = useRef<HTMLElement>(null);
  const alphaEditor = useRef<AlphaFormulaEditorHandle>(null);
  const exposureEditor = useRef<AlphaFormulaEditorHandle>(null);
  const [validationAttempted, setValidationAttempted] = useState(false);
  const [pendingInput, setPendingInput] = useState<ResearchInputField | null>(null);
  const direct = draft.researchKind === "strategy_backtest" && draft.strategyMode === "direct";
  const builtinAlpha = usesBuiltinAlpha(draft);
  const builtinPortfolio = usesBuiltinPortfolio(draft);
  const inputIssues = validationAttempted ? researchInputIssues(researchInputs(draft)) : [];
  const inputError = (field: ResearchInputField) => inputIssues.find((issue) => issue.field === field)?.message;
  useEffect(() => {
    if (pendingInput === null) return;
    if (pendingInput === "formula") alphaEditor.current?.focus();
    else if (pendingInput === "exposureExpression") exposureEditor.current?.focus();
    else {
      const input = workspace.current?.querySelector<HTMLElement>(inputSelector(pendingInput));
      const disclosure = input?.closest("details");
      if (disclosure) disclosure.open = true;
      input?.focus();
    }
    setPendingInput(null);
  }, [pendingInput, settingsOpen]);
  function focusInput(field: ResearchInputField) {
    if (field.startsWith("costs.") || ["neutralization", "initialCashCny", "volatilityWindow", "exposureExpression"].includes(field)) setSettingsOpen(true);
    setPendingInput(field);
  }
  function validateInputs(): boolean {
    setValidationAttempted(true);
    const issues = researchInputIssues(researchInputs(draft));
    if (issues.length === 0) return true;
    focusInput(issues[0].field);
    return false;
  }
  const [fieldsOpen, setFieldsOpen] = useState(false);
  const fieldsTrigger = useRef<HTMLButtonElement>(null);
  const fieldsPanel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (fieldsOpen) fieldsPanel.current?.querySelector<HTMLInputElement>('input[role="searchbox"]')?.focus();
  }, [fieldsOpen]);
  function closeFields() {
    setFieldsOpen(false);
    fieldsTrigger.current?.focus();
  }
  function fieldsButton() {
    return <button className="button button-quiet" type="button" aria-expanded={fieldsOpen}
      aria-controls="research-fields-panel" onClick={event => {
        fieldsTrigger.current = event.currentTarget;
        setFieldsOpen(open => !open);
      }}>Browse fields</button>;
  }
  const [exposureDiagnosticState, setExposureDiagnosticState] = useState<DiagnosticState>({ kind: "idle", result: null });
  const exposureDiagnostics = useRef(createDiagnosticsScheduler(coreFetch, undefined, "exposure"));
  const [specFeedback, setSpecFeedback] = useState<{
    key: string; checking: boolean; message: string; issues: ResearchRunAdmissionRejection["issues"];
  } | null>(null);
  const specController = useRef<AbortController | null>(null);
  const specKey = JSON.stringify(researchInputs(draft));
  const diagnostics = useRef(createDiagnosticsScheduler());
  const handledGlobalNew = useRef(false);
  const admissionGeneration = useRef(0);
  const admissionController = useRef<AbortController | null>(null);

  useEffect(() => {
    diagnostics.current.diagnose(builtinAlpha ? draft.formula : "", setDiagnosticState);
  }, [draft.formula, builtinAlpha]);
  useEffect(() => {
    exposureDiagnostics.current.diagnose(
      builtinPortfolio ? draft.exposureExpression : "",
      setExposureDiagnosticState,
    );
  }, [draft.exposureExpression, builtinPortfolio]);
  useEffect(() => {
    specController.current?.abort();
  }, [specKey]);
  useEffect(() => () => {
    diagnostics.current.dispose();
    exposureDiagnostics.current.dispose();
    specController.current?.abort();
    admissionGeneration.current += 1;
    admissionController.current?.abort();
  }, []);
  useEffect(() => {
    if (!startNewOnOpen || handledGlobalNew.current) return;
    handledGlobalNew.current = true;
    startNewResearch();
    if (typeof window !== "undefined") window.history.replaceState(null, "", "/research");
  }, [startNewOnOpen]);

  function updateDraft(change: (current: ResearchDraft) => ResearchDraft): void {
    setDraft((current) => {
      const next = change(current);
      try {
        persistResearchDraft(storage, researcherId, folder.id, next);
        setStorageError(null);
      } catch {
        setStorageError("This Draft could not be retained in this browser.");
      }
      return next;
    });
  }

  function startNewResearch(): void {
    if (
      hasUnexecutedChanges(draft) &&
      !confirmDiscard("Start a new Research and discard unexecuted browser changes?")
    ) return;
    storage.removeItem(researchDraftKey(researcherId, folder.id));
    setDraft(emptyResearchDraft());
    setValidationAttempted(false);
    setSettingsOpen(false);
    setStorageError(null);
    setAdmissionFeedback(null);
  }

  async function checkConfiguration(): Promise<void> {
    if (!validateInputs()) return;
    specController.current?.abort();
    const controller = new AbortController();
    specController.current = controller;
    const key = specKey;
    setSpecFeedback({ key, checking: true, message: "Checking configuration…", issues: [] });
    try {
      const response = await coreFetch("/api/research/diagnostics", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(researchSpec(researchInputs(draft))), signal: controller.signal,
      });
      if (!response.ok) throw new Error("Configuration check is unavailable. Try again.");
      const result = await response.json() as { valid: boolean; issues: ResearchRunAdmissionRejection["issues"] };
      if (controller.signal.aborted) return;
      setSpecFeedback({
        key, checking: false, issues: result.issues,
        message: result.valid ? "Configuration is valid. Data and capacity are checked again when submitted." : "Resolve the configuration issues below.",
      });
    } catch {
      if (controller.signal.aborted) return;
      setSpecFeedback({ key, checking: false, issues: [], message: "Configuration check is unavailable. Try again." });
    }
  }

  async function runResearch(): Promise<void> {
    if (submitting || !validateInputs()) return;
    const begun = beginResearchRun(
      draft,
      folder.id,
      () => `research_${crypto.randomUUID()}`,
    );
    try {
      persistResearchDraft(storage, researcherId, folder.id, begun.draft);
      setStorageError(null);
    } catch {
      setStorageError("This Draft could not be retained in this browser.");
      return;
    }
    setDraft(begun.draft);
    setAdmissionFeedback(null);
    setSubmitting(true);
    const generation = ++admissionGeneration.current;
    admissionController.current?.abort();
    const controller = new AbortController();
    admissionController.current = controller;
    try {
      const response = await coreFetch("/api/research-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(begun.command),
        signal: controller.signal,
      });
      if (generation !== admissionGeneration.current) return;
      if (response.status === 422) {
        const rejection = (await response.json()) as ResearchRunAdmissionRejection;
        if (generation !== admissionGeneration.current) return;
        setAdmissionFeedback({ key: JSON.stringify(researchInputs(begun.draft)), issues: rejection.issues });
        return;
      }
      if (!response.ok) throw new Error(`Research Run request failed (${response.status})`);
      const accepted = (await response.json()) as { id: string };
      if (generation !== admissionGeneration.current) return;
      let next: ResearchDraft | null;
      try {
        next = finishResearchRun(
          storage,
          researcherId,
          folder.id,
          begun.command.request_id,
        );
      } catch {
        setStorageError("The accepted Run is safe, but this Draft could not be retained in this browser.");
        return;
      }
      if (next === null) return;
      setDraft(next);
      setStorageError(null);
      window.location.assign(`/research-runs/${accepted.id}`);
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== admissionGeneration.current) return;
      setAdmissionFeedback({
        key: JSON.stringify(researchInputs(begun.draft)),
        issues: [{
          code: "RUN_UNAVAILABLE",
          field: "run",
          message: reason instanceof Error ? reason.message : "Research Run request failed",
          severity: "error",
          range: null,
        }],
      });
    } finally {
      if (generation === admissionGeneration.current) {
        admissionController.current = null;
        setSubmitting(false);
      }
    }
  }

  const coverage = data.market_research_readiness ? data.market_coverage : null;
  const previewDiagnostics = diagnosticState.kind === "complete"
    ? diagnosticState.result.diagnostics
    : [];
  const admissionDiagnostics = admissionFeedback?.key === specKey
    ? admissionFeedback.issues.flatMap(issueAsFormulaDiagnostic)
    : [];
  const serverDiagnostics = admissionDiagnostics.length > 0
    ? admissionDiagnostics
    : previewDiagnostics;
  const visibleIssues = admissionFeedback?.key === specKey
    ? admissionFeedback.issues
    : [];
  function programError(field: ResearchInputField): string | undefined {
    if (drawdownFields.includes(field as DrawdownField)) {
      const serverKey = { drawdownThreshold: "drawdown_threshold", drawdownMaximumExposure: "maximum_stock_exposure", drawdownCooldownSessions: "cooldown_sessions" }[field as DrawdownField];
      const issues = [...visibleIssues, ...(specFeedback?.key === specKey ? specFeedback.issues : [])];
      return inputError(field) ?? issues.find(issue => issue.field.includes(`portfolio_drawdown.${serverKey}`))?.message;
    }
    if (field.startsWith("takeProfitTiers.")) {
      const [, index, key] = field.split(".");
      const serverKey = key === "profitThreshold" ? "profit_threshold" : "cumulative_reduction";
      const issues = [...visibleIssues, ...(specFeedback?.key === specKey ? specFeedback.issues : [])];
      return inputError(field) ?? issues.find(issue => issue.field.includes(`take_profit_tiers.${index}.${serverKey}`))?.message;
    }
    if (field === "stopLossThreshold" || field === "maximumHoldingSessions" || field === "minimumHoldingSessions") {
      const issues = [...visibleIssues, ...(specFeedback?.key === specKey ? specFeedback.issues : [])];
      const serverField = { stopLossThreshold: "stop_loss_threshold", maximumHoldingSessions: "maximum_holding_sessions", minimumHoldingSessions: "minimum_holding_sessions" }[field];
      return inputError(field) ?? issues.find(issue => issue.field.includes(serverField))?.message;
    }
    const [stage, input] = field.includes(".") ? field.split(".") : [null, field];
    const serverField = (stage ? `modules.${stage}.` : "") + {
      programSource: "program.source", programParameters: "program.parameters",
      programFields: "program.data_requirements", programHistorySessions: "program.data_requirements",
    }[input as ProgramInputField];
    const issues = [...visibleIssues, ...(specFeedback?.key === specKey ? specFeedback.issues : [])];
    return inputError(field) ?? issues.find(issue => issue.field === serverField || issue.field.startsWith(`${serverField}.`))?.message;
  }
  function costError(field: CostField): string | undefined {
    const path = `costs.${field}` as const;
    const issues = [...visibleIssues, ...(specFeedback?.key === specKey ? specFeedback.issues : [])];
    return inputError(path) ?? issues.find(issue => issue.field === path)?.message;
  }
  const alphaAuthoring = <>
        <div className="formula-workbench">
          <header className="formula-heading">
            <h2 id="alpha-formula-title">Alpha formula</h2>
            {fieldsButton()}
          </header>
          {inputError("formula") && <p className="research-formula-error inline-status-error">{inputError("formula")}</p>}
          <AlphaFormulaEditor
            ref={alphaEditor}
            catalog={catalog}
            diagnostics={serverDiagnostics}
            formula={draft.formula}
            onChange={(formula, editor) => updateDraft((current) => ({ ...current, formula, editor }))}
            selection={draft.editor}
          />
          <footer className="formula-status"><span>Ctrl + Space to autocomplete</span><span>{coverage ? `Market data through ${coverage.end}` : "Market data not ready for research"}</span></footer>
        </div>
        {diagnosticState.kind === "complete" && diagnosticState.result.diagnostics.length > 0 ? (
          <ul aria-label="Formula diagnostics" className="formula-diagnostics">
            {diagnosticState.result.diagnostics.map((diagnostic) => (
              <li key={`${diagnostic.code}-${diagnostic.range.start.offset}`}>
                <code>{diagnostic.code}</code> {diagnostic.message}
              </li>
            ))}
          </ul>
        ) : null}
        {diagnosticState.kind === "unavailable" ? (
          <p className="inline-status inline-status-error" role="status">Formula validation is unavailable.</p>
        ) : null}
  </>;
  return (
    <section ref={workspace} aria-label="Research" className="page-section research-workspace">
      <header className="research-workspace-header">
        {folderNavigation}
        <label className="research-name-field" htmlFor="research-name">
          <span className="visually-hidden">Draft name</span>
          <input
            aria-label="Research name"
            autoComplete="off"
            id="research-name"
            maxLength={200}
            onChange={(event) => updateDraft((current) => ({ ...current, name: event.target.value }))}
            placeholder="Untitled research"
            type="text"
            value={draft.name}
          />
        </label>
        <button className="button research-new" disabled={submitting} onClick={startNewResearch} type="button">
          <Plus aria-hidden="true" size={17} weight="regular" />
          New research
        </button>
      </header>

      <section className="research-setup" aria-label="Research setup">
            <fieldset className="research-kind-control">
              <legend className="visually-hidden">Research type</legend>
              <label className="research-kind-option">
                <input
                  checked={draft.researchKind === "factor_evaluation"}
                  name="research-kind"
                  onChange={() => updateDraft((current) => selectResearchKind(current, "factor_evaluation"))}
                  type="radio"
                  value="factor_evaluation"
                />
                <span>
                  <strong>Factor Evaluation</strong>

                </span>
              </label>
              <label className="research-kind-option">
                <input
                  checked={draft.researchKind === "strategy_backtest"}
                  name="research-kind"
                  onChange={() => updateDraft((current) => selectResearchKind(current, "strategy_backtest"))}
                  type="radio"
                  value="strategy_backtest"
                />
                <span>
                  <strong>Strategy Backtest</strong>

                </span>
              </label>
            </fieldset>
        {draft.researchKind === "strategy_backtest" && <div className="research-parameter-field research-strategy-mode">
          <label htmlFor="strategy-mode">Strategy mode</label>
          <select id="strategy-mode" value={draft.strategyMode} onChange={event => {
            const mode = event.target.value;
            if (mode === "framework" || mode === "direct") updateDraft(current => selectStrategyMode(current, mode));
          }}>
            <option value="framework">Framework · Decision modules</option>
            <option value="direct">Direct · Python</option>
          </select>
        </div>}
        <div className="research-quick-settings">
            <ResearchDateFields
              startError={inputError("startDate")} endError={inputError("endDate")}
              coverageEnd={coverage?.end ?? null}
              coverageStart={coverage?.start ?? null}
              endDate={draft.endDate}
              onChange={({ startDate, endDate }) => updateDraft((current) => ({
                ...current,
                startDate,
                endDate,
              }))}
              startDate={draft.startDate}
            />
            <div className="research-parameter-field research-universe-field">
              <div className="research-parameter-heading"><label htmlFor="research-universe">Universe</label><ResearchParameterHelp label="Universe" text="Top stocks ranked by average traded value over the latest 20 trading days. Membership changes over time. These are liquidity rankings, not index constituents." /></div>
              <select id="research-universe" aria-invalid={Boolean(inputError("universe"))} aria-describedby={inputError("universe") ? "universe-error" : undefined} onChange={(event) => updateDraft((current) => ({ ...current, universe: event.target.value }))} value={draft.universe}>
                <option value="">Not selected</option>
                <option value="top300">Top 300</option>
                <option value="top1000">Top 1000</option>
                <option value="top2000">Top 2000</option>
                <option value="top3000">Top 3000</option>
              </select>
              {inputError("universe") && <small id="universe-error" className="inline-status-error">{inputError("universe")}</small>}
            </div>

        </div>
      </section>

      <aside ref={fieldsPanel} id="research-fields-panel" className="research-fields-panel" aria-label="Field browser" hidden={!fieldsOpen}
        onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); closeFields(); } }}>
        <header><h2>Browse fields</h2><button className="button button-quiet" type="button" aria-label="Close field browser" onClick={closeFields}><X aria-hidden="true" size={18} /></button></header>
        {fieldsOpen && <ResearchFieldCatalog catalog={catalog} />}
      </aside>
      <section className="research-editor-panel" aria-label={direct ? "Python authoring" : draft.researchKind === "strategy_backtest" ? "Framework authoring" : "Alpha authoring"}>
        {direct ? <PythonStrategyAuthoring inputs={draft} error={programError}
          onChange={changes => updateDraft(current => ({ ...current, ...changes }))}
          fieldsButton={fieldsButton()} /> : draft.researchKind === "strategy_backtest" ? <FrameworkAuthoring
          drawdown={draft}
          updateDrawdown={changes => updateDraft(current => ({ ...current, ...changes }))}
          takeProfitTiers={draft.takeProfitTiers}
          updateTakeProfitTiers={takeProfitTiers => updateDraft(current => ({ ...current, takeProfitTiers }))}
          stopLossThreshold={draft.stopLossThreshold}
          maximumHoldingSessions={draft.maximumHoldingSessions}
          minimumHoldingSessions={draft.minimumHoldingSessions}
          updateMinimumHoldingSessions={minimumHoldingSessions => updateDraft(current => ({ ...current, minimumHoldingSessions }))}
          updateMaximumHoldingSessions={maximumHoldingSessions => updateDraft(current => ({ ...current, maximumHoldingSessions }))}
          updateStopLoss={stopLossThreshold => updateDraft(current => ({ ...current, stopLossThreshold }))}
          modules={draft.frameworkModules} error={programError} fieldsButton={fieldsButton} alphaEditor={alphaAuthoring}
          selectModule={(stage, kind) => updateDraft(current => selectFrameworkModule(current, stage, kind))}
          updateProgram={(stage, changes) => updateDraft(current => ({ ...current, frameworkModules: {
            ...current.frameworkModules, [stage]: { ...current.frameworkModules[stage],
              program: { ...current.frameworkModules[stage].program, ...changes } },
          } }))} /> : alphaAuthoring}
        {storageError !== null ? <p className="inline-status inline-status-error" role="alert">{storageError}</p> : null}
        {visibleIssues.length > 0 ? (
          <ul aria-label="Run issues" className="formula-diagnostics">
            {visibleIssues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}><code>{issue.code}</code> {issue.message}</li>
            ))}
          </ul>
        ) : null}
        {draft.researchKind === "strategy_backtest" && <p className="research-spec-feedback">
          {direct ? "Direct · Python strategy." : "Framework · Decision modules."} Decide after the close; simulate trades at the next trading session’s open.
        </p>}
        <div className="research-selection-settings">
          {builtinPortfolio && <>
                <ResearchNumberStepper
                  actionLabel="number of holdings"
                  id="research-holdings-count"
                  label="Holdings count"
                  error={inputError("holdingsCount")}
                  maximum={100}
                  minimum={1}
                  onChange={(value) => updateDraft((current) => ({ ...current, holdingsCount: value }))}
                  value={draft.holdingsCount}
                />
                <ResearchNumberStepper
                  actionLabel="selection interval"
                  id="research-selection-sessions"
                  label="Selection interval (trading days)"
                  error={inputError("selectionEverySessions")}
                  maximum={20}
                  minimum={1}
                  onChange={(value) => updateDraft((current) => ({ ...current, selectionEverySessions: value }))}
                  value={draft.selectionEverySessions}
                />
          </>}
          <button className="button" type="button"
            aria-expanded={settingsOpen} aria-controls="research-parameters" onClick={() => setSettingsOpen((open) => !open)}>
            <SlidersHorizontal aria-hidden="true" size={18} /> Run settings
          </button>
        </div>
      <section className="research-run-settings research-inline-settings" id="research-parameters" aria-label="Run settings" hidden={!settingsOpen}>
          <div className="run-configuration-grid">
            {draft.researchKind === "strategy_backtest" && <>
                <div className="research-parameter-field">
                  <div className="research-parameter-heading"><label htmlFor="initial-cash">Initial cash (CNY)</label><ResearchParameterHelp label="Initial cash (CNY)" text="0.01–1,000,000,000 CNY, up to two decimal places." /></div>
                  <input id="initial-cash"
                    aria-describedby={(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny) ? "initial-cash-help" : undefined}
                    aria-invalid={(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny)}
                    inputMode="decimal"
                    onChange={(event) => updateDraft((current) => ({ ...current, initialCashCny: event.target.value }))}
                    placeholder="100000.00"
                    type="text"
                    value={draft.initialCashCny}
                  />

                  {(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny) && <small id="initial-cash-help" className="inline-status-error">Enter 0.01–1,000,000,000 CNY, with up to two decimal places.</small>}
                </div>
            </>}
            {builtinAlpha && <div className="research-parameter-field">
              <div className="research-parameter-heading"><label htmlFor="research-neutralization">Neutralization</label></div>
              <select id="research-neutralization" aria-invalid={Boolean(inputError("neutralization"))} aria-describedby={inputError("neutralization") ? "neutralization-error" : undefined} onChange={(event) => updateDraft((current) => ({ ...current, neutralization: event.target.value }))} value={draft.neutralization}>
                <option value="">Not selected</option>
                <option value="none">None</option>
                <option value="industry">Industry</option>
              </select>
              {inputError("neutralization") && <small id="neutralization-error" className="inline-status-error">{inputError("neutralization")}</small>}
            </div>}

            {builtinPortfolio ? (
              <>
                <div className="research-parameter-field research-weighting-field">
                  <div className="research-parameter-heading"><label htmlFor="portfolio-weighting">Portfolio weighting</label>
                    <ResearchParameterHelp label="Portfolio weighting" text={<span className="research-help-content">
                      <span>Splits the invested amount across selected stocks. Position sizing formula sets the total amount invested.</span>
                      <span>{draft.weighting === "inverse_volatility"
                        ? "Lower-volatility stocks receive more weight."
                        : draft.weighting === "rank_weight"
                          ? "Higher-ranked stocks receive more weight; tied scores share rank weight."
                          : "Equal weight gives every selected stock the same share."}</span>
                      <span><strong>Example</strong>{draft.weighting === "inverse_volatility"
                        ? "Two stocks with volatility of 1% and 2% receive about 66.7% and 33.3% of the invested amount."
                        : draft.weighting === "rank_weight"
                          ? "Three stocks with distinct scores receive 50%, 33.3% and 16.7% of the invested amount, from highest to lowest rank."
                          : "A 100,000 CNY account at 50% exposure invests 50,000 CNY. With 10 stocks, each targets 5,000 CNY."}</span>
                    </span>} />
                  </div>
                  <select id="portfolio-weighting"
                    value={draft.weighting}
                    onChange={(event) => {
                      const weighting = event.target.value;
                      if (weighting === "equal_weight" || weighting === "rank_weight" || weighting === "inverse_volatility") {
                        updateDraft((current) => ({
                          ...current, weighting,
                          volatilityWindow: weighting !== "inverse_volatility" && !isValidVolatilityWindow(current.volatilityWindow)
                            ? "20" : current.volatilityWindow,
                        }));
                      }
                    }}
                  >
                    <option value="equal_weight">Equal weight</option>
                    <option value="rank_weight">Rank weight</option>
                    <option value="inverse_volatility">Inverse volatility</option>
                  </select>

                </div>
                {draft.weighting === "inverse_volatility" && (
                  <div className="research-parameter-field research-weighting-field">
                  <div className="research-parameter-heading"><label htmlFor="volatility-window">Volatility window (sessions)</label><ResearchParameterHelp label="Volatility window (sessions)" text="Default 20, range 1–252. Uses adjusted Close returns through selection Close and population standard deviation. Zero volatility, insufficient history and unavailable returns are excluded; the next eligible stock is selected." /></div>
                    <input id="volatility-window" type="number" min={1} max={252} step={1}
                      aria-invalid={!isValidVolatilityWindow(draft.volatilityWindow)}
                      aria-describedby={!isValidVolatilityWindow(draft.volatilityWindow) ? "volatility-window-help" : undefined}
                      value={draft.volatilityWindow}
                      onChange={(event) => updateDraft((current) => ({ ...current, volatilityWindow: event.target.value }))}
                    />

                  {!isValidVolatilityWindow(draft.volatilityWindow) && <small id="volatility-window-help" className="inline-status-error">Enter a whole number from 1 to 252.</small>}
                </div>
                )}
                <ResearchPositionSizing ref={exposureEditor} catalog={catalog} expression={draft.exposureExpression} error={inputError("exposureExpression")}
                  diagnostics={exposureDiagnosticState.kind === "complete" ? exposureDiagnosticState.result.diagnostics : []}
                  onChange={(exposureExpression) => updateDraft((current) => ({ ...current, exposureExpression }))} />
                {exposureDiagnosticState.kind === "complete" && !exposureDiagnosticState.result.valid ? (
                  <ul aria-label="Exposure diagnostics" className="formula-diagnostics research-spec-feedback">
                    {exposureDiagnosticState.result.diagnostics.map((issue) => (
                      <li key={`${issue.code}-${issue.range.start.offset}`}>{issue.message}</li>
                    ))}
                  </ul>
                ) : null}
                {exposureDiagnosticState.kind === "unavailable" ? <p className="research-spec-feedback">Exposure check is unavailable.</p> : null}
              </>
            ) : null}
          </div>
          {draft.researchKind === "strategy_backtest" && <SimulationCostSettings costs={draft.costs}
            onChange={costs => updateDraft(current => ({ ...current, costs }))}
            error={costError} />}
      </section>

        <details className="research-notes">
          <summary>Notes</summary>
          <label htmlFor="research-notes">Notes</label>
          <textarea
            aria-describedby="research-notes-limit"
            aria-invalid={Array.from(draft.hypothesis).length > MAX_HYPOTHESIS_LENGTH}
            id="research-notes"
            onChange={(event) => updateDraft((current) => ({ ...current, hypothesis: event.target.value }))}
            placeholder="Optional context for this research"
            rows={2}
            value={draft.hypothesis}
          />
          <p id="research-notes-limit">
            {Array.from(draft.hypothesis).length} / {MAX_HYPOTHESIS_LENGTH} characters
          </p>
        </details>
      </section>

            {specFeedback?.key === specKey ? (
              <div className="research-spec-feedback" role="status">
                <p>{specFeedback.message}</p>
                {specFeedback.issues.length > 0 ? <ul aria-label="Configuration issues">
                  {specFeedback.issues.map((issue, index) => <li key={`${issue.field}-${issue.code}-${index}`}><strong>{issue.field}</strong>: {issue.message}</li>)}
                </ul> : null}
              </div>
            ) : null}
            {inputIssues.length > 0 && <div className="research-input-issues" role="alert">
              <p>Complete these settings to continue:</p>
              <ul>{inputIssues.map((issue) => <li key={issue.field}><button type="button" onClick={() => focusInput(issue.field)}>{issue.message}</button></li>)}</ul>
            </div>}
            <footer className="research-action-bar">
              <button
                className="button" type="button"
                disabled={submitting || (specFeedback?.key === specKey && specFeedback.checking)}
                onClick={() => void checkConfiguration()}
              >Check configuration</button>
              <button
                className="button button-primary"
                disabled={submitting}
                onClick={() => void runResearch()}
                type="button"
              >
                <Play aria-hidden="true" size={17} weight="fill" />
                {submitting ? "Running…" : draft.researchKind === "strategy_backtest" ? "Run backtest" : "Run evaluation"}
              </button>
            </footer>
    </section>
  );
}

type ResearchRunAdmissionIssue = {
  code: string;
  field: string;
  message: string;
  severity: "error";
  range: FormulaDiagnostic["range"] | null;
};

type ResearchRunAdmissionRejection = { issues: ResearchRunAdmissionIssue[] };
type AdmissionFeedback = {
  key: string;
  issues: ResearchRunAdmissionIssue[];
};

function issueAsFormulaDiagnostic(issue: ResearchRunAdmissionIssue): FormulaDiagnostic[] {
  if (issue.field !== "formula" || issue.range === null) return [];
  return [{ code: issue.code, message: issue.message, severity: issue.severity, range: issue.range }];
}

export function ResearchDateFields({
  coverageStart,
  coverageEnd,
  startDate,
  endDate,
  onChange,
  startError,
  endError,
}: {
  startError?: string;
  endError?: string;
  coverageStart: string | null;
  coverageEnd: string | null;
  startDate: string;
  endDate: string;
  onChange: (range: { startDate: string; endDate: string }) => void;
}) {
  const startDateInput = useRef<HTMLInputElement>(null);
  const endDateInput = useRef<HTMLInputElement>(null);
  const commitDateRange = () => onChange({
    startDate: startDateInput.current?.value ?? startDate,
    endDate: endDateInput.current?.value ?? endDate,
  });
  const presets = buildResearchDatePresets(coverageStart, coverageEnd);
  return (
    <div aria-label="Research dates" className="research-date-range" role="group">
      <div className="research-date-field">
        <label htmlFor="research-start-date">Start date</label>
        <div className="research-date-control">
          <input id="research-start-date" aria-invalid={Boolean(startError)} aria-describedby={startError ? "start-date-error" : undefined} ref={startDateInput} aria-label="Research start date" max={endDate || coverageEnd || undefined} min={coverageStart ?? undefined} onBlur={commitDateRange} onChange={commitDateRange} onClick={() => startDateInput.current?.showPicker()} type="date" value={startDate} />
          <button aria-label="Open start date calendar" onClick={() => startDateInput.current?.showPicker()} type="button">
            <CalendarBlank aria-hidden="true" size={18} weight="regular" />
          </button>
        </div>
        {startError && <small id="start-date-error" className="inline-status-error">{startError}</small>}
      </div>
      <div className="research-date-field">
        <label htmlFor="research-end-date">End date</label>
        <div className="research-date-control">
          <input id="research-end-date" aria-invalid={Boolean(endError)} aria-describedby={endError ? "end-date-error" : undefined} ref={endDateInput} aria-label="Research end date" max={coverageEnd ?? undefined} min={startDate || coverageStart || undefined} onBlur={commitDateRange} onChange={commitDateRange} onClick={() => endDateInput.current?.showPicker()} type="date" value={endDate} />
          <button aria-label="Open end date calendar" onClick={() => endDateInput.current?.showPicker()} type="button">
            <CalendarBlank aria-hidden="true" size={18} weight="regular" />
          </button>
        </div>
        {endError && <small id="end-date-error" className="inline-status-error">{endError}</small>}
      </div>
      <div aria-label="Quick date ranges" className="research-date-presets" role="group">
        {presets.map((preset) => {
          const active = preset.startDate !== null &&
            preset.startDate === startDate &&
            preset.endDate === endDate;
          return (
            <button
              aria-label={preset.accessibleLabel}
              aria-pressed={active}
              disabled={preset.startDate === null || preset.endDate === null}
              key={preset.label}
              onClick={() => {
                if (preset.startDate === null || preset.endDate === null) return;
                onChange({ startDate: preset.startDate, endDate: preset.endDate });
              }}
              type="button"
            >
              {preset.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ResearchParameterHelp({ label, text }: { label: string; text: ReactNode }) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState({ above: false, maxHeight: 0 });
  const show = () => {
    const bounds = button.current?.getBoundingClientRect();
    if (!bounds) return;
    const below = window.innerHeight - bounds.bottom;
    const above = bounds.top > below;
    setPlacement({ above, maxHeight: Math.max(0, (above ? bounds.top : below) - 16) });
    setOpen(true);
  };
  return <span className="research-parameter-help" onMouseEnter={show} onMouseLeave={() => setOpen(false)}>
    <button ref={button} type="button" aria-label={{ "Initial cash (CNY)": "Cash requirements", "Portfolio weighting": "Weighting help", "Volatility window (sessions)": "Volatility calculation help", "Exposure expression": "Exposure formula help", "Universe": "Stock universe help" }[label]} aria-describedby={open ? id : undefined}
      onFocus={show} onBlur={() => setOpen(false)}
      onClick={show} onKeyDown={(event) => {
        if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
      }}><Info aria-hidden="true" size={16} /></button>
    {open && <span role="tooltip" id={id} data-placement={placement.above ? "above" : "below"}
      style={{ maxHeight: placement.maxHeight }}>{text}</span>}
  </span>;
}

const INPUT_SELECTORS: Record<Exclude<ResearchInputField, TakeProfitField | "formula" | "exposureExpression" | `${FrameworkStage}.${ProgramInputField}` | `costs.${CostField}`>, string> = {
  drawdownThreshold: "#risk-drawdownThreshold", drawdownMaximumExposure: "#risk-drawdownMaximumExposure", drawdownCooldownSessions: "#risk-drawdownCooldownSessions",
  hypothesis: "#research-notes", startDate: "#research-start-date", endDate: "#research-end-date",
  universe: "#research-universe", neutralization: "#research-neutralization", initialCashCny: "#initial-cash",
  holdingsCount: "#research-holdings-count", selectionEverySessions: "#research-selection-sessions",
  volatilityWindow: "#volatility-window", stopLossThreshold: "#stop-loss-threshold", maximumHoldingSessions: "#maximum-holding-sessions", minimumHoldingSessions: "#minimum-holding-sessions",
  programSource: "#python-source", programParameters: "#python-parameters",
  programFields: "#python-fields", programHistorySessions: "#python-history",
};

function inputSelector(field: Exclude<ResearchInputField, "formula" | "exposureExpression">): string {
  if (field.startsWith("takeProfitTiers.")) {
    const [, index, key] = field.split(".");
    return `#take-profit-${index}-${key}`;
  }
  if (field.startsWith("costs.")) return `#cost-${field.slice(6)}`;
  const [stage, input] = field.split(".");
  if (frameworkStages.includes(stage as FrameworkStage) && programInputFields.includes(input as ProgramInputField)) {
    return `#${stage}-${INPUT_SELECTORS[input as ProgramInputField].slice(1)}`;
  }
  return INPUT_SELECTORS[field as keyof typeof INPUT_SELECTORS];
}

function ResearchPositionSizing({ ref, catalog, expression, diagnostics, onChange, error }: {
  ref: Ref<AlphaFormulaEditorHandle>;
  error?: string;
  catalog: AlphaCatalog; expression: string; diagnostics: FormulaDiagnostic[]; onChange: (expression: string) => void;
}) {
  const [selection, setSelection] = useState({ anchor: 0, head: 0 });
  return <div className="research-exposure-expression">
    <div className="research-parameter-heading"><h3>Position sizing formula</h3>
      <ResearchParameterHelp label="Exposure expression" text={<span className="research-help-content">
        <span>Sets the fraction of account equity invested. The rest stays in cash; Portfolio weighting divides the invested amount among stocks.</span>
        <span><strong>Fixed exposure</strong><code>0.5</code> targets 50%: 50,000 CNY in a 100,000 CNY account. Use <code>1</code> for 100% or <code>0</code> to stay in cash.</span>
        <span><strong>Market-based example</strong>
          <code className="research-help-formula">{"if_else(\n  universe_advancing_fraction() > 0.5,\n  1, 0.3\n)"}</code>
          Targets 100% when more than half the valid stocks in your Universe rose that session; otherwise 30%.
        </span>
        <span>Output must be 0–1. Calculated each Close; changes trade at the next Open.</span>
      </span>} />
    </div>
    <AlphaFormulaEditor ref={ref} catalog={catalog} context="exposure" diagnostics={diagnostics} formula={expression} selection={selection}
      onChange={(value, nextSelection) => { setSelection(nextSelection); onChange(value); }} />
    {error && <small id="position-sizing-error" className="inline-status-error">{error}</small>}
  </div>;
}
