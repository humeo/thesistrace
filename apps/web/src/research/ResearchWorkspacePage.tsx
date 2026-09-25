import { drawdownFields, type DrawdownField } from "./portfolioDrawdown";
import type { TakeProfitField } from "./takeProfit";
import {
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

import { Trans } from "react-i18next";
import type { AlphaCatalog } from "../alphaCatalog";
import { coreFetch } from "../auth/coreFetch";
import type { BrowserLocation } from "../auth/routing";
import { interfaceLocale, useTranslation } from "../i18n";
import { ResearchFieldCatalog, type DataOverview } from "../data/DataPage";
import { AlphaFormulaEditor, type AlphaFormulaEditorHandle, type EditorDiagnostic } from "./AlphaFormulaEditor";
import { folderDisplayName, folderMutationError, type FolderError } from "./folders";
import { formatResearchIssue, researchIssueField, type ResearchRunAdmissionIssue } from "./admission";
import { PythonStrategyAuthoring } from "./PythonStrategyAuthoring";
import { FrameworkAuthoring } from "./FrameworkAuthoring";
import { SimulationCostSettings } from "./SimulationCostSettings";
import type { CostField } from "./simulationCosts";
import { frameworkStages, type FrameworkStage } from "./frameworkModules";
import { programInputFields, type ProgramInputField } from "./pythonStrategy";
import { buildResearchDatePresets, isResearchIsoDate } from "./dateRange";
import { ResearchDateInput } from "./ResearchDateInput";
import { ResearchFieldBrowser } from "./ResearchFieldBrowser";
import { useResearchDraftController } from "./useResearchDraftController";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Field, FieldGroup, FieldLabel } from "../components/ui/field";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { RadioGroup, RadioGroupItem } from "../components/ui/radio-group";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";
import { PageContent, PageHeader } from "../components/layout/Page";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "../components/ui/popover";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "../components/ui/alert-dialog";
import { formatFormulaDiagnostic, type FormulaDiagnostic } from "./diagnostics";
import {
  type ResearchInputField,
  isValidInitialCash,
  isValidVolatilityWindow,
  MAX_HYPOTHESIS_LENGTH,
  researchDraftKey,
  selectResearchKind,
  selectStrategyMode,
  selectFrameworkModule,
  usesBuiltinAlpha,
  usesBuiltinPortfolio,
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
  const { t } = useTranslation("research");
  const [resources, setResources] = useState<WorkspaceResources | null>(null);
  const [error, setError] = useState<"unavailable" | null>(null);
  const [folderError, setFolderError] = useState<FolderError | null>(null);
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
    } catch {
      if (controller.signal.aborted) return;
      setResources(null);
      setError("unavailable");
    }
  }, [location]);

  useEffect(() => {
    void load();
    return () => resourceRequest.current?.abort();
  }, [load]);

  if (error !== null) return (
    <section aria-label={t("title")} className="page-section state-section">
      <p role="alert">{t(error)}</p>
      <button onClick={() => void load()}>{t("retry")}</button>
    </section>
  );
  if (resources === null) return (
    <section aria-label={t("title")} className="page-section state-section">
      <p>{t("opening")}</p>
    </section>
  );
  async function createFolder(name: string): Promise<boolean> {
    setFolderError(null);
    try {
      const response = await coreFetch("/api/research-folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!response.ok) {
        setFolderError(await folderMutationError(response));
        return false;
      }
      const folder = (await response.json()) as ResearchFolder;
      setResources((current) => current === null ? current : {
        ...current,
        folder,
        folders: [...current.folders, folder],
      });
      window.history.replaceState(null, "", `/research?folder=${folder.id}`);
      return true;
    } catch {
      setFolderError("unavailable");
      return false;
    }
  }

  async function renameFolder(folderId: string, name: string): Promise<boolean> {
    setFolderError(null);
    try {
      const response = await coreFetch(`/api/research-folders/${folderId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!response.ok) {
        setFolderError(await folderMutationError(response));
        return false;
      }
      const renamed = (await response.json()) as ResearchFolder;
      setResources((current) => current === null ? current : {
        ...current,
        folder: current.folder.id === renamed.id ? renamed : current.folder,
        folders: current.folders.map((folder) => folder.id === renamed.id ? renamed : folder),
      });
      return true;
    } catch {
      setFolderError("unavailable");
      return false;
    }
  }

  async function deleteFolder(folder: ResearchFolder): Promise<boolean> {
    const currentResources = resources;
    if (currentResources === null) return false;
    setFolderError(null);
    try {
      const response = await coreFetch(`/api/research-folders/${folder.id}`, { method: "DELETE" });
      if (!response.ok) {
        setFolderError(await folderMutationError(response));
        return false;
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
      return true;
    } catch {
      setFolderError("unavailable");
      return false;
    }
  }

  return (
    <section aria-label={t("workspace")} className="research-folder-layout">
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
  error: FolderError | null;
  onCreate: (name: string) => Promise<boolean>;
  onRename: (folderId: string, name: string) => Promise<boolean>;
  onDelete: (folder: ResearchFolder) => Promise<boolean>;
}) {
  const { t } = useTranslation("research");
  const [newName, setNewName] = useState("");
  const [renameName, setRenameName] = useState(activeFolder.name);
  const [menuOpen, setMenuOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ResearchFolder | null>(null);
  const [folderPending, setFolderPending] = useState(false);
  useEffect(() => setRenameName(activeFolder.name), [activeFolder.id, activeFolder.name]);
  return (
    <div className="min-w-0">
      <Popover open={menuOpen} onOpenChange={setMenuOpen}>
        <PopoverTrigger render={<Button variant="outline" size="sm" className="max-[767px]:min-h-11" aria-label={t("folderMenu")} />}>
          <FolderSimple aria-hidden="true" size={17} />
          <span className="max-w-48 truncate">{t("activeFolder", { name: folderDisplayName(activeFolder) })}</span>
          <CaretDown aria-hidden="true" size={14} />
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[min(360px,calc(100vw-32px))] gap-4 p-4">
          <PopoverTitle>{t("folders")}</PopoverTitle>
          <nav aria-label={t("folderNavigation")} className="grid max-h-48 gap-1 overflow-auto">
            {folders.map((folder) => (
              <a
                className="flex min-h-9 items-center justify-between gap-2 rounded-md px-2 text-sm text-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring aria-[current=page]:bg-muted max-[767px]:min-h-11"
                aria-current={folder.id === activeFolder.id ? "page" : undefined}
                href={folder.is_default ? "/research" : `/research?folder=${folder.id}`}
                key={folder.id}
              >
                <span className="truncate">{folderDisplayName(folder)}</span>
                {folder.is_default ? <small className="text-muted-foreground">{t("defaultFolder")}</small> : null}
              </a>
            ))}
          </nav>
          <form className="grid gap-2 border-t border-border pt-3" onSubmit={(event) => {
            event.preventDefault();
            if (newName.trim() === "" || folderPending) return;
            setFolderPending(true);
            void onCreate(newName).then((success) => { if (success) setNewName(""); }).finally(() => setFolderPending(false));
          }}>
            <label className="text-sm font-medium" htmlFor="new-folder-name">{t("newFolder")}</label>
            <div className="flex gap-2">
              <Input id="new-folder-name" className="max-[767px]:min-h-11" maxLength={120} onChange={(event) => setNewName(event.target.value)} value={newName} />
              <Button disabled={newName.trim() === "" || folderPending} size="sm" className="max-[767px]:min-h-11" type="submit">
                <Plus aria-hidden="true" size={16} />{t("create")}
              </Button>
            </div>
          </form>
          {!activeFolder.is_default ? (
            <section aria-label={t("folderActions")} className="grid gap-2 border-t border-border pt-3">
              <label className="text-sm font-medium" htmlFor="rename-folder-name">{t("folderName")}</label>
              <Input id="rename-folder-name" className="max-[767px]:min-h-11" maxLength={120} onChange={(event) => setRenameName(event.target.value)} value={renameName} />
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" className="max-[767px]:min-h-11" disabled={folderPending || renameName.trim() === "" || renameName.trim() === activeFolder.name}
                  onClick={() => { setFolderPending(true); void onRename(activeFolder.id, renameName).finally(() => setFolderPending(false)); }}>
                  {t("renameFolder")}
                </Button>
                <Button variant="destructive" size="sm" className="max-[767px]:min-h-11" disabled={folderPending} onClick={() => { setMenuOpen(false); setDeleteTarget(activeFolder); }}>
                  {t("deleteFolder")}
                </Button>
              </div>
            </section>
          ) : null}
          {error !== null ? <p className="text-sm text-destructive" role="alert">{t(`folderErrors.${error}`)}</p> : null}
        </PopoverContent>
      </Popover>
      <AlertDialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open && !folderPending) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("deleteFolder")}</AlertDialogTitle>
            <AlertDialogDescription>{t("deleteFolderConfirm", { name: folderDisplayName(deleteTarget ?? activeFolder) })}</AlertDialogDescription>
          </AlertDialogHeader>
          {error !== null ? <p className="m-0 text-sm text-destructive" role="alert">{t(`folderErrors.${error}`)}</p> : null}
          <AlertDialogFooter>
            <AlertDialogCancel className="max-[767px]:min-h-11" disabled={folderPending}>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" className="max-[767px]:min-h-11" disabled={folderPending} onClick={() => {
              if (deleteTarget === null) return;
              setFolderPending(true);
              void onDelete(deleteTarget).then((success) => { if (success) setDeleteTarget(null); }).finally(() => setFolderPending(false));
            }}>{t("deleteFolder")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
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
  const { t } = useTranslation("research");
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
          aria-label={t("decrease", { label: actionLabel })}
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
          aria-label={t("increase", { label: actionLabel })}
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
  const { t } = useTranslation("research");
  const locale = interfaceLocale();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const workspace = useRef<HTMLElement>(null);
  const alphaEditor = useRef<AlphaFormulaEditorHandle>(null);
  const exposureEditor = useRef<AlphaFormulaEditorHandle>(null);
  const [pendingInput, setPendingInput] = useState<ResearchInputField | null>(null);
  function focusInput(field: ResearchInputField) {
    if (field.startsWith("costs.") || ["neutralization", "initialCashCny", "volatilityWindow", "exposureExpression"].includes(field)) setSettingsOpen(true);
    setPendingInput(field);
  }
  const {
    draft, hasStoredDraft, storageError, diagnosticState, exposureDiagnosticState,
    admissionFeedback, specFeedback, specKey, submitting, validationAttempted, inputIssues, inputError,
    updateDraft, startNewResearch, checkConfiguration, runResearch,
  } = useResearchDraftController({
    researcherId, folderId: folder.id, storage, confirmDiscard, startNewOnOpen,
    onInvalidInput: focusInput, onNew: () => setSettingsOpen(false),
  });
  const direct = draft.researchKind === "strategy_backtest" && draft.strategyMode === "direct";
  const factor = draft.researchKind === "factor_evaluation";
  const builtinAlpha = usesBuiltinAlpha(draft);
  const builtinPortfolio = usesBuiltinPortfolio(draft);
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
  const [fieldsOpen, setFieldsOpen] = useState(false);
  const fieldsTrigger = useRef<HTMLButtonElement>(null);
  const fieldsPanel = useRef<HTMLElement>(null);
  const restoreEditorFocus = useRef(false);
  function closeFields() {
    setFieldsOpen(false);
  }
  function fieldsButton() {
    return <Button variant="outline" size="sm" className="max-[767px]:min-h-11" type="button" aria-expanded={fieldsOpen}
      aria-controls="research-fields-panel" onClick={event => {
        fieldsTrigger.current = event.currentTarget;
        setFieldsOpen(open => !open);
      }}>{t("browseFields")}</Button>;
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
      const issue = issues.find(issue => issue.field.includes(`portfolio_drawdown.${serverKey}`));
      return inputError(field) ?? (issue ? formatResearchIssue(issue, locale) : undefined);
    }
    if (field.startsWith("takeProfitTiers.")) {
      const [, index, key] = field.split(".");
      const serverKey = key === "profitThreshold" ? "profit_threshold" : "cumulative_reduction";
      const issues = [...visibleIssues, ...(specFeedback?.key === specKey ? specFeedback.issues : [])];
      const issue = issues.find(issue => issue.field.includes(`take_profit_tiers.${index}.${serverKey}`));
      return inputError(field) ?? (issue ? formatResearchIssue(issue, locale) : undefined);
    }
    if (field === "stopLossThreshold" || field === "maximumHoldingSessions" || field === "minimumHoldingSessions") {
      const issues = [...visibleIssues, ...(specFeedback?.key === specKey ? specFeedback.issues : [])];
      const serverField = { stopLossThreshold: "stop_loss_threshold", maximumHoldingSessions: "maximum_holding_sessions", minimumHoldingSessions: "minimum_holding_sessions" }[field];
      const issue = issues.find(issue => issue.field.includes(serverField));
      return inputError(field) ?? (issue ? formatResearchIssue(issue, locale) : undefined);
    }
    const [stage, input] = field.includes(".") ? field.split(".") : [null, field];
    const serverField = (stage ? `modules.${stage}.` : "") + {
      programSource: "program.source", programParameters: "program.parameters",
      programFields: "program.data_requirements", programHistorySessions: "program.data_requirements",
    }[input as ProgramInputField];
    const issues = [...visibleIssues, ...(specFeedback?.key === specKey ? specFeedback.issues : [])];
    const issue = issues.find(issue => issue.field === serverField || issue.field.startsWith(`${serverField}.`));
    return inputError(field) ?? (issue ? formatResearchIssue(issue, locale) : undefined);
  }
  function costError(field: CostField): string | undefined {
    const path = `costs.${field}` as const;
    const issues = [...visibleIssues, ...(specFeedback?.key === specKey ? specFeedback.issues : [])];
    const issue = issues.find(issue => issue.field === path);
    return inputError(path) ?? (issue ? formatResearchIssue(issue, locale) : undefined);
  }
  const alphaAuthoring = <>
        <div className={factor ? "overflow-hidden rounded-lg border border-border bg-card focus-within:ring-2 focus-within:ring-ring/30" : "formula-workbench"}>
          <header className={factor ? "flex min-h-12 items-center justify-between gap-3 border-b border-border px-4" : "formula-heading"}>
            <h2 id="alpha-formula-title" className={factor ? "m-0 text-base font-semibold" : undefined}>{t("formula")}</h2>
            {fieldsButton()}
          </header>
          {inputError("formula") && <p className="research-formula-error inline-status-error">{inputError("formula")}</p>}
          <AlphaFormulaEditor
            ref={alphaEditor}
            catalog={catalog}
            diagnostics={serverDiagnostics}
            formula={draft.formula}
            className={factor ? "h-[280px] min-w-0 overflow-hidden bg-card" : undefined}
            onChange={(formula, editor) => updateDraft((current) => ({ ...current, formula, editor }))}
            selection={draft.editor}
          />
          <footer className={factor ? "flex flex-wrap justify-between gap-2 border-t border-border px-4 py-2 text-xs text-muted-foreground" : "formula-status"}>
            <span>{t("autocomplete")}</span><span>{coverage ? t("marketThrough", { date: coverage.end }) : t("marketNotReady")}</span>
          </footer>
        </div>
        {diagnosticState.kind === "complete" && diagnosticState.result.diagnostics.length > 0 ? (
          <ul aria-label={t("formulaDiagnostics")} className="formula-diagnostics">
            {diagnosticState.result.diagnostics.map((diagnostic) => (
              <li key={`${diagnostic.code}-${diagnostic.range.start.offset}`}>
                <code>{diagnostic.code}</code> {formatFormulaDiagnostic(diagnostic, locale)}
              </li>
            ))}
          </ul>
        ) : null}
        {diagnosticState.kind === "unavailable" ? (
          <p className="inline-status inline-status-error" role="status">{t("diagnosticsUnavailable")}</p>
        ) : null}
  </>;
  if (factor) return (
    <section ref={workspace} aria-label={t("title")} className="@container min-w-0">
      <PageContent width="wide">
        <PageHeader
          title={<Input id="research-name" aria-label={t("name")} autoComplete="off" maxLength={200}
            className="h-11 w-full max-w-[720px] border-transparent bg-transparent px-0 text-2xl font-semibold placeholder:text-foreground hover:border-border focus-visible:border-ring focus-visible:px-2"
            onChange={(event) => updateDraft((current) => ({ ...current, name: event.target.value }))}
            placeholder={t("untitled")} value={draft.name} />}
          description={storageError === null ? t(hasStoredDraft ? "draftSavedLocal" : "draftNew") : t(`storage.${storageError}`)}
          actions={<>{folderNavigation}<Button variant="outline" className="max-[767px]:min-h-11" disabled={submitting} onClick={startNewResearch}>
            <Plus aria-hidden="true" />{t("newResearch")}</Button></>}
        />
        <fieldset className="mb-6 min-w-0 border-0 p-0">
          <legend className="sr-only">{t("kind")}</legend>
          <RadioGroup className="flex flex-wrap gap-2" value={draft.researchKind}
            onValueChange={(value) => {
              if (value === "factor_evaluation" || value === "strategy_backtest") {
                updateDraft((current) => selectResearchKind(current, value));
              }
            }}>
            <label className="flex min-h-10 cursor-pointer items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium has-[[data-checked]]:border-primary has-[[data-checked]]:bg-secondary max-[767px]:min-h-11">
              <RadioGroupItem value="factor_evaluation" />{t("factor_evaluation")}
            </label>
            <label className="flex min-h-10 cursor-pointer items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium has-[[data-checked]]:border-primary has-[[data-checked]]:bg-secondary max-[767px]:min-h-11">
              <RadioGroupItem value="strategy_backtest" />{t("strategy_backtest")}
            </label>
          </RadioGroup>
        </fieldset>

        <div className="grid min-w-0 gap-6 pb-8 @min-[960px]:grid-cols-[minmax(0,1fr)_320px] @min-[960px]:items-start">
          <section aria-label={t("authoring")} className="grid min-w-0 content-start gap-6">
            {alphaAuthoring}
            {visibleIssues.length > 0 ? (
              <ul aria-label={t("runIssues")} className="m-0 grid gap-2 rounded-lg border border-destructive p-4 text-sm text-destructive">
                {visibleIssues.map((issue, index) => <li key={`${issue.code}-${index}`}>{formatResearchIssue(issue, locale)}</li>)}
              </ul>
            ) : null}
            <FieldGroup className="rounded-lg border border-border bg-card p-4">
              <Field>
                <FieldLabel htmlFor="research-notes">{t("notes")}</FieldLabel>
                <Textarea id="research-notes" rows={3} aria-describedby="research-notes-limit"
                  aria-invalid={Array.from(draft.hypothesis).length > MAX_HYPOTHESIS_LENGTH}
                  placeholder={t("notesPlaceholder")} value={draft.hypothesis}
                  onChange={(event) => updateDraft((current) => ({ ...current, hypothesis: event.target.value }))} />
                <span id="research-notes-limit" className="text-right text-xs text-muted-foreground">
                  {t("characters", { used: Array.from(draft.hypothesis).length, maximum: MAX_HYPOTHESIS_LENGTH })}
                </span>
              </Field>
            </FieldGroup>
          </section>

          <aside aria-label={t("settings")} className="grid min-w-0 gap-5 rounded-lg border border-border bg-card p-4 @min-[960px]:sticky @min-[960px]:top-4">
            <h2 className="m-0 text-base font-semibold">{t("settings")}</h2>
            <ResearchDateFields
              compact
              startError={inputError("startDate")} endError={inputError("endDate")}
              coverageEnd={coverage?.end ?? null} coverageStart={coverage?.start ?? null}
              endDate={draft.endDate} startDate={draft.startDate}
              onChange={({ startDate, endDate }) => updateDraft((current) => ({ ...current, startDate, endDate }))}
            />
            <FieldGroup className="gap-4">
              <Field>
                <FieldLabel htmlFor="research-universe">{t("universe")}</FieldLabel>
                <Select value={draft.universe || null} onValueChange={(value) => updateDraft((current) => ({ ...current, universe: value ?? "" }))}>
                  <SelectTrigger id="research-universe" aria-invalid={Boolean(inputError("universe"))}
                    aria-describedby={inputError("universe") ? "universe-error" : undefined} className="w-full">
                    <SelectValue placeholder={t("notSelected")}>
                      {draft.universe ? t("top", { count: Number(draft.universe.slice(3)) }) : undefined}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent><SelectGroup>
                    {[300, 1000, 2000, 3000].map((count) => <SelectItem value={`top${count}`} key={count}>{t("top", { count })}</SelectItem>)}
                  </SelectGroup></SelectContent>
                </Select>
                {inputError("universe") && <small id="universe-error" className="text-destructive">{inputError("universe")}</small>}
              </Field>
              <Field>
                <FieldLabel htmlFor="research-neutralization">{t("neutralization")}</FieldLabel>
                <Select value={draft.neutralization || null}
                  onValueChange={(value) => updateDraft((current) => ({ ...current, neutralization: value ?? "" }))}>
                  <SelectTrigger id="research-neutralization" aria-invalid={Boolean(inputError("neutralization"))}
                    aria-describedby={inputError("neutralization") ? "neutralization-error" : undefined} className="w-full">
                    <SelectValue placeholder={t("notSelected")}>
                      {draft.neutralization === "none" || draft.neutralization === "industry" ? t(draft.neutralization) : undefined}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent><SelectGroup>
                    <SelectItem value="none">{t("none")}</SelectItem>
                    <SelectItem value="industry">{t("industry")}</SelectItem>
                  </SelectGroup></SelectContent>
                </Select>
                {inputError("neutralization") && <small id="neutralization-error" className="text-destructive">{inputError("neutralization")}</small>}
              </Field>
            </FieldGroup>
          </aside>
        </div>

        {storageError !== null ? <p className="text-sm text-destructive" role="alert">{t(`storage.${storageError}`)}</p> : null}
        {specFeedback?.key === specKey ? <div className="mb-4 rounded-lg border border-border bg-card p-4 text-sm" role="status">
          <p className="m-0">{t(`configuration.${specFeedback.status}`)}</p>
          {specFeedback.issues.length > 0 ? <ul aria-label={t("configurationIssues")}>
            {specFeedback.issues.map((issue, index) => <li key={`${issue.field}-${issue.code}-${index}`}>
              <strong>{researchIssueField(issue.field, locale)}</strong>: {formatResearchIssue(issue, locale)}
            </li>)}
          </ul> : null}
        </div> : null}
        {inputIssues.length > 0 ? <div className="mb-4 rounded-lg border border-destructive p-4 text-sm" role="alert">
          <p className="m-0 font-medium">{t("completeSettings")}</p>
          <ul className="mb-0">{inputIssues.map((issue) => <li key={issue.field}>
            <Button variant="link" size="sm" className="h-auto px-0 text-destructive max-[767px]:min-h-11" onClick={() => focusInput(issue.field)}>
              {t(`inputErrors.${issue.code}`)}
            </Button>
          </li>)}</ul>
        </div> : null}
        <footer className="sticky bottom-0 z-10 flex flex-wrap justify-end gap-3 border-t border-border bg-background/95 py-4 backdrop-blur-sm max-[767px]:static">
          <Button variant="outline" type="button" className="max-[767px]:min-h-11" disabled={submitting || (specFeedback?.key === specKey && specFeedback.checking)}
            onClick={() => void checkConfiguration()}>{t("check")}</Button>
          <Button type="button" className="max-[767px]:min-h-11" disabled={submitting} onClick={() => void runResearch()}>
            <Play aria-hidden="true" weight="fill" />{t(submitting ? "running" : "runEvaluation")}
          </Button>
        </footer>
      </PageContent>

      <Sheet open={fieldsOpen} onOpenChange={(open) => { if (open) setFieldsOpen(true); else closeFields(); }}>
        <SheetContent side="right" showCloseButton={false} className="w-full max-w-[520px] overflow-y-auto p-4"
          initialFocus={() => fieldsPanel.current?.querySelector<HTMLInputElement>('input[role="searchbox"]') ?? null}
          finalFocus={() => {
            if (restoreEditorFocus.current) {
              restoreEditorFocus.current = false;
              alphaEditor.current?.focus();
              return false;
            }
            return fieldsTrigger.current;
          }}>
          <SheetHeader className="flex flex-row items-center justify-between p-0 pb-4">
            <SheetTitle className="text-base">{t("fieldBrowser")}</SheetTitle>
            <Button variant="ghost" size="icon-sm" className="max-[767px]:size-11" aria-label={t("closeFields")} onClick={closeFields}><X aria-hidden="true" /></Button>
          </SheetHeader>
          <section id="research-fields-panel" ref={fieldsPanel} className="min-w-0">
            {fieldsOpen ? <ResearchFieldBrowser catalog={catalog} onInsert={(identifier) => {
              alphaEditor.current?.insertAtSelection(identifier);
              restoreEditorFocus.current = true;
              setFieldsOpen(false);
            }} /> : null}
          </section>
        </SheetContent>
      </Sheet>
    </section>
  );
  return (
    <section ref={workspace} aria-label={t("title")} className="page-section research-workspace">
      <header className="research-workspace-header">
        {folderNavigation}
        <label className="research-name-field" htmlFor="research-name">
          <span className="visually-hidden">{t("draftName")}</span>
          <input
            aria-label={t("name")}
            autoComplete="off"
            id="research-name"
            maxLength={200}
            onChange={(event) => updateDraft((current) => ({ ...current, name: event.target.value }))}
            placeholder={t("untitled")}
            type="text"
            value={draft.name}
          />
        </label>
        <button className="button research-new" disabled={submitting} onClick={startNewResearch} type="button">
          <Plus aria-hidden="true" size={17} weight="regular" />
          {t("newResearch")}
        </button>
      </header>

      <section className="research-setup" aria-label={t("setup")}>
            <fieldset className="research-kind-control">
              <legend className="visually-hidden">{t("kind")}</legend>
              <label className="research-kind-option">
                <input
                  checked={draft.researchKind === "factor_evaluation"}
                  name="research-kind"
                  onChange={() => updateDraft((current) => selectResearchKind(current, "factor_evaluation"))}
                  type="radio"
                  value="factor_evaluation"
                />
                <span>
                  <strong>{t("factor_evaluation")}</strong>

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
                  <strong>{t("strategy_backtest")}</strong>

                </span>
              </label>
            </fieldset>
        {draft.researchKind === "strategy_backtest" && <div className="research-parameter-field research-strategy-mode">
          <label htmlFor="strategy-mode">{t("strategyMode")}</label>
          <select id="strategy-mode" value={draft.strategyMode} onChange={event => {
            const mode = event.target.value;
            if (mode === "framework" || mode === "direct") updateDraft(current => selectStrategyMode(current, mode));
          }}>
            <option value="framework">{t("frameworkMode")}</option>
            <option value="direct">{t("directMode")}</option>
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
              <div className="research-parameter-heading"><label htmlFor="research-universe">{t("universe")}</label><ResearchParameterHelp helpId="universe" text={t("universeHelp")} /></div>
              <select id="research-universe" aria-invalid={Boolean(inputError("universe"))} aria-describedby={inputError("universe") ? "universe-error" : undefined} onChange={(event) => updateDraft((current) => ({ ...current, universe: event.target.value }))} value={draft.universe}>
                <option value="">{t("notSelected")}</option>
                <option value="top300">{t("top", { count: 300 })}</option>
                <option value="top1000">{t("top", { count: 1000 })}</option>
                <option value="top2000">{t("top", { count: 2000 })}</option>
                <option value="top3000">{t("top", { count: 3000 })}</option>
              </select>
              {inputError("universe") && <small id="universe-error" className="inline-status-error">{inputError("universe")}</small>}
            </div>

        </div>
      </section>

      <aside ref={fieldsPanel} id="research-fields-panel" className="research-fields-panel" aria-label={t("fieldBrowser")} hidden={!fieldsOpen}
        onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); closeFields(); } }}>
        <header><h2>{t("browseFields")}</h2><button className="button button-quiet" type="button" aria-label={t("closeFields")} onClick={closeFields}><X aria-hidden="true" size={18} /></button></header>
        {fieldsOpen && <ResearchFieldCatalog catalog={catalog} />}
      </aside>
      <section className="research-editor-panel" aria-label={t(direct ? "pythonAuthoring" : draft.researchKind === "strategy_backtest" ? "frameworkAuthoring" : "authoring")}>
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
        {storageError !== null ? <p className="inline-status inline-status-error" role="alert">{t(`storage.${storageError}`)}</p> : null}
        {visibleIssues.length > 0 ? (
          <ul aria-label={t("runIssues")} className="formula-diagnostics">
            {visibleIssues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}><code>{issue.code}</code> {formatResearchIssue(issue, locale)}</li>
            ))}
          </ul>
        ) : null}
        {draft.researchKind === "strategy_backtest" && <p className="research-spec-feedback">
          {t(direct ? "directSummary" : "frameworkSummary")}
        </p>}
        <div className="research-selection-settings">
          {builtinPortfolio && <>
                <ResearchNumberStepper
                  actionLabel={t("holdingsAction")}
                  id="research-holdings-count"
                  label={t("holdings")}
                  error={inputError("holdingsCount")}
                  maximum={100}
                  minimum={1}
                  onChange={(value) => updateDraft((current) => ({ ...current, holdingsCount: value }))}
                  value={draft.holdingsCount}
                />
                <ResearchNumberStepper
                  actionLabel={t("intervalAction")}
                  id="research-selection-sessions"
                  label={t("interval")}
                  error={inputError("selectionEverySessions")}
                  maximum={20}
                  minimum={1}
                  onChange={(value) => updateDraft((current) => ({ ...current, selectionEverySessions: value }))}
                  value={draft.selectionEverySessions}
                />
          </>}
          <button className="button" type="button"
            aria-expanded={settingsOpen} aria-controls="research-parameters" onClick={() => setSettingsOpen((open) => !open)}>
            <SlidersHorizontal aria-hidden="true" size={18} /> {t("settings")}
          </button>
        </div>
      <section className="research-run-settings research-inline-settings" id="research-parameters" aria-label={t("settings")} hidden={!settingsOpen}>
          <div className="run-configuration-grid">
            {draft.researchKind === "strategy_backtest" && <>
                <div className="research-parameter-field">
                  <div className="research-parameter-heading"><label htmlFor="initial-cash">{t("initialCash")}</label><ResearchParameterHelp helpId="cash" text={t("cashHelp")} /></div>
                  <input id="initial-cash"
                    aria-describedby={(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny) ? "initial-cash-help" : undefined}
                    aria-invalid={(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny)}
                    inputMode="decimal"
                    onChange={(event) => updateDraft((current) => ({ ...current, initialCashCny: event.target.value }))}
                    placeholder="100000.00"
                    type="text"
                    value={draft.initialCashCny}
                  />

                  {(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny) && <small id="initial-cash-help" className="inline-status-error">{t("cashInvalid")}</small>}
                </div>
            </>}
            {builtinAlpha && <div className="research-parameter-field">
              <div className="research-parameter-heading"><label htmlFor="research-neutralization">{t("neutralization")}</label></div>
              <select id="research-neutralization" aria-invalid={Boolean(inputError("neutralization"))} aria-describedby={inputError("neutralization") ? "neutralization-error" : undefined} onChange={(event) => updateDraft((current) => ({ ...current, neutralization: event.target.value }))} value={draft.neutralization}>
                <option value="">{t("notSelected")}</option>
                <option value="none">{t("none")}</option>
                <option value="industry">{t("industry")}</option>
              </select>
              {inputError("neutralization") && <small id="neutralization-error" className="inline-status-error">{inputError("neutralization")}</small>}
            </div>}

            {builtinPortfolio ? (
              <>
                <div className="research-parameter-field research-weighting-field">
                  <div className="research-parameter-heading"><label htmlFor="portfolio-weighting">{t("weighting")}</label>
                    <ResearchParameterHelp helpId="weighting" text={<span className="research-help-content">
                      <span>{t("weightingHelp")}</span>
                      <span>{t(`weightingDescriptions.${draft.weighting}`)}</span>
                      <span><strong>{t("example")}</strong>{t(`weightingExamples.${draft.weighting}`)}</span>
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
                    <option value="equal_weight">{t("weightings.equal_weight")}</option>
                    <option value="rank_weight">{t("weightings.rank_weight")}</option>
                    <option value="inverse_volatility">{t("weightings.inverse_volatility")}</option>
                  </select>

                </div>
                {draft.weighting === "inverse_volatility" && (
                  <div className="research-parameter-field research-weighting-field">
                  <div className="research-parameter-heading"><label htmlFor="volatility-window">{t("volatilityWindow")}</label><ResearchParameterHelp helpId="volatility" text={t("volatilityHelp")} /></div>
                    <input id="volatility-window" type="number" min={1} max={252} step={1}
                      aria-invalid={!isValidVolatilityWindow(draft.volatilityWindow)}
                      aria-describedby={!isValidVolatilityWindow(draft.volatilityWindow) ? "volatility-window-help" : undefined}
                      value={draft.volatilityWindow}
                      onChange={(event) => updateDraft((current) => ({ ...current, volatilityWindow: event.target.value }))}
                    />

                  {!isValidVolatilityWindow(draft.volatilityWindow) && <small id="volatility-window-help" className="inline-status-error">{t("windowInvalid")}</small>}
                </div>
                )}
                <ResearchPositionSizing ref={exposureEditor} catalog={catalog} expression={draft.exposureExpression} error={inputError("exposureExpression")}
                  diagnostics={exposureDiagnosticState.kind === "complete" ? exposureDiagnosticState.result.diagnostics : []}
                  onChange={(exposureExpression) => updateDraft((current) => ({ ...current, exposureExpression }))} />
                {exposureDiagnosticState.kind === "complete" && !exposureDiagnosticState.result.valid ? (
                  <ul aria-label={t("exposureDiagnostics")} className="formula-diagnostics research-spec-feedback">
                    {exposureDiagnosticState.result.diagnostics.map((issue) => (
                      <li key={`${issue.code}-${issue.range.start.offset}`}>{formatFormulaDiagnostic(issue, locale)}</li>
                    ))}
                  </ul>
                ) : null}
                {exposureDiagnosticState.kind === "unavailable" ? <p className="research-spec-feedback">{t("exposureUnavailable")}</p> : null}
              </>
            ) : null}
          </div>
          {draft.researchKind === "strategy_backtest" && <SimulationCostSettings costs={draft.costs}
            onChange={costs => updateDraft(current => ({ ...current, costs }))}
            error={costError} />}
      </section>

        <details className="research-notes">
          <summary>{t("notes")}</summary>
          <label htmlFor="research-notes">{t("notes")}</label>
          <textarea
            aria-describedby="research-notes-limit"
            aria-invalid={Array.from(draft.hypothesis).length > MAX_HYPOTHESIS_LENGTH}
            id="research-notes"
            onChange={(event) => updateDraft((current) => ({ ...current, hypothesis: event.target.value }))}
            placeholder={t("notesPlaceholder")}
            rows={2}
            value={draft.hypothesis}
          />
          <p id="research-notes-limit">
            {t("characters", { used: Array.from(draft.hypothesis).length, maximum: MAX_HYPOTHESIS_LENGTH })}
          </p>
        </details>
      </section>

            {specFeedback?.key === specKey ? (
              <div className="research-spec-feedback" role="status">
                <p>{t(`configuration.${specFeedback.status}`)}</p>
                {specFeedback.issues.length > 0 ? <ul aria-label={t("configurationIssues")}>
                  {specFeedback.issues.map((issue, index) => <li key={`${issue.field}-${issue.code}-${index}`}><strong>{researchIssueField(issue.field, locale)}</strong>: {formatResearchIssue(issue, locale)}</li>)}
                </ul> : null}
              </div>
            ) : null}
            {inputIssues.length > 0 && <div className="research-input-issues" role="alert">
              <p>{t("completeSettings")}</p>
              <ul>{inputIssues.map((issue) => <li key={issue.field}><button type="button" onClick={() => focusInput(issue.field)}>{t(`inputErrors.${issue.code}`)}</button></li>)}</ul>
            </div>}
            <footer className="research-action-bar">
              <button
                className="button" type="button"
                disabled={submitting || (specFeedback?.key === specKey && specFeedback.checking)}
                onClick={() => void checkConfiguration()}
              >{t("check")}</button>
              <button
                className="button button-primary"
                disabled={submitting}
                onClick={() => void runResearch()}
                type="button"
              >
                <Play aria-hidden="true" size={17} weight="fill" />
                {t(submitting ? "running" : draft.researchKind === "strategy_backtest" ? "runBacktest" : "runEvaluation")}
              </button>
            </footer>
    </section>
  );
}

function issueAsFormulaDiagnostic(issue: ResearchRunAdmissionIssue): EditorDiagnostic[] {
  if (issue.field !== "formula" || issue.range === null) return [];
  return [{ ...issue, range: issue.range }];
}

export function ResearchDateFields({
  compact = false,
  coverageStart,
  coverageEnd,
  startDate,
  endDate,
  onChange,
  startError,
  endError,
}: {
  compact?: boolean;
  startError?: string;
  endError?: string;
  coverageStart: string | null;
  coverageEnd: string | null;
  startDate: string;
  endDate: string;
  onChange: (range: { startDate: string; endDate: string }) => void;
}) {
  const { t } = useTranslation("research");
  const presets = buildResearchDatePresets(coverageStart, coverageEnd);
  return (
    <div aria-label={t("dates")} className="grid min-w-0 gap-4" role="group">
      <div className={compact ? "grid gap-4" : "grid grid-cols-1 gap-4 sm:grid-cols-2"}>
        <ResearchDateInput id="research-start-date" label={t("startDateInput")}
          openLabel={t("openStartCalendar")} value={startDate} minimum={coverageStart}
          maximum={isResearchIsoDate(endDate) ? endDate : coverageEnd}
          error={startError} errorId="start-date-error"
          onChange={startDate => onChange({ startDate, endDate })} />
        <ResearchDateInput id="research-end-date" label={t("endDateInput")}
          openLabel={t("openEndCalendar")} value={endDate}
          minimum={isResearchIsoDate(startDate) ? startDate : coverageStart}
          maximum={coverageEnd} error={endError} errorId="end-date-error"
          onChange={endDate => onChange({ startDate, endDate })} />
      </div>
      <div aria-label={t("quickDates")} className="flex flex-wrap gap-2" role="group">
        {presets.map((preset) => {
          const active = preset.startDate !== null &&
            preset.startDate === startDate &&
            preset.endDate === endDate;
          return (
            <Button
              variant={active ? "secondary" : "outline"}
              size="sm"
              className="max-[767px]:min-h-11"
              aria-label={t(`presetLabels.${preset.id}`)}
              aria-pressed={active}
              disabled={preset.startDate === null || preset.endDate === null}
              key={preset.id}
              onClick={() => {
                if (preset.startDate === null || preset.endDate === null) return;
                onChange({ startDate: preset.startDate, endDate: preset.endDate });
              }}
              type="button"
            >
              {t(`presets.${preset.id}`)}
            </Button>
          );
        })}
      </div>
    </div>
  );
}

function ResearchParameterHelp({ helpId, text }: { helpId: "cash" | "weighting" | "volatility" | "exposure" | "universe"; text: ReactNode }) {
  const { t } = useTranslation("research");
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
    <button ref={button} type="button" aria-label={t(`helpLabels.${helpId}`)} aria-describedby={open ? id : undefined}
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
  const { t } = useTranslation("research");
  const [selection, setSelection] = useState({ anchor: 0, head: 0 });
  return <div className="research-exposure-expression">
    <div className="research-parameter-heading"><h3>{t("positionSizing")}</h3>
      <ResearchParameterHelp helpId="exposure" text={<span className="research-help-content">
        <span>{t("positionSizingHelp")}</span>
        <span><strong>{t("fixedExposure")}</strong><Trans t={t} i18nKey="fixedExposureExample" components={{ code: <code /> }} /></span>
        <span><strong>{t("marketExposure")}</strong>
          <code className="research-help-formula">{"if_else(\n  universe_advancing_fraction() > 0.5,\n  1, 0.3\n)"}</code>
          {t("marketExposureExample")}
        </span>
        <span>{t("exposureRules")}</span>
      </span>} />
    </div>
    <AlphaFormulaEditor ref={ref} catalog={catalog} context="exposure" diagnostics={diagnostics} formula={expression} selection={selection}
      onChange={(value, nextSelection) => { setSelection(nextSelection); onChange(value); }} />
    {error && <small id="position-sizing-error" className="inline-status-error">{error}</small>}
  </div>;
}
