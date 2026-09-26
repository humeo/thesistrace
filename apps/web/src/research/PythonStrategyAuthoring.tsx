import type { ReactNode } from "react";

import type { ProgramInputs, ProgramInputField } from "./pythonStrategy";
import type { FrameworkStage } from "./frameworkModules";
import { useTranslation } from "../i18n";
import { Button } from "../components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { PythonSourceEditor } from "./PythonSourceEditor";

export function PythonStrategyAuthoring({ inputs, onChange, error, errorLine, fieldsButton, stage }: {
  inputs: ProgramInputs;
  onChange: (changes: Partial<ProgramInputs>) => void;
  error: (field: ProgramInputField) => string | undefined;
  fieldsButton: ReactNode;
  stage?: FrameworkStage;
  errorLine?: number | null;
}) {
  const { t } = useTranslation("strategy");
  const id = (suffix: string) => `${stage ? `${stage}-` : ""}python-${suffix}`;
  const sourceError = error("programSource");
  const parametersError = error("programParameters");
  const fieldsError = error("programFields");
  const historyError = error("programHistorySessions");
  return <FieldGroup className="min-w-0 gap-6">
    <Field data-invalid={Boolean(sourceError)}>
      <div className="flex items-center justify-between gap-3">
        <FieldLabel htmlFor={id("source")}>{t("python.source")}</FieldLabel>{fieldsButton}
      </div>
      <PythonSourceEditor id={id("source")} label={t("python.source")}
        describedBy={`${id("program-help")}${sourceError ? ` ${id("source-error")}` : ""}`}
        source={inputs.programSource} error={sourceError} errorLine={errorLine}
        onChange={programSource => onChange({ programSource })} />
      <FieldDescription id={id("program-help")}>{t("python.signature")}</FieldDescription>
      <FieldError id={id("source-error")}>{sourceError}</FieldError>
    </Field>
    <FieldGroup className="grid min-w-0 gap-4 @min-[560px]:grid-cols-2">
      <Field data-invalid={Boolean(parametersError)}>
        <FieldLabel htmlFor={id("parameters")}>{t("python.parameters")}</FieldLabel>
        <Textarea id={id("parameters")} rows={4} spellCheck={false} className="font-mono" value={inputs.programParameters}
          aria-invalid={Boolean(parametersError)} aria-describedby={parametersError ? id("parameters-error") : undefined}
          onChange={event => onChange({ programParameters: event.target.value })} />
        <FieldError id={id("parameters-error")}>{parametersError}</FieldError>
      </Field>
      <Field data-invalid={Boolean(fieldsError)}>
        <FieldLabel htmlFor={id("fields")}>{t("python.fields")}</FieldLabel>
        <Textarea id={id("fields")} rows={4} spellCheck={false} className="font-mono" value={inputs.programFields}
          aria-invalid={Boolean(fieldsError)} aria-describedby={fieldsError ? id("fields-error") : undefined}
          onChange={event => onChange({ programFields: event.target.value })} />
        <FieldError id={id("fields-error")}>{fieldsError}</FieldError>
        <FieldDescription>{t("python.fieldsHelp")}</FieldDescription>
      </Field>
      <Field data-invalid={Boolean(historyError)}>
        <FieldLabel htmlFor={id("history")}>{t("python.history")}</FieldLabel>
        <Input id={id("history")} type="number" min={1} max={253} value={inputs.programHistorySessions}
          aria-invalid={Boolean(historyError)} aria-describedby={historyError ? id("history-error") : undefined}
          onChange={event => onChange({ programHistorySessions: event.target.value })} />
        <FieldError id={id("history-error")}>{historyError}</FieldError>
        <FieldDescription>{t("python.historyHelp")}</FieldDescription>
      </Field>
    </FieldGroup>
    <Collapsible>
      <CollapsibleTrigger render={<Button variant="ghost" className="justify-start px-0" />}>{t("python.contract")}</CollapsibleTrigger>
      <CollapsibleContent keepMounted className="text-sm text-muted-foreground">
      <p>{stage ? t(`python.framework.${stage}`) : t("python.directExample")}</p>
      <p>{t("python.historyContext")}</p>
      <p>{t("python.context", { noUpdate: '{"output": None, "state": state}', unit: t(stage ? "python.module" : "python.strategy") })}</p>
      {stage && <p>{t("python.frameworkContext")}</p>}
      <p>{t("python.state")}</p>
      </CollapsibleContent>
    </Collapsible>
  </FieldGroup>;
}
