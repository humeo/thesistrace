import {
  CaretDown,
  CheckCircle,
  Desktop,
  FolderSimple,
  PencilSimple,
  Play,
  Plus,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { DataOverview } from "../data/DataPage";
import { AlphaFormulaEditor, type AlphaCatalog } from "./AlphaFormulaEditor";
import {
  createDiagnosticsScheduler,
  type DiagnosticState,
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
  type ResearchDraft,
} from "./draft";
import type { FormulaDiagnostic } from "./diagnostics";

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

export function ResearchWorkspacePage() {
  const [resources, setResources] = useState<WorkspaceResources | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [folderError, setFolderError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [folderResponse, catalogResponse, dataResponse] = await Promise.all([
        fetch("/api/research-folders"),
        fetch("/api/alpha/catalog"),
        fetch("/api/data"),
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
    const response = await fetch("/api/research-folders", {
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
  }

  async function renameFolder(folderId: string, name: string): Promise<void> {
    setFolderError(null);
    const response = await fetch(`/api/research-folders/${folderId}`, {
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
  }

  async function deleteFolder(folder: ResearchFolder): Promise<void> {
    const currentResources = resources;
    if (currentResources === null) return;
    if (!window.confirm(`Delete the empty ${folder.name} Folder and its browser Draft?`)) return;
    setFolderError(null);
    const response = await fetch(`/api/research-folders/${folder.id}`, { method: "DELETE" });
    if (!response.ok) {
      setFolderError(await folderMutationError(response));
      return;
    }
    window.localStorage.removeItem(researchDraftKey(folder.id));
    const defaultFolder = currentResources.folders.find((item) => item.is_default);
    if (defaultFolder === undefined) throw new Error("Default Folder unavailable");
    setResources({
      ...currentResources,
      folder: defaultFolder,
      folders: currentResources.folders.filter((item) => item.id !== folder.id),
    });
    window.history.replaceState(null, "", "/research");
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
      <ResearchDraftWorkspace key={resources.folder.id} {...resources} />
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

export function ResearchDraftWorkspace({
  folder,
  catalog,
  data,
  storage = window.localStorage,
  confirmDiscard = (message) => window.confirm(message),
  startNewOnOpen = typeof window !== "undefined" && new URLSearchParams(window.location.search).has("new"),
}: Omit<WorkspaceResources, "folders"> & {
  storage?: Storage;
  confirmDiscard?: (message: string) => boolean;
  startNewOnOpen?: boolean;
}) {
  const [draft, setDraft] = useState<ResearchDraft>(() => loadResearchDraft(storage, folder.id));
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
        persistResearchDraft(storage, folder.id, next);
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
    storage.removeItem(researchDraftKey(folder.id));
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
      persistResearchDraft(storage, folder.id, begun.draft);
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
      const response = await fetch("/api/research-runs", {
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
        next = finishResearchRun(storage, folder.id, begun.command.request_id);
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
          <span className="visually-hidden">Research name</span>
          <input
            aria-label="Research name"
            id="research-name"
            maxLength={200}
            onChange={(event) => updateDraft((current) => ({ ...current, name: event.target.value }))}
            placeholder="Untitled research"
            value={draft.name}
          />
          <PencilSimple aria-hidden="true" size={19} weight="regular" />
        </label>
        <button className="button button-quiet research-new" disabled={submitting} onClick={startNewResearch}>
          <Plus aria-hidden="true" size={17} weight="regular" />
          <span className="visually-hidden">New Research</span>
        </button>
        <button className="context-disclosure" onClick={() => document.getElementById("research-parameters")?.scrollIntoView({ block: "start" })} type="button">
          Hypothesis
          <CaretDown aria-hidden="true" size={15} weight="regular" />
        </button>
        <span className="formula-validity">
          <CheckCircle aria-hidden="true" size={22} weight="regular" />
          <DiagnosticsStatus state={diagnosticState} />
        </span>
        <span className="browser-save-status">
          <Desktop aria-hidden="true" size={19} weight="regular" />
          <span className="visually-hidden">{folder.name} Folder. </span>
          Saved in this browser
        </span>
        <button className="button button-primary run-settings-link" onClick={() => document.getElementById("research-parameters")?.scrollIntoView({ block: "start" })} type="button">
          <Play aria-hidden="true" size={17} weight="fill" />
          Run…
        </button>
      </header>

      <section className="research-editor-panel" aria-label="Alpha authoring">
          <div className="formula-heading"><label>Alpha formula</label></div>
          <AlphaFormulaEditor
            catalog={catalog}
            diagnostics={serverDiagnostics}
            formula={draft.formula}
            onChange={(formula, editor) => updateDraft((current) => ({ ...current, formula, editor }))}
            selection={draft.editor}
          />
          <AlphaFieldReference catalog={catalog} />
          {diagnosticState.kind === "complete" && diagnosticState.result.diagnostics.length > 0 ? (
            <ul aria-label="Formula diagnostics" className="formula-diagnostics">
              {diagnosticState.result.diagnostics.map((diagnostic) => (
                <li key={`${diagnostic.code}-${diagnostic.range.start.offset}`}>
                  <code>{diagnostic.code}</code> {diagnostic.message}
                </li>
              ))}
            </ul>
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
            <ResearchDateFields
              coverageEnd={coverage?.end ?? null}
              coverageStart={coverage?.start ?? null}
              endDate={draft.endDate}
              onEndDateChange={(endDate) => updateDraft((current) => ({ ...current, endDate }))}
              onStartDateChange={(startDate) => updateDraft((current) => ({ ...current, startDate }))}
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
            <label>Holdings count
              <input inputMode="numeric" onChange={(event) => updateDraft((current) => ({ ...current, holdingsCount: event.target.value }))} value={draft.holdingsCount} />
            </label>
            <label>Rebalance sessions
              <input inputMode="numeric" onChange={(event) => updateDraft((current) => ({ ...current, rebalanceEverySessions: event.target.value }))} value={draft.rebalanceEverySessions} />
            </label>
            <div className="research-hypothesis">
              <label htmlFor="research-hypothesis">Hypothesis</label>
              <textarea
                id="research-hypothesis"
                onChange={(event) => updateDraft((current) => ({ ...current, hypothesis: event.target.value }))}
                placeholder="What should this signal explain?"
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

function AlphaFieldReference({ catalog }: { catalog: AlphaCatalog }) {
  const financialFields = catalog.fields.filter(
    (field) => field.family_id === "equity.financial_pit",
  );
  if (financialFields.length === 0) return null;
  return (
    <details className="alpha-field-reference">
      <summary>Financial fields</summary>
      <div className="alpha-field-reference-list">
        {financialFields.map((field) => (
          <article key={field.field_id}>
            <h3><code>{field.identifier}</code></h3>
            <p>{field.description}</p>
            <dl>
              <div><dt>Unit</dt><dd>{field.unit}</dd></div>
              <div><dt>Time semantics</dt><dd>{fieldTimeSemantics(field)}</dd></div>
              <div>
                <dt>Applicability</dt>
                <dd>{field.applicable_company_types.length > 0
                  ? `Company types ${field.applicable_company_types.join(", ")}`
                  : "All supported instruments"}</dd>
              </div>
              <div><dt>Missingness</dt><dd>{humanizeContract(field.missingness)}</dd></div>
              <div><dt>Example</dt><dd><code>{field.example}</code></dd></div>
            </dl>
          </article>
        ))}
      </div>
    </details>
  );
}

function fieldTimeSemantics(field: AlphaCatalog["fields"][number]): string {
  if (field.report_period_selection === "latest_visible_full_year") {
    return "Latest full year visible on each Research Session";
  }
  if (field.report_period_selection === "latest_visible_quarterly_or_annual") {
    return "Latest quarterly or annual report visible on each Research Session";
  }
  return humanizeContract(field.report_period_selection);
}

function humanizeContract(value: string): string {
  const text = value.replaceAll("_", " ").replaceAll("-", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
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

function DiagnosticsStatus({ state }: { state: DiagnosticState }) {
  if (state.kind === "idle") return <span className="diagnostic-status">Not checked</span>;
  if (state.kind === "checking") return <span className="diagnostic-status">Checking…</span>;
  if (state.kind === "unavailable") return <span className="diagnostic-status diagnostic-error">Unavailable · not validated</span>;
  if (state.result.valid) return <span className="diagnostic-status diagnostic-valid">Formula valid</span>;
  return <span className="diagnostic-status diagnostic-error">{state.result.diagnostics.length} issue{state.result.diagnostics.length === 1 ? "" : "s"}</span>;
}

export function ResearchDateFields({
  coverageStart,
  coverageEnd,
  startDate,
  endDate,
  onStartDateChange,
  onEndDateChange,
}: {
  coverageStart: string | null;
  coverageEnd: string | null;
  startDate: string;
  endDate: string;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
}) {
  return (
    <fieldset>
      <legend>Research period</legend>
      <p>{coverageStart && coverageEnd ? `Available data: ${coverageStart} to ${coverageEnd}` : "Current Data is not ready."}</p>
      <label>Start date
        <input aria-label="Research start date" max={endDate || coverageEnd || undefined} min={coverageStart ?? undefined} onChange={(event) => onStartDateChange(event.target.value)} type="date" value={startDate} />
      </label>
      <label>End date
        <input aria-label="Research end date" max={coverageEnd ?? undefined} min={startDate || coverageStart || undefined} onChange={(event) => onEndDateChange(event.target.value)} type="date" value={endDate} />
      </label>
    </fieldset>
  );
}
