import "./research-perplexity.css";
import { drawdownFields, type DrawdownField } from "./portfolioDrawdown";
import type { TakeProfitField } from "./takeProfit";
import {
  CaretDown,
  FolderSimple,
  Minus,
  Play,
  Plus,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "cn";
import type { AlphaCatalog } from "../alphaCatalog";
import { coreFetch } from "../auth/coreFetch";
import type { BrowserLocation } from "../auth/routing";
import { i18n, interfaceLocale, useTranslation } from "../i18n";
import { ResearchFieldCatalog, type DataOverview } from "../data/DataPage";
import { AlphaFormulaEditor, type AlphaFormulaEditorHandle, type EditorDiagnostic } from "./AlphaFormulaEditor";
import { folderDisplayName, folderMutationError, type FolderError } from "./folders";
import { formatResearchIssue, researchIssueField, type ResearchRunAdmissionIssue } from "./admission";
import { PythonStrategyAuthoring } from "./PythonStrategyAuthoring";
import { StrategyScoringRule } from "./StrategyScoringRule";
import { StrategyRuleSummary } from "./StrategyRuleSummary";
import { RuleDisclosure } from "./RuleDisclosure";
import { ResearchPositionSizing } from "./ResearchPositionSizing";
import { FrameworkAuthoring } from "./FrameworkAuthoring";
import { SimulationCostSettings } from "./SimulationCostSettings";
import type { CostField } from "./simulationCosts";
import { frameworkStages, type FrameworkStage } from "./frameworkModules";
import { programInputFields, type ProgramInputField } from "./pythonStrategy";
import { buildResearchDatePresets } from "./dateRange";
import { isIsoCalendarDate } from "../components/layout/calendarDate";
import { CalendarDateField } from "../components/layout/CalendarDateField";
import { ResearchFieldBrowser } from "./ResearchFieldBrowser";
import { useResearchDraftController } from "./useResearchDraftController";
import { Alert, AlertTitle, AlertDescription } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "../components/ui/input-group";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { RadioGroup, RadioGroupItem } from "../components/ui/radio-group";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";
import { PageContent, PageHeader } from "../components/layout/Page";
import { ResearchParameterHelp } from "./ResearchParameterHelp";
import { ResearchInfotip } from "./ResearchInfotip";
import { readScoringRule } from "./strategyRules";
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
      <Button variant="outline" onClick={() => void load()}>{t("retry")}</Button>
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

  return <Field data-invalid={Boolean(error)}>
    <FieldLabel htmlFor={id}>{label}</FieldLabel>
    <InputGroup className="h-11">
      <InputGroupAddon className="py-0">
        <InputGroupButton variant="ghost" size="icon-sm" className="size-11" aria-controls={id} aria-label={t("decrease", { label: actionLabel })}
          disabled={!canDecrease} onClick={() => onChange(nextBoundedInteger(value, minimum, maximum, -1))}>
          <Minus aria-hidden="true" />
        </InputGroupButton>
      </InputGroupAddon>
      <InputGroupInput id={id} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined}
        inputMode="numeric" type="number" min={minimum} max={maximum} required step={1} value={value}
        onChange={event => onChange(event.target.value)} />
      <InputGroupAddon align="inline-end" className="py-0">
        <InputGroupButton variant="ghost" size="icon-sm" className="size-11" aria-controls={id} aria-label={t("increase", { label: actionLabel })}
          disabled={!canIncrease} onClick={() => onChange(nextBoundedInteger(value, minimum, maximum, 1))}>
          <Plus aria-hidden="true" />
        </InputGroupButton>
      </InputGroupAddon>
    </InputGroup>
    <FieldError id={`${id}-error`}>{error}</FieldError>
  </Field>;
}

export function ResearchDraftWorkspace({
  researcherId,
  folder,
  catalog,
  data,
  folderNavigation,
  storage = window.localStorage,
  confirmDiscard,
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
  const [costsOpen, setCostsOpen] = useState(false);
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);
  const [editorGeneration, setEditorGeneration] = useState(0);
  const [activeStage, setActiveStage] = useState<FrameworkStage>("portfolio_construction");
  const workspace = useRef<HTMLElement>(null);
  const alphaEditor = useRef<AlphaFormulaEditorHandle>(null);
  const exposureEditor = useRef<AlphaFormulaEditorHandle>(null);
  const [pendingInput, setPendingInput] = useState<ResearchInputField | null>(null);
  function focusInput(field: ResearchInputField) {
    if (field.startsWith("costs.")) setCostsOpen(true);
    if (field.startsWith("modules.")) {
      const stage = field.split(".")[1];
      if (frameworkStages.includes(stage as FrameworkStage)) setActiveStage(stage as FrameworkStage);
    } else if (field === "universe") setActiveStage("universe_selection");
    else if (field === "formula" || field === "neutralization") setActiveStage("alpha");
    else if (field === "holdingsCount" || field === "selectionEverySessions" || field === "volatilityWindow" || field === "exposureExpression" || field === "minimumHoldingSessions") setActiveStage("portfolio_construction");
    else if (drawdownFields.includes(field as DrawdownField) || field.startsWith("takeProfitTiers.") || field === "stopLossThreshold" || field === "maximumHoldingSessions") setActiveStage("risk_management");
    setPendingInput(field);
  }
  const {
    draft, hasStoredDraft, storageError, diagnosticState, exposureDiagnosticState,
    admissionFeedback, specFeedback, specKey, submitting, validationAttempted, inputIssues, inputError,
    updateDraft, startNewResearch, checkConfiguration, runResearch,
  } = useResearchDraftController({
    researcherId, folderId: folder.id, storage, startNewOnOpen,
    confirmDiscard: message => {
      if (confirmDiscard) return confirmDiscard(message);
      setDiscardDialogOpen(true);
      return false;
    },
    onInvalidInput: focusInput, onNew: () => { setCostsOpen(false); setEditorGeneration(value => value + 1); },
  });
  const direct = draft.researchKind === "strategy_backtest" && draft.strategyMode === "direct";
  const factor = draft.researchKind === "factor_evaluation";
  const builtinAlpha = usesBuiltinAlpha(draft);
  const scoringRule = readScoringRule(draft.formula);
  useEffect(() => {
    if (pendingInput === null) return;
    if (pendingInput === "formula") {
      const input = workspace.current?.querySelector<HTMLElement>("#scoring-window");
      if (input && input.getClientRects().length) input.focus();
      else if (!factor && !workspace.current?.querySelector("#scoring-custom-formula")?.getClientRects().length) workspace.current?.querySelector<HTMLElement>("#scoring-rule")?.focus();
      else alphaEditor.current?.focus();
    } else if (pendingInput === "exposureExpression") {
      const input = workspace.current?.querySelector<HTMLElement>("#stock-exposure-percent");
      if (input && input.getClientRects().length) input.focus();
      else exposureEditor.current?.focus();
    }
    else {
      const input = workspace.current?.querySelector<HTMLElement>(inputSelector(pendingInput));
      input?.focus();
    }
    setPendingInput(null);
  }, [pendingInput, costsOpen, activeStage]);
  const [fieldsOpen, setFieldsOpen] = useState(false);
  const [fieldBrowserMode, setFieldBrowserMode] = useState<"formula" | "catalog">("formula");
  const fieldsTrigger = useRef<HTMLButtonElement>(null);
  const fieldsPanel = useRef<HTMLElement>(null);
  const restoreEditorFocus = useRef(false);
  function closeFields() {
    setFieldsOpen(false);
  }
  function fieldsButton(mode: "formula" | "catalog" = "formula") {
    return <Button variant="outline" size="sm" className="max-[767px]:min-h-11" type="button" aria-expanded={fieldsOpen}
      aria-controls="research-fields-panel" onClick={event => {
        fieldsTrigger.current = event.currentTarget;
        setFieldBrowserMode(mode);
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
        <div className="research-editor-panel overflow-hidden rounded-lg border border-border bg-card focus-within:ring-2 focus-within:ring-ring/30">
          <header className="flex min-h-12 items-center justify-between gap-3 border-b border-border px-4">
            <h2 id="alpha-formula-title" className="m-0 text-base font-semibold">{t("formula")}</h2>
            {fieldsButton()}
          </header>
          {inputError("formula") && <p className="px-4 text-sm text-destructive">{inputError("formula")}</p>}
          <AlphaFormulaEditor
            ref={alphaEditor}
            catalog={catalog}
            diagnostics={serverDiagnostics}
            formula={draft.formula}
            error={inputError("formula")}
            className={cn(factor ? "h-[180px]" : "h-[280px]", "min-w-0 overflow-hidden bg-card")}
            onChange={(formula, editor) => updateDraft((current) => ({ ...current, formula, editor }))}
            selection={draft.editor}
          />
          <footer className="flex flex-wrap justify-between gap-2 border-t border-border px-4 py-2 text-xs text-muted-foreground">
            <span>{t("autocomplete")}</span>
          </footer>
        </div>
        {diagnosticState.kind === "complete" && diagnosticState.result.diagnostics.length > 0 ? (
          <ul aria-label={t("formulaDiagnostics")} className="m-0 grid gap-2 text-sm text-destructive">
            {diagnosticState.result.diagnostics.map((diagnostic) => (
              <li key={`${diagnostic.code}-${diagnostic.range.start.offset}`}>
                <code>{diagnostic.code}</code> {formatFormulaDiagnostic(diagnostic, locale)}
              </li>
            ))}
          </ul>
        ) : null}
        {diagnosticState.kind === "unavailable" ? (
          <p className="text-sm text-destructive" role="status">{t("diagnosticsUnavailable")}</p>
        ) : null}
  </>;
  function programErrorLine(stage?: FrameworkStage): number | null {
    const field = `${stage ? `modules.${stage}.` : ""}program.source`;
    const issue = [...visibleIssues, ...(specFeedback?.key === specKey ? specFeedback.issues : [])]
      .find(issue => issue.field === field && issue.details?.kind === "strategy_program");
    return issue?.details?.kind === "strategy_program" ? issue.details.line : null;
  }
  const portfolioSettings = <FieldGroup className="gap-6">
    <FieldGroup className="grid gap-4 @min-[560px]:grid-cols-2">
      <ResearchNumberStepper actionLabel={t("holdingsAction")} id="research-holdings-count" label={t("holdings")}
        error={inputError("holdingsCount")} maximum={100} minimum={1} value={draft.holdingsCount}
        onChange={holdingsCount => updateDraft(current => ({ ...current, holdingsCount }))} />
      <ResearchNumberStepper actionLabel={t("intervalAction")} id="research-selection-sessions" label={t("interval")}
        error={inputError("selectionEverySessions")} maximum={20} minimum={1} value={draft.selectionEverySessions}
        onChange={selectionEverySessions => updateDraft(current => ({ ...current, selectionEverySessions }))} />
    </FieldGroup>
    <Field>
      <div className="flex items-center gap-2"><FieldLabel htmlFor="portfolio-weighting">{t("weighting")}</FieldLabel>
        <ResearchParameterHelp helpId="weighting" text={<span className="grid gap-3">
          <span>{t("weightingHelp")}</span><span>{t(`weightingDescriptions.${draft.weighting}`)}</span>
          <span><strong>{t("example")}</strong>{t(`weightingExamples.${draft.weighting}`)}</span>
        </span>} />
      </div>
      <Select value={draft.weighting} onValueChange={weighting => {
        if (weighting === "equal_weight" || weighting === "rank_weight" || weighting === "inverse_volatility") {
          updateDraft(current => ({ ...current, weighting }));
        }
      }}>
        <SelectTrigger id="portfolio-weighting" className="w-full"><SelectValue>{t(`weightings.${draft.weighting}`)}</SelectValue></SelectTrigger>
        <SelectContent><SelectGroup>
          {(["equal_weight", "rank_weight", "inverse_volatility"] as const).map(value => <SelectItem key={value} value={value}>{t(`weightings.${value}`)}</SelectItem>)}
        </SelectGroup></SelectContent>
      </Select>
    </Field>
    {draft.weighting === "inverse_volatility" && <Field data-invalid={!isValidVolatilityWindow(draft.volatilityWindow)}>
      <div className="flex items-center gap-2"><FieldLabel htmlFor="volatility-window">{t("volatilityWindow")}</FieldLabel><ResearchParameterHelp helpId="volatility" text={t("volatilityHelp")} /></div>
      <Input id="volatility-window" type="number" min={1} max={252} step={1} value={draft.volatilityWindow}
        aria-invalid={!isValidVolatilityWindow(draft.volatilityWindow)} aria-describedby="volatility-window-error"
        onChange={event => updateDraft(current => ({ ...current, volatilityWindow: event.target.value }))} />
      <FieldError id="volatility-window-error">{!isValidVolatilityWindow(draft.volatilityWindow) ? t("windowInvalid") : undefined}</FieldError>
    </Field>}
    <ResearchPositionSizing ref={exposureEditor} catalog={catalog} expression={draft.exposureExpression} error={inputError("exposureExpression")}
      diagnostics={exposureDiagnosticState.kind === "complete" ? exposureDiagnosticState.result.diagnostics : []}
      onChange={exposureExpression => updateDraft(current => ({ ...current, exposureExpression }))} />
    {exposureDiagnosticState.kind === "complete" && !exposureDiagnosticState.result.valid ? (
      <ul aria-label={t("exposureDiagnostics")} className="m-0 grid gap-2 text-sm text-destructive">
        {exposureDiagnosticState.result.diagnostics.map(issue => <li key={`${issue.code}-${issue.range.start.offset}`}>{formatFormulaDiagnostic(issue, locale)}</li>)}
      </ul>
    ) : null}
    {exposureDiagnosticState.kind === "unavailable" ? <p className="m-0 text-sm text-muted-foreground">{t("exposureUnavailable")}</p> : null}
  </FieldGroup>;
  const universeSettings = <FieldGroup className="gap-2">
              <Field>
                <div className="flex items-center gap-1"><FieldLabel htmlFor="research-universe">{t("universe")}</FieldLabel><ResearchParameterHelp helpId="universe" text={t("universeHelp")} /></div>
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
  </FieldGroup>;
  const neutralizationSettings = <Field hidden={!builtinAlpha} className={cn(!builtinAlpha && "hidden")}>
                <div className="flex items-center gap-1"><FieldLabel htmlFor="research-neutralization">{t("neutralization")}</FieldLabel><ResearchInfotip label={i18n.t("strategy:workbench.advancedSelection")}>{i18n.t("strategy:workbench.advancedSelectionHelp")}</ResearchInfotip></div>
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
              </Field>;
  const authoring = <div key={editorGeneration} className="min-w-0">
    <div hidden={direct} className={cn("min-w-0", direct && "hidden")}>
      <FrameworkAuthoring factor={factor} drawdown={draft}
        activeStage={activeStage} onStageChange={setActiveStage}
        stageSummaries={{
          universe_selection: draft.universe ? t("top", { count: Number(draft.universe.slice(3)) }) : t("notSelected"),
          alpha: draft.frameworkModules.alpha.kind === "python" ? i18n.t("strategy:workbench.python") : scoringRule
            ? i18n.t(`strategy:workbench.scoring.${scoringRule.kind}`) : draft.formula.trim() ? i18n.t("strategy:workbench.summaryCustomFormula") : t("notSelected"),
          portfolio_construction: draft.frameworkModules.portfolio_construction.kind === "python" ? i18n.t("strategy:workbench.python") : i18n.t("strategy:workbench.stagePortfolioSummary", { holdings: draft.holdingsCount || "—", weighting: i18n.t(`strategy:workbench.weighting.${draft.weighting}`) }),
          risk_management: draft.frameworkModules.risk_management.kind === "python" ? i18n.t("strategy:workbench.python") : draft.stopLossThreshold || draft.maximumHoldingSessions || draft.takeProfitTiers.length || draft.drawdownThreshold ? i18n.t("strategy:workbench.stageRiskConfigured") : i18n.t("strategy:workbench.stageRiskEmpty"),
        }}
        updateDrawdown={changes => updateDraft(current => ({ ...current, ...changes }))}
        takeProfitTiers={draft.takeProfitTiers} updateTakeProfitTiers={takeProfitTiers => updateDraft(current => ({ ...current, takeProfitTiers }))}
        stopLossThreshold={draft.stopLossThreshold} updateStopLoss={stopLossThreshold => updateDraft(current => ({ ...current, stopLossThreshold }))}
        maximumHoldingSessions={draft.maximumHoldingSessions} updateMaximumHoldingSessions={maximumHoldingSessions => updateDraft(current => ({ ...current, maximumHoldingSessions }))}
        minimumHoldingSessions={draft.minimumHoldingSessions} updateMinimumHoldingSessions={minimumHoldingSessions => updateDraft(current => ({ ...current, minimumHoldingSessions }))}
        modules={draft.frameworkModules} error={programError} errorLine={programErrorLine}
        fieldsButton={() => fieldsButton("catalog")}
        universeSettings={!factor && !direct ? universeSettings : null}
        neutralizationSettings={!factor && !direct ? <RuleDisclosure title={i18n.t("strategy:workbench.advancedSelection")}
          configured={draft.neutralization === "industry"}
          invalid={Boolean(inputError("neutralization"))}>{neutralizationSettings}</RuleDisclosure> : null}
        alphaEditor={<StrategyScoringRule enabled={!factor} formula={draft.formula} catalog={catalog}
          error={inputError("formula")} onChange={formula => updateDraft(current => ({ ...current, formula, editor: { anchor: 0, head: 0 } }))}>
          {alphaAuthoring}</StrategyScoringRule>} portfolioSettings={portfolioSettings}
        selectModule={(stage, kind) => updateDraft(current => selectFrameworkModule(current, stage, kind))}
        updateProgram={(stage, changes) => updateDraft(current => ({ ...current, frameworkModules: {
          ...current.frameworkModules, [stage]: { ...current.frameworkModules[stage], program: { ...current.frameworkModules[stage].program, ...changes } },
        } }))} />
    </div>
    <div hidden={!direct} className={cn("min-w-0", !direct && "hidden")}>
      <PythonStrategyAuthoring inputs={draft} error={programError} errorLine={programErrorLine()}
        onChange={changes => updateDraft(current => ({ ...current, ...changes }))} fieldsButton={fieldsButton("catalog")} />
    </div>
  </div>;
  return (
    <section ref={workspace} aria-label={t("title")} className="research-reading-workspace @container min-w-0">
      <PageContent width="wide" className="research-page-content">
        <PageHeader className="research-page-header"
          title={draft.name.trim() || t("untitled")}
          actions={<>{folderNavigation}<Button variant="outline" disabled={submitting} onClick={() => startNewResearch()}>
            <Plus aria-hidden="true" />{t("newResearch")}</Button>
            <Button variant="outline" type="button" disabled={submitting || (specFeedback?.key === specKey && specFeedback.checking)}
              onClick={() => void checkConfiguration()}>{t("check")}</Button>
            <Button type="button" disabled={submitting} onClick={() => void runResearch()}>
              <Play aria-hidden="true" weight="fill" />{t(submitting ? "running" : factor ? "runEvaluation" : "runBacktest")}
            </Button></>}
        />
        <div className="research-authoring-options">
          <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
            <fieldset className="research-mode-switch m-0 min-w-0 border-0 p-0">
              <legend className="mb-2 p-0 text-sm font-medium leading-[22px]">{t("kind")}</legend>
              <ResearchInfotip label={t(factor ? "factor_evaluation" : "strategy_backtest")}>{i18n.t(factor ? "strategy:workbench.factorIntro" : "strategy:workbench.intro")}</ResearchInfotip>
              <RadioGroup className="flex flex-wrap gap-2" value={draft.researchKind}
                onValueChange={(value) => {
                  if (value === "factor_evaluation" || value === "strategy_backtest") {
                    updateDraft((current) => selectResearchKind(current, value));
                  }
                }}>
                <label className="research-mode-option flex min-h-10 cursor-pointer items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium has-[[data-checked]]:border-primary has-[[data-checked]]:bg-secondary max-[767px]:min-h-11">
                  <RadioGroupItem value="factor_evaluation" />{t("factor_evaluation")}
                </label>
                <label className="research-mode-option flex min-h-10 cursor-pointer items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium has-[[data-checked]]:border-primary has-[[data-checked]]:bg-secondary max-[767px]:min-h-11">
                  <RadioGroupItem value="strategy_backtest" />{t("strategy_backtest")}
                </label>
              </RadioGroup>
            </fieldset>

            {!factor && <fieldset className="m-0 min-w-0 border-0 p-0">
              <legend id="strategy-mode-label" className="mb-2 p-0 text-sm font-medium leading-[22px]">{t("strategyMode")}</legend>
              <ResearchInfotip label={t(direct ? "directMode" : "frameworkMode")}>{i18n.t(direct ? "strategy:workbench.directHelp" : "strategy:workbench.ruleModeHelp")}</ResearchInfotip>
              <RadioGroup aria-labelledby="strategy-mode-label" className="flex flex-wrap gap-2" value={draft.strategyMode} onValueChange={mode => {
                if (mode === "framework" || mode === "direct") updateDraft(current => selectStrategyMode(current, mode));
              }}>
                <label className="research-mode-option flex min-h-10 cursor-pointer items-center gap-2 rounded-md border border-border px-3 text-sm font-medium">
                  <RadioGroupItem value="framework" />{t("frameworkMode")}
                </label>
                <label className="research-mode-option flex min-h-10 cursor-pointer items-center gap-2 rounded-md border border-border px-3 text-sm font-medium">
                  <RadioGroupItem value="direct" />{t("directMode")}
                </label>
              </RadioGroup>
            </fieldset>}
          </div>
        </div>

        <div className={cn("grid min-w-0 gap-5 pb-6", factor ? "@min-[840px]:grid-cols-[minmax(0,1fr)_300px] @min-[840px]:items-start" : "@min-[960px]:grid-cols-[minmax(0,1fr)_320px] @min-[960px]:items-start")}>
          <section aria-label={t(direct ? "pythonAuthoring" : factor ? "authoring" : "frameworkAuthoring")} className="grid min-w-0 content-start gap-5">
            {authoring}
            {visibleIssues.length > 0 ? (
              <ul aria-label={t("runIssues")} className="m-0 grid gap-2 rounded-lg border border-destructive p-4 text-sm text-destructive">
                {visibleIssues.map((issue, index) => <li key={`${issue.code}-${index}`}>{formatResearchIssue(issue, locale)}</li>)}
              </ul>
            ) : null}

            <RuleDisclosure title={i18n.t("strategy:workbench.notes")} configured={draft.hypothesis !== ""} invalid={Boolean(inputError("hypothesis"))}><FieldGroup>
              <Field>
                <FieldLabel htmlFor="research-notes">{t("notes")}</FieldLabel>
                <Textarea id="research-notes" rows={2} className="min-h-16" aria-describedby="research-notes-limit"
                  aria-invalid={Array.from(draft.hypothesis).length > MAX_HYPOTHESIS_LENGTH}
                  placeholder={t("notesPlaceholder")} value={draft.hypothesis}
                  onChange={(event) => updateDraft((current) => ({ ...current, hypothesis: event.target.value }))} />
                <span id="research-notes-limit" className="text-right text-xs text-muted-foreground">
                  {t("characters", { used: Array.from(draft.hypothesis).length, maximum: MAX_HYPOTHESIS_LENGTH })}
                </span>
              </Field>
            </FieldGroup></RuleDisclosure>
            {!factor && <StrategyRuleSummary inputs={draft} />}
          </section>

          <aside aria-label={t("settings")} className="grid min-w-0 gap-6">
            <section className="research-settings-panel grid min-w-0 gap-5 rounded-lg border border-border bg-card p-4">
            <h2 className="m-0 text-base font-semibold">{factor ? t("settings") : i18n.t("strategy:workbench.conditionsTitle")}</h2>
            <Field>
              <FieldLabel htmlFor="research-name">{t("name")}</FieldLabel>
              <Input id="research-name" aria-label={t("name")} autoComplete="off" maxLength={200} placeholder={t("untitled")} value={draft.name}
                onChange={event => updateDraft(current => ({ ...current, name: event.target.value }))} />
            </Field>
            <ResearchDateFields
              compact
              startError={inputError("startDate")} endError={inputError("endDate")}
              coverageEnd={coverage?.end ?? null} coverageStart={coverage?.start ?? null}
              endDate={draft.endDate} startDate={draft.startDate}
              onChange={({ startDate, endDate }) => updateDraft((current) => ({ ...current, startDate, endDate }))}
            />
            <FieldGroup className="gap-4">
              {(factor || direct) && universeSettings}
              {factor && neutralizationSettings}
              {!factor && <Field data-invalid={(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny)}>
                <div className="flex items-center gap-2"><FieldLabel htmlFor="initial-cash">{t("initialCash")}</FieldLabel><ResearchParameterHelp helpId="cash" text={t("cashHelp")} /></div>
                <Input id="initial-cash" inputMode="decimal" placeholder="100000.00" value={draft.initialCashCny}
                  aria-invalid={(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny)}
                  aria-describedby="initial-cash-error" onChange={event => updateDraft(current => ({ ...current, initialCashCny: event.target.value }))} />
                <FieldError id="initial-cash-error">{(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny) ? t("cashInvalid") : undefined}</FieldError>
              </Field>}
            </FieldGroup>
            {!factor && <Collapsible open={costsOpen} onOpenChange={setCostsOpen}>
              <CollapsibleTrigger render={<Button variant="outline" className="w-full justify-between" />}>
                {i18n.t("strategy:cost.title")}<CaretDown aria-hidden="true" />
              </CollapsibleTrigger>
              <CollapsibleContent keepMounted className="pt-4">
                <SimulationCostSettings costs={draft.costs} onChange={costs => updateDraft(current => ({ ...current, costs }))} error={costError} />
              </CollapsibleContent>
            </Collapsible>}
            {!factor && <div className="flex items-center gap-1 border-t border-border pt-3 text-sm text-muted-foreground">
              <span>{i18n.t("strategy:workbench.executionShort")}</span>
              <ResearchInfotip label={i18n.t("strategy:workbench.executionLabel")}>{i18n.t("strategy:workbench.execution")}</ResearchInfotip>
            </div>}
            </section>
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
        {inputIssues.length > 0 ? <Alert variant="destructive" className="mb-4" aria-label={t("completeSettings")}>
          <AlertTitle>{t("completeSettings")}</AlertTitle>
          <AlertDescription><ul className="mb-0">{inputIssues.map((issue) => <li key={issue.field}>
            <Button variant="link" size="sm" className="h-auto px-0 text-destructive max-[767px]:min-h-11" onClick={() => focusInput(issue.field)}>
              {t(`inputErrors.${issue.code}`)}
            </Button>
          </li>)}</ul></AlertDescription>
        </Alert> : null}
        <footer className="research-submit-bar flex flex-wrap items-center justify-between gap-3 border-t border-border py-4">
          <span className="text-xs text-muted-foreground">{storageError === null ? t(hasStoredDraft ? "draftSavedLocal" : "draftNew") : t(`storage.${storageError}`)}</span>
          <span className="text-xs text-muted-foreground">{coverage ? t("marketThrough", { date: coverage.end }) : t("marketNotReady")}</span>
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
            {fieldsOpen && fieldBrowserMode === "formula" ? <ResearchFieldBrowser catalog={catalog} onInsert={(identifier) => {
              alphaEditor.current?.insertAtSelection(identifier);
              restoreEditorFocus.current = true;
              setFieldsOpen(false);
            }} /> : fieldsOpen ? <ResearchFieldCatalog catalog={catalog} /> : null}
          </section>
        </SheetContent>
      </Sheet>
      <AlertDialog open={discardDialogOpen} onOpenChange={setDiscardDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader><AlertDialogTitle>{t("newResearch")}</AlertDialogTitle><AlertDialogDescription>{t("discardConfirm")}</AlertDialogDescription></AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting}>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction disabled={submitting} onClick={() => { startNewResearch(true); setDiscardDialogOpen(false); }}>{t("newResearch")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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
        <CalendarDateField id="research-start-date" label={t("startDateInput")}
          openLabel={t("openStartCalendar")} value={startDate} minimum={coverageStart}
          maximum={isIsoCalendarDate(endDate) ? endDate : coverageEnd}
          error={startError} errorId="start-date-error"
          onChange={startDate => onChange({ startDate, endDate })} />
        <CalendarDateField id="research-end-date" label={t("endDateInput")}
          openLabel={t("openEndCalendar")} value={endDate}
          minimum={isIsoCalendarDate(startDate) ? startDate : coverageStart}
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
