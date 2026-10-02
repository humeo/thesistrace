import "./research-perplexity.css";
import { drawdownFields, type DrawdownField } from "./portfolioDrawdown";
import type { TakeProfitField } from "./takeProfit";
import {
  ArrowLeft,
  CaretDown,
  CaretRight,
  Check,
  DotsThree,
  FolderSimple,
  Minus,
  PencilSimple,
  Play,
  Plus,
  Trash,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";

import { cn } from "cn";
import type { AlphaCatalog } from "../alphaCatalog";
import { coreFetch } from "../auth/coreFetch";
import type { BrowserLocation } from "../auth/routing";
import { useUrlSelection } from "../shell/useUrlSelection";
import { i18n, interfaceLocale, useTranslation } from "../i18n";
import { type DataOverview } from "../data/DataPage";
import type { PythonSourceEditorHandle } from "./PythonSourceEditor";
import { AlphaFormulaEditor, type AlphaFormulaEditorHandle } from "./AlphaFormulaEditor";
import { ResearchCodeInput } from "./ResearchCodeInput";
import { folderDisplayName, folderMutationError, type FolderError } from "./folders";
import { formatResearchIssue, researchIssueField } from "./admission";
import { PythonStrategyAuthoring } from "./PythonStrategyAuthoring";
import { RuleDisclosure } from "./RuleDisclosure";
import { ResearchPositionSizing } from "./ResearchPositionSizing";
import { FrameworkAuthoring } from "./FrameworkAuthoring";
import { riskPolicyEnabled } from "./riskPolicies";
import { SimulationCostSettings } from "./SimulationCostSettings";
import type { CostField } from "./simulationCosts";
import { frameworkStages, type FrameworkStage } from "./frameworkModules";
import { programInputFields, type ProgramInputField } from "./pythonStrategy";
import { buildResearchDatePresets } from "./dateRange";
import { isIsoCalendarDate } from "../components/layout/calendarDate";
import { CalendarDateField } from "../components/layout/CalendarDateField";
import { ResearchFieldBrowser } from "./ResearchFieldBrowser";
import { useResearchDraftController } from "./useResearchDraftController";
import { researchInputStage } from "./draftFeedback";
import { ResearchTypeChooser } from "./ResearchTypeChooser";
import { Button } from "../components/ui/button";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Tooltip, TooltipContent, TooltipTrigger } from "../components/ui/tooltip";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "../components/ui/field";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "../components/ui/input-group";
import { RadioGroup, RadioGroupItem } from "../components/ui/radio-group";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";
import { PageContent } from "../components/layout/Page";
import { ResearchParameterHelp } from "./ResearchParameterHelp";
import { ResearchInfotip } from "./ResearchInfotip";
import { Popover, PopoverContent, PopoverHeader, PopoverTitle } from "../components/ui/popover";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuLinkItem, DropdownMenuSeparator, DropdownMenuTrigger,
  DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger,
} from "../components/ui/dropdown-menu";
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
  selectStrategyMode,
  selectFrameworkModule,
  selectRiskPolicy,
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

const stageLocations = {
  universe_selection: "universe", alpha: "signal", portfolio_construction: "portfolio", risk_management: "risk",
} as const satisfies Record<FrameworkStage, string>;

export function ResearchWorkspacePage({ location, researcherId }: { location: BrowserLocation; researcherId: string }) {
  const { t } = useTranslation("research");
  const [resources, setResources] = useState<WorkspaceResources | null>(null);
  const [error, setError] = useState<"unavailable" | null>(null);
  const [folderError, setFolderError] = useState<FolderError | null>(null);
  const [folderMenuOpen, setFolderMenuOpen] = useState(false);
  const resourceRequest = useRef<AbortController | null>(null);
  const parameters = new URLSearchParams(location.search);
  const requestedFolderId = parameters.has("new") ? null : parameters.get("folder");

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
  }, [requestedFolderId]);

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
        folder: currentResources.folder.id === folder.id ? defaultFolder : currentResources.folder,
        folders: currentResources.folders.filter((item) => item.id !== folder.id),
      });
      if (currentResources.folder.id === folder.id) window.history.replaceState(null, "", "/research");
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
            menuOpen={folderMenuOpen}
            onMenuOpenChange={setFolderMenuOpen}
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
  menuOpen,
  onMenuOpenChange,
  onCreate,
  onRename,
  onDelete,
}: {
  activeFolder: ResearchFolder;
  folders: ResearchFolder[];
  error: FolderError | null;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  onCreate: (name: string) => Promise<boolean>;
  onRename: (folderId: string, name: string) => Promise<boolean>;
  onDelete: (folder: ResearchFolder) => Promise<boolean>;
}) {
  const { t } = useTranslation("research");
  const [newName, setNewName] = useState("");
  const [renameName, setRenameName] = useState(activeFolder.name);
  const [folderForm, setFolderForm] = useState<"create" | "rename" | null>(null);
  const [renameTarget, setRenameTarget] = useState<ResearchFolder | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ResearchFolder | null>(null);
  const [folderPending, setFolderPending] = useState(false);
  const [showError, setShowError] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const folderNameInput = useRef<HTMLInputElement>(null);
  const creating = folderForm === "create";
  const formName = creating ? newName : renameName;
  const folderError = showError && error !== null ? t(`folderErrors.${error}`) : null;
  const invalidName = showError && (error === "invalid" || error === "nameExists");
  function returnToFolders() {
    setFolderForm(null);
    setShowError(false);
    onMenuOpenChange(true);
  }
  return (
    <div className="min-w-0">
      <DropdownMenu open={menuOpen} onOpenChange={(open) => { onMenuOpenChange(open); if (open) setShowError(false); }}>
        <DropdownMenuTrigger render={<Button ref={menuTrigger} variant="outline" size="sm" aria-label={t("folderMenu")} />}>
          <FolderSimple aria-hidden="true" data-icon="inline-start" />
          <span className="max-w-48 truncate">{t("activeFolder", { name: folderDisplayName(activeFolder) })}</span>
          <CaretDown aria-hidden="true" data-icon="inline-end" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-60 p-1" aria-label={t("folderMenu")}
          finalFocus={folderForm !== null || deleteTarget !== null ? false : menuTrigger}>
          <DropdownMenuGroup aria-label={t("folderNavigation")} className="max-h-56 overflow-auto">
            <DropdownMenuLabel>{t("folders")}</DropdownMenuLabel>
            {folders.map((folder) => (
              <DropdownMenuGroup key={folder.id} aria-label={folderDisplayName(folder)} className="flex items-center gap-1">
                <DropdownMenuLinkItem
                  aria-current={folder.id === activeFolder.id ? "page" : undefined}
                  href={folder.is_default ? "/research" : `/research?folder=${folder.id}`}
                  className="min-w-0 flex-1"
                  title={folderDisplayName(folder)}
                >
                  <FolderSimple aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate">{folderDisplayName(folder)}</span>
                  {folder.id === activeFolder.id ? <Check aria-hidden="true" /> : null}
                </DropdownMenuLinkItem>
                {!folder.is_default ? <DropdownMenuSub>
                  <DropdownMenuSubTrigger openOnHover={false}
                    className="size-8 shrink-0 justify-center p-0 [&>svg:last-child]:hidden"
                    aria-label={t("folderRowActions", { name: folderDisplayName(folder) })}>
                    <DotsThree aria-hidden="true" />
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent className="w-44 p-1" sideOffset={4} alignOffset={0}
                    aria-label={t("folderRowActions", { name: folderDisplayName(folder) })}
                    finalFocus={folderForm !== null || deleteTarget !== null ? false : undefined}>
                    <DropdownMenuItem onClick={() => { setRenameTarget(folder); setRenameName(folder.name); setFolderForm("rename"); }}>
                      <PencilSimple aria-hidden="true" />{t("renameFolder")}
                    </DropdownMenuItem>
                    <DropdownMenuItem variant="destructive" onClick={() => setDeleteTarget(folder)}>
                      <Trash aria-hidden="true" />{t("deleteFolder")}
                    </DropdownMenuItem>
                  </DropdownMenuSubContent>
                </DropdownMenuSub> : null}
              </DropdownMenuGroup>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup aria-label={t("folderActions")}>
            <DropdownMenuItem onClick={() => setFolderForm("create")}>
              <Plus aria-hidden="true" />{t("newFolder")}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <Popover open={folderForm !== null} onOpenChange={(open) => { if (!open && !folderPending) setFolderForm(null); }}>
        <PopoverContent anchor={menuTrigger} align="start" className="gap-4 p-3" initialFocus={folderNameInput} finalFocus={menuOpen ? false : menuTrigger}>
          <PopoverHeader>
            <PopoverTitle>{t(creating ? "newFolder" : "renameFolder")}</PopoverTitle>
          </PopoverHeader>
          <form onSubmit={(event) => {
            event.preventDefault();
            if (formName.trim() === "" || folderPending || (!creating && (renameTarget === null || formName.trim() === renameTarget.name))) return;
            setShowError(true);
            setFolderPending(true);
            const mutation = creating ? onCreate(newName) : onRename(renameTarget!.id, renameName);
            void mutation.then((success) => {
              if (success) { if (creating) setNewName(""); returnToFolders(); }
            }).finally(() => setFolderPending(false));
          }}>
            <FieldGroup className="gap-4">
              <Field data-invalid={invalidName} data-disabled={folderPending}>
                <FieldLabel htmlFor={creating ? "new-folder-name" : "rename-folder-name"}>{t("folderName")}</FieldLabel>
                <Input ref={folderNameInput} id={creating ? "new-folder-name" : "rename-folder-name"} maxLength={120}
                  aria-invalid={invalidName} aria-describedby={folderError !== null ? "folder-form-error" : undefined}
                  disabled={folderPending} onChange={(event) => creating ? setNewName(event.target.value) : setRenameName(event.target.value)} value={formName} />
                {folderError !== null ? <FieldError id="folder-form-error">{folderError}</FieldError> : null}
              </Field>
              <Field orientation="horizontal" className="justify-end">
                <Button variant="outline" size="sm" type="button" disabled={folderPending} onClick={returnToFolders}>{t("cancel")}</Button>
                <Button size="sm" disabled={formName.trim() === "" || folderPending || (!creating && (renameTarget === null || formName.trim() === renameTarget.name))} type="submit">
                  {t(creating ? "create" : "renameFolder")}
                </Button>
              </Field>
            </FieldGroup>
          </form>
        </PopoverContent>
      </Popover>
      <AlertDialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open && !folderPending) setDeleteTarget(null); }}>
        <AlertDialogContent finalFocus={menuTrigger}>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("deleteFolder")}</AlertDialogTitle>
            <AlertDialogDescription>{t("deleteFolderConfirm", { name: folderDisplayName(deleteTarget ?? activeFolder) })}</AlertDialogDescription>
          </AlertDialogHeader>
          {folderError !== null ? <FieldError>{folderError}</FieldError> : null}
          <AlertDialogFooter>
            <AlertDialogCancel className="max-[767px]:min-h-11" disabled={folderPending}>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" className="max-[767px]:min-h-11" disabled={folderPending} onClick={() => {
              if (deleteTarget === null) return;
              setShowError(true);
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
  const [nameEditing, setNameEditing] = useState(false);
  const [nameValue, setNameValue] = useState("");
  const nameCancel = useRef(false);
  const [conditionsOpen, setConditionsOpen] = useState(false);
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);
  const [editorGeneration, setEditorGeneration] = useState(0);
  const [module, setModule] = useUrlSelection("module", Object.values(stageLocations), "universe");
  const activeStage = frameworkStages.find(stage => stageLocations[stage] === module)!;
  const setActiveStage = (stage: FrameworkStage) => setModule(stageLocations[stage]);
  const workspace = useRef<HTMLElement>(null);
  const focusEditorOnEntry = useRef(false);
  const alphaEditor = useRef<AlphaFormulaEditorHandle>(null);
  const exposureEditor = useRef<AlphaFormulaEditorHandle>(null);
  const [pendingInput, setPendingInput] = useState<ResearchInputField | null>(null);
  function focusInput(field: ResearchInputField) {
    if (["startDate", "endDate", "initialCashCny", "universe", "neutralization"].includes(field) || field.startsWith("costs.")) setConditionsOpen(true);
    const stage = researchInputStage(field);
    if (stage) setActiveStage(stage);
    setPendingInput(field);
  }
  const {
    draft, choosingType, storageError, diagnosticState, exposureDiagnosticState,
    feedback, submitting, validationAttempted,
    updateDraft, chooseResearchKind, showResearchTypes, startNewResearch, checkConfiguration, runResearch,
  } = useResearchDraftController({
    researcherId, folderId: folder.id, storage, startNewOnOpen,
    confirmDiscard: message => {
      if (confirmDiscard) return confirmDiscard(message);
      setDiscardDialogOpen(true);
      return false;
    },
    onInvalidInput: focusInput, onNew: () => { setEditorGeneration(value => value + 1); setActiveStage("universe_selection"); },
  });
  const { inputIssues, inputError, fieldError: programError, programErrorLine, configuration: specFeedback,
    admissionIssues: visibleIssues, formulaDiagnostics: serverDiagnostics } = feedback;
  const costError = (field: CostField) => feedback.fieldError(`costs.${field}`);
  const direct = draft.researchKind === "strategy_backtest" && draft.strategyMode === "direct";
  useEffect(() => {
    if (choosingType || !focusEditorOnEntry.current) return;
    workspace.current?.querySelector<HTMLElement>("h1")?.focus();
    focusEditorOnEntry.current = false;
  }, [choosingType]);
  const factor = draft.researchKind === "factor_evaluation";
  const notesTooLong = Array.from(draft.hypothesis).length > MAX_HYPOTHESIS_LENGTH;
  function commitName() {
    if (nameCancel.current) { nameCancel.current = false; return; }
    updateDraft(current => ({ ...current, name: nameValue.trim() }));
    setNameEditing(false);
  }
  const builtinAlpha = usesBuiltinAlpha(draft);
  useEffect(() => {
    if (pendingInput === null) return;
    if (pendingInput === "formula") {
      alphaEditor.current?.focus();
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
  }, [pendingInput, activeStage, conditionsOpen]);
  const [fieldsOpen, setFieldsOpen] = useState(false);
  const [fieldBrowserMode, setFieldBrowserMode] = useState<"formula" | "catalog">("formula");
  const fieldsTrigger = useRef<HTMLButtonElement>(null);
  const fieldsPanel = useRef<HTMLElement>(null);
  const restoreEditorFocus = useRef(false);
  const pythonEditor = useRef<PythonSourceEditorHandle | null>(null);
  function closeFields() {
    setFieldsOpen(false);
  }
  function fieldsButton(mode: "formula" | "catalog" = "formula", editor?: () => PythonSourceEditorHandle | null) {
    const props = {
      "aria-expanded": fieldsOpen,
      "aria-controls": "research-fields-panel",
      onClick: (event: MouseEvent<HTMLButtonElement>) => {
        fieldsTrigger.current = event.currentTarget;
        pythonEditor.current = editor?.() ?? null;
        setFieldBrowserMode(mode);
        setFieldsOpen(open => !open);
      },
    };
    return (
      <Button type="button" variant="ghost" size="xs" {...props}>
        {t("browseFields")}<CaretRight data-icon="inline-end" aria-hidden="true" />
      </Button>
    );
  }
  const coverage = data.market_research_readiness ? data.market_coverage : null;
  const configurationIssues = specFeedback?.issues ?? [];
  const hasConfigurationIssues = inputIssues.length > 0 || configurationIssues.length > 0 || visibleIssues.length > 0;
  const configurationMessage = inputIssues.length > 0 || visibleIssues.length > 0
    ? t("issueCount", { count: inputIssues.length + visibleIssues.length })
    : specFeedback
      ? t(`configuration.${specFeedback.status}`)
      : feedback.configurationChanged ? t("configurationChanged") : null;
  const stageIssues = Object.fromEntries(frameworkStages.map(stage => [stage, 0])) as Record<FrameworkStage, number>;
  for (const issue of [...inputIssues, ...visibleIssues, ...configurationIssues]) {
    const stage = issueStage(issue.field);
    if (stage !== null) stageIssues[stage] += 1;
  }
  const alphaAuthoring = <>
        <FieldGroup className="gap-3">
          <Field data-invalid={Boolean(inputError("formula"))} className="gap-4">
            <div className="flex h-7 items-center justify-between gap-3">
              <div className="flex items-center gap-1">
                <h2 className="m-0 text-base font-semibold">{t("formula")}</h2>
                <ResearchInfotip label={t("formulaSyntax")} buttonLabel={t("formulaSyntax")}>
                  <div className="grid gap-3">
                    <ul className="m-0 grid list-disc gap-2 pl-4">
                      <li>{t("formulaSyntaxExpression")}</li>
                      <li>{t("formulaSyntaxFields")}</li>
                      <li>{t("formulaSyntaxFunctions")}</li>
                      <li>{t("formulaSyntaxWindows")}</li>
                    </ul>
                    <code className="text-foreground">rank(pct_change(close, 20))</code>
                    <p className="m-0">{t("formulaSyntaxExample")}</p>
                  </div>
                </ResearchInfotip>
              </div>
              {fieldsButton()}
            </div>
            <ResearchCodeInput height={factor ? 382 : 280}>
              <AlphaFormulaEditor
                ref={alphaEditor}
                catalog={catalog}
                diagnostics={serverDiagnostics}
                formula={draft.formula}
                error={inputError("formula")}
                onChange={(formula, editor) => updateDraft((current) => ({ ...current, formula, editor }))}
                selection={draft.editor}
              />
            </ResearchCodeInput>
            {inputError("formula") && <FieldError>{inputError("formula")}</FieldError>}
          </Field>
        </FieldGroup>
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

  const portfolioSettings = (minimumHoldingInput: ReactNode) => <FieldGroup className="research-portfolio-fields gap-6">
      <FieldGroup className="research-holdings-fields grid grid-cols-2 gap-4">
      <ResearchNumberStepper actionLabel={t("holdingsAction")} id="research-holdings-count" label={t("holdings")}
        error={inputError("holdingsCount")} maximum={100} minimum={1} value={draft.holdingsCount}
        onChange={holdingsCount => updateDraft(current => ({ ...current, holdingsCount }))} />
      <ResearchNumberStepper actionLabel={t("intervalAction")} id="research-selection-sessions" label={t("interval")}
        error={inputError("selectionEverySessions")} maximum={20} minimum={1} value={draft.selectionEverySessions}
        onChange={selectionEverySessions => updateDraft(current => ({ ...current, selectionEverySessions }))} />
      </FieldGroup>
    <FieldGroup className="grid grid-cols-2 items-start gap-4">
    <FieldGroup className="gap-4">
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
      <SelectTrigger id="portfolio-weighting" className="w-full max-w-72"><SelectValue>{t(`weightings.${draft.weighting}`)}</SelectValue></SelectTrigger>
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
    </FieldGroup>
    {minimumHoldingInput}
    </FieldGroup>
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
  const universeLabel = !factor && !direct ? i18n.t("strategy:workbench.baseUniverse") : t("universe");
  const universeOptionLabel = (count: number) => !factor && !direct
    ? i18n.t("strategy:workbench.baseUniverseOption", { count }) : t("top", { count });
  const universeSettings = <FieldGroup className="gap-2">
              <Field>
                <div className="flex items-center gap-1">
                  <FieldLabel htmlFor="research-universe">{universeLabel}</FieldLabel>
                  {!factor && !direct
                    ? <ResearchInfotip label={universeLabel}>{t("universeHelp")}</ResearchInfotip>
                    : <ResearchParameterHelp helpId="universe" text={<span className="grid gap-2"><span>{t("universeHelp")}</span>{direct && <span>{t("directUniverseHelp")}</span>}</span>} />}
                </div>
                <Select value={draft.universe || null} onValueChange={(value) => updateDraft((current) => ({ ...current, universe: value ?? "" }))}>
                  <SelectTrigger id="research-universe" aria-invalid={Boolean(inputError("universe"))}
                    aria-describedby={inputError("universe") ? "universe-error" : undefined} className="w-full">
                    <SelectValue placeholder={t("notSelected")}>
                      {draft.universe ? universeOptionLabel(Number(draft.universe.slice(3))) : undefined}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent><SelectGroup>
                    {[300, 1000, 2000, 3000].map((count) => <SelectItem value={`top${count}`} key={count}>{universeOptionLabel(count)}</SelectItem>)}
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
        stageIssues={stageIssues}
        riskPolicyEnabled={policy => riskPolicyEnabled(draft, policy)}
        selectRiskPolicy={(policy, enabled) => updateDraft(current => selectRiskPolicy(current, policy, enabled))}
        updateDrawdown={changes => updateDraft(current => ({ ...current, ...changes }))}
        takeProfitTiers={draft.takeProfitTiers} updateTakeProfitTiers={takeProfitTiers => updateDraft(current => ({
          ...current, takeProfitTiers,
          ...(takeProfitTiers.length === 0 ? { riskPolicySelection: { ...current.riskPolicySelection, takeProfit: false } } : {}),
        }))}
        stopLossThreshold={draft.stopLossThreshold} updateStopLoss={stopLossThreshold => updateDraft(current => ({ ...current, stopLossThreshold }))}
        maximumHoldingSessions={draft.maximumHoldingSessions} updateMaximumHoldingSessions={maximumHoldingSessions => updateDraft(current => ({ ...current, maximumHoldingSessions }))}
        minimumHoldingSessions={draft.minimumHoldingSessions} updateMinimumHoldingSessions={minimumHoldingSessions => updateDraft(current => ({ ...current, minimumHoldingSessions }))}
        modules={draft.frameworkModules} error={programError} errorLine={programErrorLine}
        fieldsButton={editor => fieldsButton("catalog", editor)}
        universeSettings={!factor && !direct ? universeSettings : null}
        neutralizationSettings={!factor && !direct ? <RuleDisclosure title={i18n.t("strategy:workbench.advancedSelection")}
          configured={draft.neutralization === "industry"}
          invalid={Boolean(inputError("neutralization"))}>{neutralizationSettings}</RuleDisclosure> : null}
        alphaEditor={alphaAuthoring} portfolioSettings={portfolioSettings}
        selectModule={(stage, kind) => updateDraft(current => selectFrameworkModule(current, stage, kind))}
        updateProgram={(stage, changes) => updateDraft(current => ({ ...current, frameworkModules: {
          ...current.frameworkModules, [stage]: { ...current.frameworkModules[stage], program: { ...current.frameworkModules[stage].program, ...changes } },
        } }))} />
    </div>
    <div hidden={!direct} className={cn("min-w-0", !direct && "hidden")}>
      <PythonStrategyAuthoring inputs={draft} error={programError} errorLine={programErrorLine()}
        onChange={changes => updateDraft(current => ({ ...current, ...changes }))} fieldsButton={editor => fieldsButton("catalog", editor)} />
    </div>
  </div>;
  if (choosingType) return <ResearchTypeChooser storageError={storageError} folderNavigation={folderNavigation} onChoose={kind => {
    focusEditorOnEntry.current = true;
    chooseResearchKind(kind);
  }} />;
  return (
    <>
    <section ref={workspace} aria-label={t("title")} className="research-reading-workspace @container min-w-0">
      <PageContent width="wide" className={cn("research-page-content", hasConfigurationIssues && "research-page-with-issues")}>
        <h1 className="sr-only" tabIndex={-1}>{t("title")}</h1>
        <header className="research-page-header">
          <div className="research-identity">
            <Tooltip>
              <TooltipTrigger render={<Button variant="ghost" size="icon" type="button" aria-label={t("entry.back")} disabled={submitting} onClick={showResearchTypes} />}>
                <ArrowLeft aria-hidden="true" />
              </TooltipTrigger>
              <TooltipContent side="bottom">{t("entry.back")}</TooltipContent>
            </Tooltip>
            <div className="research-name">{nameEditing ? <Input id="research-name" aria-label={t("name")} className="research-name-input" autoComplete="off" maxLength={200}
            autoFocus value={nameValue} onChange={event => setNameValue(event.target.value)} onBlur={commitName}
            onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); commitName(); } else if (event.key === "Escape") { nameCancel.current = true; setNameEditing(false); } }} />
            : <Button variant="ghost" className="research-name-button" type="button" title={t("editName")} onClick={() => { nameCancel.current = false; setNameValue(draft.name); setNameEditing(true); }}>
              <span className="truncate">{draft.name.trim() || t("untitled")}</span><PencilSimple aria-hidden="true" data-icon="inline-end" />
            </Button>}</div>
            <div className="research-identity-meta">{folderNavigation}</div>
          </div>
          <div className="research-header-actions">
            <Tooltip>
              <TooltipTrigger render={<Button variant="ghost" size="icon" type="button" aria-label={t("newResearch")} disabled={submitting} onClick={() => startNewResearch()} />}>
                <Plus aria-hidden="true" size={20} />
              </TooltipTrigger>
              <TooltipContent side="bottom">{t("newResearch")}</TooltipContent>
            </Tooltip>
          </div>
        </header>
        <div className={cn("research-workbench-grid", direct && "research-workbench-direct")}>
          <div className="research-authoring-column min-w-0">
          <div className={cn("research-workbench", factor && "research-workbench-factor")}>
          {!factor && <div className="research-workbench-toolbar">
            <FieldSet className="m-0 min-w-0 border-0 p-0">
              <FieldLegend className="sr-only">{t("strategyMode")}</FieldLegend>
              <RadioGroup aria-label={t("strategyMode")} className="flex flex-wrap gap-6" value={draft.strategyMode} onValueChange={mode => {
                if (mode === "framework" || mode === "direct") updateDraft(current => selectStrategyMode(current, mode));
              }}>
                <div className="flex items-center gap-1">
                  <Field orientation="horizontal" className="w-auto">
                    <RadioGroupItem id="strategy-mode-framework" value="framework" />
                    <FieldLabel htmlFor="strategy-mode-framework" className="min-h-9 cursor-pointer items-center">{t("frameworkMode")}</FieldLabel>
                  </Field>
                  <ResearchInfotip label={t("frameworkMode")}>{i18n.t("strategy:workbench.ruleModeHelp")}</ResearchInfotip>
                </div>
                <div className="flex items-center gap-1">
                  <Field orientation="horizontal" className="w-auto">
                    <RadioGroupItem id="strategy-mode-direct" value="direct" />
                    <FieldLabel htmlFor="strategy-mode-direct" className="min-h-9 cursor-pointer items-center">{t("directMode")}</FieldLabel>
                  </Field>
                  <ResearchInfotip label={t("directMode")}>{i18n.t("strategy:workbench.directHelp")}</ResearchInfotip>
                </div>
              </RadioGroup>
            </FieldSet>
          </div>}
          <section aria-label={t(direct ? "pythonAuthoring" : factor ? "authoring" : "frameworkAuthoring")} className="research-editor-column grid min-w-0 content-start gap-5">
            <Button type="button" variant="outline" className="research-conditions-toggle" aria-expanded={conditionsOpen} aria-controls="research-conditions-panel" onClick={() => setConditionsOpen(value => !value)}>
              {factor ? t("factorConditions") : i18n.t("strategy:workbench.conditionsTitle")}<CaretDown aria-hidden="true" size={16} />
            </Button>
            {authoring}
          </section>
          </div>

          <FieldGroup className="mt-8">
            <Field data-invalid={notesTooLong}>
              <FieldLabel htmlFor="research-notes">{i18n.t("strategy:workbench.notes")}</FieldLabel>
              <Textarea id="research-notes" rows={2} className="min-h-16 max-h-60 resize-y overflow-y-auto"
                aria-describedby={notesTooLong ? "research-notes-limit" : undefined} aria-invalid={notesTooLong}
                placeholder={t("notesPlaceholder")} value={draft.hypothesis}
                onChange={(event) => updateDraft((current) => ({ ...current, hypothesis: event.target.value }))} />
              <FieldError id="research-notes-limit">{notesTooLong ? t("inputErrors.notesLength") : null}</FieldError>
            </Field>
          </FieldGroup>
          </div>

          <aside id="research-conditions-panel" aria-label={t("settings")} className={cn("research-conditions-column", conditionsOpen && "research-conditions-open")}>
            <section className="research-settings-panel grid min-w-0 gap-5">
            <h2 className="m-0 text-base font-semibold">{factor ? t("factorConditions") : i18n.t("strategy:workbench.conditionsTitle")}</h2>
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
                <Input id="initial-cash" inputMode="decimal" placeholder="1000000.00" value={draft.initialCashCny}
                  aria-invalid={(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny)}
                  aria-describedby="initial-cash-error" onChange={event => updateDraft(current => ({ ...current, initialCashCny: event.target.value }))} />
                <FieldError id="initial-cash-error">{(validationAttempted || draft.initialCashCny !== "") && !isValidInitialCash(draft.initialCashCny) ? t("cashInvalid") : undefined}</FieldError>
              </Field>}
            </FieldGroup>
            {!factor && <SimulationCostSettings costs={draft.costs} onChange={costs => updateDraft(current => ({ ...current, costs }))} error={costError} />}
            {!factor && <div className="flex items-center gap-1 border-t border-border pt-3 text-sm text-muted-foreground">
              <span>{i18n.t("strategy:workbench.executionShort")}</span>
              <ResearchInfotip label={i18n.t("strategy:workbench.executionLabel")}>{i18n.t("strategy:workbench.execution")}</ResearchInfotip>
            </div>}
            </section>
          </aside>
        </div>

        {storageError !== null ? <p className="text-sm text-destructive" role="alert">{t(`storage.${storageError}`)}</p> : null}
      </PageContent>

      <Sheet open={fieldsOpen} onOpenChange={(open) => { if (open) setFieldsOpen(true); else closeFields(); }}>
        <SheetContent side="right" showCloseButton={false} className="w-full max-w-[520px] overflow-y-auto p-4"
          initialFocus={() => fieldsPanel.current?.querySelector<HTMLInputElement>('input[role="searchbox"]') ?? null}
          finalFocus={() => {
            if (restoreEditorFocus.current) {
              restoreEditorFocus.current = false;
              if (fieldBrowserMode === "catalog") pythonEditor.current?.focus();
              else alphaEditor.current?.focus();
              return false;
            }
            return fieldsTrigger.current;
          }}>
          <SheetHeader className="flex flex-row items-center justify-between p-0 pb-4">
            <SheetTitle className="text-base">{t("fieldBrowser")}</SheetTitle>
            <Button variant="ghost" size="icon-sm" className="max-[767px]:size-11" aria-label={t("closeFields")} onClick={closeFields}><X aria-hidden="true" /></Button>
          </SheetHeader>
          <section id="research-fields-panel" ref={fieldsPanel} className="min-w-0">
            {fieldsOpen ? <ResearchFieldBrowser catalog={catalog} python={fieldBrowserMode === "catalog"} onInsert={(identifier) => {
              if (fieldBrowserMode === "catalog") pythonEditor.current?.insertAtSelection(identifier);
              else alphaEditor.current?.insertAtSelection(identifier);
              restoreEditorFocus.current = true;
              setFieldsOpen(false);
            }} /> : null}
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
    {/* Keep viewport actions outside the editor's container-query boundary. */}
    <div className="research-action-dock">
      <div role="group" aria-label={t("actions")} className="pointer-events-auto mx-4 flex min-w-0 max-w-2xl flex-col items-center gap-2">
        {hasConfigurationIssues && <Alert variant="destructive" className="max-h-40 overflow-y-auto" aria-label={t("configurationStatus")}>
          <AlertDescription>
            {inputIssues.length > 0 && <ul className="m-0 grid list-none gap-1 p-0" aria-label={t("completeSettings")}>
              {inputIssues.map(issue => <li key={issue.field}><Button variant="link" size="sm" className="h-auto min-h-7 justify-start whitespace-normal p-0 text-left" onClick={() => focusInput(issue.field)}>{t(`inputErrors.${issue.code}`)}</Button></li>)}
            </ul>}
            {configurationIssues.length > 0 && <ul className="m-0 grid list-none gap-1 p-0" aria-label={t("configurationIssues")}>
              {configurationIssues.map((issue, index) => <li key={`${issue.field}-${issue.code}-${index}`}>
                {serverIssueInput(issue.field) ? <Button variant="link" size="sm" className="h-auto min-h-7 justify-start whitespace-normal p-0 text-left" onClick={() => focusInput(serverIssueInput(issue.field)!)}>
                  {researchIssueField(issue.field, locale)}: {formatResearchIssue(issue, locale)}
                </Button> : <span>{researchIssueField(issue.field, locale)}: {formatResearchIssue(issue, locale)}</span>}
              </li>)}
            </ul>}
            {visibleIssues.length > 0 && <ul className="m-0 grid list-none gap-1 p-0" aria-label={t("runIssues")}>
              {visibleIssues.map((issue, index) => <li key={`${issue.field}-${issue.code}-${index}`}>
                {serverIssueInput(issue.field) ? <Button variant="link" size="sm" className="h-auto min-h-7 justify-start whitespace-normal p-0 text-left" onClick={() => focusInput(serverIssueInput(issue.field)!)}>
                  {researchIssueField(issue.field, locale)}: {formatResearchIssue(issue, locale)}
                </Button> : <span>{researchIssueField(issue.field, locale)}: {formatResearchIssue(issue, locale)}</span>}
              </li>)}
            </ul>}
          </AlertDescription>
        </Alert>}
        <div className="research-action-bar rounded-xl border border-border bg-popover p-2 shadow-md">
          <Button variant="outline" type="button" disabled={submitting || specFeedback?.checking}
            onClick={() => void checkConfiguration()}>{t("check")}</Button>
          {configurationMessage !== null && <span role="status" className="min-w-0 max-w-72 text-xs text-muted-foreground">{configurationMessage}</span>}
          <Button type="button" disabled={submitting} onClick={() => void runResearch()}>
            <Play aria-hidden="true" weight="fill" />{t(submitting ? "running" : factor ? "runEvaluation" : "runBacktest")}
          </Button>
        </div>
      </div>
    </div>
    </>
  );
}

function issueStage(field: string): FrameworkStage | null {
  if (field.includes("universe")) return "universe_selection";
  if (field.includes("alpha") || field.includes("formula") || field.includes("neutralization")) return "alpha";
  if (/holdingsCount|holdings_count|selectionEverySessions|selection_every_sessions|weighting|volatilityWindow|exposureExpression|exposure_expression|minimumHoldingSessions|minimum_holding_sessions|portfolio_construction/.test(field)) return "portfolio_construction";
  if (/risk_management|drawdown|stopLoss|stop_loss|maximumHolding|maximum_holding|takeProfit|take_profit/.test(field)) return "risk_management";
  return null;
}

function serverIssueInput(field: string): ResearchInputField | null {
  const simple: Record<string, ResearchInputField> = {
    formula: "formula", universe: "universe", neutralization: "neutralization", hypothesis: "hypothesis",
    start_date: "startDate", end_date: "endDate", initial_cash_cny: "initialCashCny",
    holdings_count: "holdingsCount", selection_every_sessions: "selectionEverySessions",
    exposure_expression: "exposureExpression", minimum_holding_sessions: "minimumHoldingSessions",
    maximum_holding_sessions: "maximumHoldingSessions", stop_loss_threshold: "stopLossThreshold",
  };
  if (field in simple) return simple[field];
  if (field.startsWith("costs.")) return field as ResearchInputField;
  const program = field.match(/^(?:modules\.(universe_selection|alpha|portfolio_construction|risk_management)\.)?program\.source$/);
  if (program) {
    const stage = program[1] as FrameworkStage | undefined;
    return stage ? `${stage}.programSource` : "programSource";
  }
  return null;
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
  const presets = buildResearchDatePresets(coverageStart, coverageEnd, endDate);
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
  programSource: "#python-source",
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
