import { useRef, type ReactNode } from "react";
import type { ProgramInputs, ProgramInputField } from "./pythonStrategy";
import type { FrameworkStage } from "./frameworkModules";
import { useTranslation } from "../i18n";
import { Field, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { PythonSourceEditor, type PythonSourceEditorHandle } from "./PythonSourceEditor";
import { ResearchInfotip } from "./ResearchInfotip";

export type PythonFieldsButton = (editor: () => PythonSourceEditorHandle | null) => ReactNode;

export function PythonStrategyAuthoring({ inputs, onChange, error, fieldsButton, stage, errorLine }: {
  inputs: ProgramInputs; onChange: (changes: Partial<ProgramInputs>) => void;
  error: (field: ProgramInputField) => string | undefined; fieldsButton: PythonFieldsButton;
  stage?: FrameworkStage; errorLine?: number | null;
}) {
  const { t } = useTranslation("strategy");
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
        <div className="flex items-center gap-2">{fieldsButton(() => editor.current)}</div>
      </div>
      <PythonSourceEditor editorRef={editor} id={id("source")} label={t("python.source")}
        describedBy={id("source-error")}
        source={inputs.programSource} error={sourceError} errorLine={errorLine}
        onChange={programSource => onChange({ programSource })} />
      <FieldError id={id("source-error")}>{sourceError}</FieldError>
    </Field>
  </FieldGroup>;
}
