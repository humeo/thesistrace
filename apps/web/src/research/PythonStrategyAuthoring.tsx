import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import type { ProgramInputs, ProgramInputField } from "./pythonStrategy";
import type { FrameworkStage } from "./frameworkModules";
import { useTranslation } from "../i18n";
import { Field, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import type { PythonSourceEditorHandle } from "./PythonSourceEditor";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { ResearchInfotip } from "./ResearchInfotip";

export type PythonFieldsButton = (editor: () => PythonSourceEditorHandle | null) => ReactNode;

const PythonSourceEditor = lazy(() => import("./PythonSourceEditor").then(module => ({ default: module.PythonSourceEditor })));

const AuthoringReference = lazy(() => import("../mcp/AuthoringReference").then(module => ({ default: module.AuthoringReference })));

export function PythonStrategyAuthoring({ active, inputs, onChange, error, fieldsButton, stage, errorLine }: {
  active: boolean;
  inputs: ProgramInputs; onChange: (changes: Partial<ProgramInputs>) => void;
  error: (field: ProgramInputField) => string | undefined; fieldsButton: PythonFieldsButton;
  stage?: FrameworkStage; errorLine?: number | null;
}) {
  const { t } = useTranslation("strategy");
  const { t: commonText } = useTranslation("common");
  const [opened, setOpened] = useState(active);
  useEffect(() => { if (active) setOpened(true); }, [active]);
  const id = (suffix: string) => `${stage ? `${stage}-` : ""}python-${suffix}`;
  const sourceError = error("programSource");
  const editor = useRef<PythonSourceEditorHandle>(null);
  return <FieldGroup className="min-w-0 gap-4">
    <Field data-invalid={Boolean(sourceError)}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-1">
          <FieldLabel htmlFor={id("source")}>{t("python.source")}</FieldLabel>
          <ResearchInfotip label={t("workbench.programHelp")} buttonLabel={t("workbench.programHelp")}>
            <div className="grid gap-3">
              <p className="m-0">{t("python.shortcuts")}</p>
              <dl className="m-0 grid gap-3 text-sm">
                <div><dt className="font-medium">{t("python.systemInput")}</dt><dd className="m-0 text-muted-foreground">{t("python.systemInputHelp")}</dd></div>
                <div><dt className="font-medium">{t("python.strategyOutput")}</dt><dd className="m-0 text-muted-foreground">{stage ? t(`python.framework.${stage}`) : t("python.strategyOutputHelp")}</dd></div>
                <div><dt className="font-medium">{t("python.systemExecution")}</dt><dd className="m-0 text-muted-foreground">{t("python.systemExecutionHelp")}</dd></div>
              </dl>
              <div className="grid gap-3 border-t border-border pt-3">
                <code>{t("python.signature")}</code>
                <p className="m-0">{stage ? t(`python.framework.${stage}`) : t("python.directExample")}</p>
                <p className="m-0">{t("python.historyContext")}</p>
                <p className="m-0">{t("python.accountReference")}</p>
                {(!stage || stage === "portfolio_construction") && <p className="m-0">{t("python.targetReference")}</p>}
                {stage && <p className="m-0">{t("python.frameworkContext")}</p>}
                <p className="m-0">{t("python.state")}</p>
                <p className="m-0">{t("python.readLimits")}</p>
              </div>
            </div>
          </ResearchInfotip>
        </div>
        <div className="flex items-center gap-2">
          <Dialog>
            <DialogTrigger render={<Button type="button" variant="outline" size="sm" />}>{t("python.writingReference")}</DialogTrigger>
            <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-3xl">
              <DialogHeader><DialogTitle>{t("python.writingReference")}</DialogTitle></DialogHeader>
              <Suspense fallback={<p role="status">{commonText("loadingWorkspace")}</p>}><AuthoringReference initialTopic="python_sdk" /></Suspense>
            </DialogContent>
          </Dialog>
          {fieldsButton(() => editor.current)}
        </div>
      </div>
      {(active || opened) && <Suspense fallback={<p role="status" className="h-[280px] p-3 text-sm text-muted-foreground">{commonText("loadingWorkspace")}</p>}>
      <PythonSourceEditor editorRef={editor} id={id("source")} label={t("python.source")}
        describedBy={id("source-error")}
        source={inputs.programSource} error={sourceError} errorLine={errorLine}
        onChange={programSource => onChange({ programSource })} />
      </Suspense>}
      <FieldError id={id("source-error")}>{sourceError}</FieldError>
    </Field>
  </FieldGroup>;
}
