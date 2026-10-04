import { useEffect, useRef, useState } from "react";

import { coreFetch } from "../auth/coreFetch";
import { navigateCorePath } from "../shell/navigation";
import { interfaceLocale, useTranslation } from "../i18n";
import { formatResearchIssue, readResearchIssues, type ResearchRunAdmissionIssue } from "./admission";
import { createDiagnosticsScheduler, type DiagnosticState } from "./diagnostics";
import { researchDraftFeedback, type AdmissionFeedback, type ConfigurationFeedback } from "./draftFeedback";
import {
  beginResearchRun, emptyResearchDraft, finishResearchRun, hasUnexecutedChanges,
  loadResearchDraftState, persistResearchDraft, researchDraftKey, researchInputIssues,
  researchInputs, researchSpec, selectResearchKind, usesBuiltinAlpha, usesBuiltinPortfolio,
  type ResearchDraft, type ResearchInputField,
} from "./draft";

export type ResearchRunAdmissionRejection = { issues: ResearchRunAdmissionIssue[] };
/** Owns the research draft's persistence, validation, diagnostics and admission lifecycle. */
export function useResearchDraftController({
  researcherId, folderId, storage, confirmDiscard, startNewOnOpen, onInvalidInput, onNew,
}: {
  researcherId: string;
  folderId: string;
  storage: Storage;
  confirmDiscard: (message: string) => boolean;
  startNewOnOpen: boolean;
  onInvalidInput: (field: ResearchInputField) => void;
  onNew: () => void;
}) {
  const { t } = useTranslation("research");
  const [initial] = useState(() => {
    try {
      const loaded = loadResearchDraftState(storage, researcherId, folderId);
      if (loaded.upgradedExample) {
        try { persistResearchDraft(storage, researcherId, folderId, loaded.draft, loaded.view); }
        catch { return { ...loaded, failed: true }; }
      }
      return { ...loaded, failed: false };
    }
    catch { return { draft: emptyResearchDraft(), restored: false, view: "types" as const, failed: true }; }
  });
  const [draft, setDraft] = useState<ResearchDraft>(initial.draft);
  const [hasStoredDraft, setHasStoredDraft] = useState(initial.restored);
  const [choosingType, setChoosingType] = useState(initial.view === "types");
  const [storageError, setStorageError] = useState<"failed" | "accepted" | null>(initial.failed ? "failed" : null);
  const [diagnosticState, setDiagnosticState] = useState<DiagnosticState>({ kind: "idle", result: null });
  const [exposureDiagnosticState, setExposureDiagnosticState] = useState<DiagnosticState>({ kind: "idle", result: null });
  const [admissionFeedback, setAdmissionFeedback] = useState<AdmissionFeedback | null>(null);
  const [specFeedback, setSpecFeedback] = useState<ConfigurationFeedback | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [validationAttempted, setValidationAttempted] = useState(false);
  const specKey = JSON.stringify(researchInputs(draft));
  const inputIssues = validationAttempted ? researchInputIssues(researchInputs(draft)) : [];
  const attributed = researchDraftFeedback({ key: specKey, inputIssues, admission: admissionFeedback, configuration: specFeedback, diagnostics: diagnosticState });
  const feedback = {
    ...attributed,
    inputError(field: ResearchInputField) {
      const issue = attributed.inputIssue(field);
      return issue ? t(`inputErrors.${issue.code}`) : undefined;
    },
    fieldError(field: ResearchInputField) {
      const result = attributed.fieldIssue(field);
      return result?.kind === "input" ? t(`inputErrors.${result.issue.code}`)
        : result?.kind === "server" ? formatResearchIssue(result.issue, interfaceLocale()) : undefined;
    },
  };

  const formulaDiagnostics = useRef(createDiagnosticsScheduler());
  const exposureDiagnostics = useRef(createDiagnosticsScheduler(coreFetch, undefined, "exposure"));
  const specController = useRef<AbortController | null>(null);
  const admissionController = useRef<AbortController | null>(null);
  const admissionGeneration = useRef(0);
  const submittingRef = useRef(false);
  const handledGlobalNew = useRef(false);

  useEffect(() => {
    formulaDiagnostics.current.diagnose(usesBuiltinAlpha(draft) ? draft.formula : "", setDiagnosticState);
  }, [draft.formula, draft.researchKind, draft.strategyMode, draft.frameworkModules]);
  useEffect(() => {
    exposureDiagnostics.current.diagnose(
      usesBuiltinPortfolio(draft) ? draft.exposureExpression : "", setExposureDiagnosticState,
    );
  }, [draft.exposureExpression, draft.researchKind, draft.strategyMode, draft.frameworkModules]);
  useEffect(() => { specController.current?.abort(); }, [specKey]);
  useEffect(() => () => {
    formulaDiagnostics.current.dispose();
    exposureDiagnostics.current.dispose();
    specController.current?.abort();
    admissionGeneration.current += 1;
    admissionController.current?.abort();
  }, []);
  useEffect(() => {
    if (!startNewOnOpen || handledGlobalNew.current) return;
    handledGlobalNew.current = true;
    startNewResearch();
    navigateCorePath("/research", { replace: true });
  }, [startNewOnOpen]);

  function updateDraft(change: (current: ResearchDraft) => ResearchDraft): void {
    setDraft((current) => {
      const next = change(current);
      try {
        persistResearchDraft(storage, researcherId, folderId, next);
        setStorageError(null);
        setHasStoredDraft(true);
      } catch {
        setStorageError("failed");
      }
      return next;
    });
  }

  function startNewResearch(confirmed = false): void {
    if (!confirmed && hasUnexecutedChanges(draft) && !confirmDiscard(t("discardConfirm"))) return;
    try {
      storage.removeItem(researchDraftKey(researcherId, folderId));
    } catch {
      setStorageError("failed");
      return;
    }
    setDraft(emptyResearchDraft());
    setChoosingType(true);
    setHasStoredDraft(false);
    setValidationAttempted(false);
    setStorageError(null);
    setAdmissionFeedback(null);
    setSpecFeedback(null);
    onNew();
  }

  function chooseResearchKind(kind: ResearchDraft["researchKind"]): void {
    updateDraft(current => selectResearchKind(current, kind));
    setChoosingType(false);
  }

  function showResearchTypes(): void {
    try {
      persistResearchDraft(storage, researcherId, folderId, draft, "types");
      setStorageError(null);
      setHasStoredDraft(true);
    } catch {
      setStorageError("failed");
    }
    setChoosingType(true);
  }

  function validateInputs(): boolean {
    setValidationAttempted(true);
    const issues = researchInputIssues(researchInputs(draft));
    if (issues.length === 0) return true;
    onInvalidInput(issues[0].field);
    return false;
  }

  async function checkConfiguration(): Promise<void> {
    if (!validateInputs()) return;
    specController.current?.abort();
    const controller = new AbortController();
    specController.current = controller;
    const key = specKey;
    setSpecFeedback({ key, checking: true, status: "checking", issues: [] });
    try {
      const response = await coreFetch("/api/research/diagnostics", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(researchSpec(researchInputs(draft))), signal: controller.signal,
      });
      if (!response.ok) throw new Error("Configuration check is unavailable. Try again.");
      const result = await response.json() as { valid: boolean; issues: ResearchRunAdmissionIssue[] };
      if (typeof result.valid !== "boolean") throw new Error("Invalid configuration response");
      const issues = readResearchIssues(result.issues);
      if (result.valid !== (issues.length === 0)) throw new Error("Inconsistent configuration response");
      if (controller.signal.aborted) return;
      setSpecFeedback({ key, checking: false, issues, status: result.valid ? "valid" : "invalid" });
    } catch {
      if (controller.signal.aborted) return;
      setSpecFeedback({ key, checking: false, issues: [], status: "unavailable" });
    }
  }

  async function runResearch(): Promise<void> {
    if (submittingRef.current || !validateInputs()) return;
    const begun = beginResearchRun(draft, folderId, () => `research_${crypto.randomUUID()}`);
    try {
      persistResearchDraft(storage, researcherId, folderId, begun.draft);
      setStorageError(null);
      setHasStoredDraft(true);
    } catch {
      setStorageError("failed");
      return;
    }
    submittingRef.current = true;
    setDraft(begun.draft);
    setAdmissionFeedback(null);
    setSubmitting(true);
    const generation = ++admissionGeneration.current;
    admissionController.current?.abort();
    const controller = new AbortController();
    admissionController.current = controller;
    try {
      const response = await coreFetch("/api/research-runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(begun.command), signal: controller.signal,
      });
      if (generation !== admissionGeneration.current) return;
      if (response.status === 422) {
        const rejection = (await response.json()) as ResearchRunAdmissionRejection;
        const issues = readResearchIssues(rejection.issues);
        if (issues.length === 0) throw new Error("Empty research rejection");
        if (generation !== admissionGeneration.current) return;
        setAdmissionFeedback({ key: JSON.stringify(researchInputs(begun.draft)), issues });
        return;
      }
      if (!response.ok) throw new Error(`Research Run request failed (${response.status})`);
      const accepted = (await response.json()) as { id: string };
      if (generation !== admissionGeneration.current) return;
      let next: ResearchDraft | null;
      try {
        next = finishResearchRun(storage, researcherId, folderId, begun.command.request_id);
      } catch {
        setStorageError("accepted");
        return;
      }
      if (next === null) return;
      setDraft(next);
      setStorageError(null);
      window.location.assign(`/research-runs/${accepted.id}`);
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== admissionGeneration.current) return;
      setAdmissionFeedback({ key: JSON.stringify(researchInputs(begun.draft)), issues: [{
        code: "RUN_UNAVAILABLE", field: "run",
        message: reason instanceof Error ? reason.message : "Research Run request failed",
        severity: "error", range: null, details: null,
      }] });
    } finally {
      if (generation === admissionGeneration.current) {
        admissionController.current = null;
        submittingRef.current = false;
        setSubmitting(false);
      }
    }
  }

  return {
    draft, hasStoredDraft, choosingType, storageError, diagnosticState, exposureDiagnosticState,
    feedback, submitting, validationAttempted,
    updateDraft, chooseResearchKind, showResearchTypes, startNewResearch, checkConfiguration, runResearch,
  };
}
