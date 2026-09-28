import type { ReactNode } from "react";
import type { ProgramInputs, ProgramInputField } from "./pythonStrategy";
import type { FrameworkStage } from "./frameworkModules";
import { useTranslation } from "../i18n";
import { Field, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { PythonSourceEditor } from "./PythonSourceEditor";
import { RuleDisclosure } from "./RuleDisclosure";
import { ResearchInfotip } from "./ResearchInfotip";

export function PythonStrategyAuthoring({ inputs, onChange, error, fieldsButton, stage, errorLine }: {
  inputs: ProgramInputs; onChange: (changes: Partial<ProgramInputs>) => void;
  error: (field: ProgramInputField) => string | undefined; fieldsButton: ReactNode;
  stage?: FrameworkStage; errorLine?: number | null;
}) {
  const { t } = useTranslation("strategy");
  const id = (suffix: string) => `${stage ? `${stage}-` : ""}python-${suffix}`;
  const sourceError = error("programSource");
  const parametersError = error("programParameters");
  const fieldsError = error("programFields");
  const historyError = error("programHistorySessions");
  return <FieldGroup className="min-w-0 gap-4">
    <Field data-invalid={Boolean(sourceError)}>
      <div className="flex items-center justify-between gap-3">
        <FieldLabel htmlFor={id("source")}>{t("python.source")}</FieldLabel>{fieldsButton}
      </div>
      <PythonSourceEditor id={id("source")} label={t("python.source")}
        describedBy={id("source-error")}
        source={inputs.programSource} error={sourceError} errorLine={errorLine}
        onChange={programSource => onChange({ programSource })} />
      <FieldError id={id("source-error")}>{sourceError}</FieldError>
    </Field>
    <RuleDisclosure title={t("workbench.programInputs")}
      description={t("workbench.programDataSummary", { fields: inputs.programFields.split(/[\s,]+/).filter(Boolean).length, days: inputs.programHistorySessions || "—" })}
      invalid={Boolean(fieldsError || historyError)}>
      <FieldGroup className="grid min-w-0 gap-4 @min-[560px]:grid-cols-[minmax(0,1fr)_160px]">
        <Field data-invalid={Boolean(fieldsError)}>
          <div className="flex items-center gap-1"><FieldLabel htmlFor={id("fields")}>{t("python.fields")}</FieldLabel><ResearchInfotip label={t("python.fields")}>{t("python.fieldsHelp")}</ResearchInfotip></div>
          <Textarea id={id("fields")} rows={2} spellCheck={false} className="font-mono" value={inputs.programFields}
            aria-invalid={Boolean(fieldsError)} aria-describedby={fieldsError ? id("fields-error") : undefined}
            onChange={event => onChange({ programFields: event.target.value })} />
          <FieldError id={id("fields-error")}>{fieldsError}</FieldError>
        </Field>
        <Field data-invalid={Boolean(historyError)}>
          <div className="flex items-center gap-1"><FieldLabel htmlFor={id("history")}>{t("python.history")}</FieldLabel><ResearchInfotip label={t("python.history")}>{t("python.historyHelp")}</ResearchInfotip></div>
          <Input id={id("history")} type="number" min={1} max={253} value={inputs.programHistorySessions}
            aria-invalid={Boolean(historyError)} aria-describedby={historyError ? id("history-error") : undefined}
            onChange={event => onChange({ programHistorySessions: event.target.value })} />
          <FieldError id={id("history-error")}>{historyError}</FieldError>
        </Field>
      </FieldGroup>
    </RuleDisclosure>
    <RuleDisclosure title={t("workbench.programParameters")} description={inputs.programParameters.trim() || "{}"} invalid={Boolean(parametersError)}>
      <Field data-invalid={Boolean(parametersError)}>
        <div className="flex items-center gap-1"><FieldLabel htmlFor={id("parameters")}>{t("python.parameters")}</FieldLabel><ResearchInfotip label={t("python.parameters")}>{t("workbench.programParametersHelp")}</ResearchInfotip></div>
        <Textarea id={id("parameters")} rows={3} spellCheck={false} className="font-mono" value={inputs.programParameters}
          aria-invalid={Boolean(parametersError)} aria-describedby={parametersError ? id("parameters-error") : undefined}
          onChange={event => onChange({ programParameters: event.target.value })} />
        <FieldError id={id("parameters-error")}>{parametersError}</FieldError>
      </Field>
    </RuleDisclosure>
    <RuleDisclosure title={t("workbench.programHelp")}>
      <div className="grid gap-3 text-sm text-muted-foreground">
        <code>{t("python.signature")}</code>
        <p className="m-0">{stage ? t(`python.framework.${stage}`) : t("python.directExample")}</p>
        <p className="m-0">{t("python.historyContext")}</p>
        <p className="m-0">{t("python.context", { noUpdate: '{"output": None, "state": state}', unit: t(stage ? "python.module" : "python.strategy") })}</p>
        {stage && <p className="m-0">{t("python.frameworkContext")}</p>}
        <p className="m-0">{t("python.state")}</p>
      </div>
    </RuleDisclosure>
  </FieldGroup>;
}
