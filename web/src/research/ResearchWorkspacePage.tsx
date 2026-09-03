import {
  CalendarBlank,
  CaretDown,
  FolderSimple,
  Minus,
  Play,
  Plus,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AlphaCatalog } from "../alphaCatalog";
import { coreFetch } from "../auth/coreFetch";
import type { DataOverview } from "../data/DataPage";
import { AlphaFormulaEditor } from "./AlphaFormulaEditor";
import { buildResearchDatePresets } from "./dateRange";
import {
  createDiagnosticsScheduler,
  type DiagnosticState,
  type FormulaDiagnostic,
} from "./diagnostics";
import {
  beginResearchRun,
  emptyResearchDraft,
  finishResearchRun,
  hasUnexecutedChanges,
  isCompleteResearchInputs,
  loadResearchDraft,
  persistResearchDraft,
  researchInputs,
  researchDraftKey,
  selectResearchKind,
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

export function ResearchWorkspacePage({ researcherId }: { researcherId: string }) {
  const [resources, setResources] = useState<WorkspaceResources | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [folderError, setFolderError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [folderResponse, catalogResponse, dataResponse] = await Promise.all([
        coreFetch("/api/research-folders"),
        coreFetch("/api/alpha/catalog"),
        coreFetch("/api/data"),
      ]);
      if (!folderResponse.ok || !catalogResponse.ok || !dataResponse.ok) {
        throw new Error("Research workspace unavailable");
      }
      const folders = (await folderResponse.json()) as ResearchFolderList;
      const defaults = folders.items.filter((folder) => folder.is_default);
      if (defaults.length !== 1) throw new Error("Default Folder unavailable");
      const parameters = new URLSearchParams(window.location.search);
      const requestedFolderId = parameters.has("new") ? null : parameters.get("folder");
      const selected = folders.items.find((folder) => folder.id === requestedFolderId) ?? defaults[0];
      setResources({
        folder: selected,
        folders: folders.items,
        catalog: (await catalogResponse.json()) as AlphaCatalog,
        data: (await dataResponse.json()) as DataOverview,
      });
    } catch (reason: unknown) {
      setResources(null);
      setError(reason instanceof Error ? reason.message : "Research workspace unavailable");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

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
      <ResearchFolderNavigation
        activeFolder={resources.folder}
        error={folderError}
        folders={resources.folders}
        onCreate={createFolder}
        onDelete={deleteFolder}
        onRename={renameFolder}
      />
      <ResearchDraftWorkspace
        key={`${researcherId}:${resources.folder.id}`}
        researcherId={researcherId}
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
      <span className="research-control-label">Folder</span>
      <details aria-label="Research Folders" className="research-folder-navigation">
        <summary>
          <FolderSimple aria-hidden="true" size={18} weight="regular" />
          <span>{activeFolder.name} folder</span>
          <CaretDown aria-hidden="true" className="folder-menu-caret" size={16} weight="regular" />
        </summary>
        <div className="folder-menu-panel">
          <div className="folder-navigation-heading">
            <span>Folders</span>
            <small>One level</small>
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
}: {
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
    </div>
  );
}

export function ResearchDraftWorkspace({
  researcherId,
  folder,
  catalog,
  data,
  storage = window.localStorage,
  confirmDiscard = (message) => window.confirm(message),
  startNewOnOpen = typeof window !== "undefined" && new URLSearchParams(window.location.search).has("new"),
}: Omit<WorkspaceResources, "folders"> & {
  researcherId: string;
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
  const diagnostics = useRef(createDiagnosticsScheduler());
  const handledGlobalNew = useRef(false);
  const admissionGeneration = useRef(0);
  const admissionController = useRef<AbortController | null>(null);

  useEffect(() => {
    diagnostics.current.diagnose(draft.formula, setDiagnosticState);
  }, [draft.formula]);
  useEffect(() => () => {
    diagnostics.current.dispose();
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
    setStorageError(null);
    setAdmissionFeedback(null);
  }

  async function runResearch(): Promise<void> {
    const inputs = researchInputs(draft);
    if (!isCompleteResearchInputs(inputs) || submitting) return;
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
        setAdmissionFeedback({ formula: begun.command.formula, issues: rejection.issues });
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
        formula: begun.command.formula,
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
  const admissionDiagnostics = admissionFeedback?.formula === draft.formula
    ? admissionFeedback.issues.flatMap(issueAsFormulaDiagnostic)
    : [];
  const serverDiagnostics = admissionDiagnostics.length > 0
    ? admissionDiagnostics
    : previewDiagnostics;
  const visibleIssues = admissionFeedback?.formula === draft.formula
    ? admissionFeedback.issues
    : [];
  return (
    <section aria-label="Research" className="page-section research-workspace">
      <header className="research-workspace-header">
        <label className="research-name-field" htmlFor="research-name">
          <span className="research-control-label">Draft name</span>
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

      <section className="research-editor-panel" aria-label="Alpha authoring">
        <div className="formula-workbench">
          <header className="formula-heading">
            <span aria-hidden="true" className="formula-heading-symbol">α</span>
            <h2 id="alpha-formula-title">Alpha formula</h2>
          </header>
          <AlphaFormulaEditor
            catalog={catalog}
            diagnostics={serverDiagnostics}
            formula={draft.formula}
            onChange={(formula, editor) => updateDraft((current) => ({ ...current, formula, editor }))}
            selection={draft.editor}
          />
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
        {storageError !== null ? <p className="inline-status inline-status-error" role="alert">{storageError}</p> : null}
        {visibleIssues.length > 0 ? (
          <ul aria-label="Run issues" className="formula-diagnostics">
            {visibleIssues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}><code>{issue.code}</code> {issue.message}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="research-run-settings" id="research-parameters" aria-label="Research parameters">
          <header><h2>Research parameters</h2></header>
          <div className="run-configuration-grid">
            <fieldset className="research-kind-control">
              <legend>Research type</legend>
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
                  <small>Measure predictive strength without constructing a portfolio.</small>
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
                  <small>Evaluate the factor and its portfolio execution.</small>
                </span>
              </label>
            </fieldset>
            <ResearchDateFields
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
            <label>Universe
              <select onChange={(event) => updateDraft((current) => ({ ...current, universe: event.target.value }))} value={draft.universe}>
                <option value="">Not selected</option>
                <option value="top300">Top 300</option>
                <option value="top1000">Top 1000</option>
                <option value="top2000">Top 2000</option>
                <option value="top3000">Top 3000</option>
              </select>
            </label>
            <label>Neutralization
              <select onChange={(event) => updateDraft((current) => ({ ...current, neutralization: event.target.value }))} value={draft.neutralization}>
                <option value="">Not selected</option>
                <option value="none">None</option>
                <option value="industry">Industry</option>
              </select>
            </label>
            {draft.researchKind === "strategy_backtest" ? (
              <>
                <ResearchNumberStepper
                  actionLabel="number of holdings"
                  id="research-holdings-count"
                  label="Holdings count"
                  maximum={100}
                  minimum={1}
                  onChange={(value) => updateDraft((current) => ({ ...current, holdingsCount: value }))}
                  value={draft.holdingsCount}
                />
                <ResearchNumberStepper
                  actionLabel="rebalance interval"
                  id="research-rebalance-sessions"
                  label="Rebalance sessions"
                  maximum={20}
                  minimum={1}
                  onChange={(value) => updateDraft((current) => ({ ...current, rebalanceEverySessions: value }))}
                  value={draft.rebalanceEverySessions}
                />
              </>
            ) : null}
            <div className="research-notes">
              <label htmlFor="research-notes">Notes</label>
              <textarea
                id="research-notes"
                onChange={(event) => updateDraft((current) => ({ ...current, hypothesis: event.target.value }))}
                placeholder="Optional context for this research"
                rows={3}
                value={draft.hypothesis}
              />
            </div>
            <footer>
              <button
                className="button button-primary"
                disabled={!isCompleteResearchInputs(researchInputs(draft)) || submitting}
                onClick={() => void runResearch()}
                type="button"
              >
                <Play aria-hidden="true" size={17} weight="fill" />
                {submitting ? "Running…" : "Run research"}
              </button>
            </footer>
          </div>
      </section>
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
  formula: string;
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
}: {
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
          <input id="research-start-date" ref={startDateInput} aria-label="Research start date" max={endDate || coverageEnd || undefined} min={coverageStart ?? undefined} onBlur={commitDateRange} onChange={commitDateRange} onClick={() => startDateInput.current?.showPicker()} type="date" value={startDate} />
          <button aria-label="Open start date calendar" onClick={() => startDateInput.current?.showPicker()} type="button">
            <CalendarBlank aria-hidden="true" size={18} weight="regular" />
          </button>
        </div>
      </div>
      <div className="research-date-field">
        <label htmlFor="research-end-date">End date</label>
        <div className="research-date-control">
          <input id="research-end-date" ref={endDateInput} aria-label="Research end date" max={coverageEnd ?? undefined} min={startDate || coverageStart || undefined} onBlur={commitDateRange} onChange={commitDateRange} onClick={() => endDateInput.current?.showPicker()} type="date" value={endDate} />
          <button aria-label="Open end date calendar" onClick={() => endDateInput.current?.showPicker()} type="button">
            <CalendarBlank aria-hidden="true" size={18} weight="regular" />
          </button>
        </div>
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
