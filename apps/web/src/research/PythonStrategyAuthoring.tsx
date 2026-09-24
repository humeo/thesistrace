import type { ReactNode } from "react";

import type { ProgramInputs, ProgramInputField } from "./pythonStrategy";
import type { FrameworkStage } from "./frameworkModules";
import { useTranslation } from "../i18n";

export function PythonStrategyAuthoring({ inputs, onChange, error, fieldsButton, stage }: {
  inputs: ProgramInputs;
  onChange: (changes: Partial<ProgramInputs>) => void;
  error: (field: ProgramInputField) => string | undefined;
  fieldsButton: ReactNode;
  stage?: FrameworkStage;
}) {
  const { t } = useTranslation("strategy");
  const id = (suffix: string) => `${stage ? `${stage}-` : ""}python-${suffix}`;
  const sourceError = error("programSource");
  const parametersError = error("programParameters");
  const fieldsError = error("programFields");
  const historyError = error("programHistorySessions");
  return <div className="python-strategy-authoring">
    <div className="formula-workbench">
      <header className="formula-heading"><h2><label htmlFor={id("source")}>{t("python.source")}</label></h2>{fieldsButton}</header>
      <textarea id={id("source")} className="python-program-source" spellCheck={false} autoCapitalize="off" autoCorrect="off"
        aria-invalid={Boolean(sourceError)} aria-describedby={`${id("program-help")}${sourceError ? ` ${id("source-error")}` : ""}`}
        value={inputs.programSource} onChange={event => onChange({ programSource: event.target.value })} />
      <footer id={id("program-help")} className="formula-status">{t("python.signature")}</footer>
    </div>
    {sourceError && <small id={id("source-error")} className="inline-status-error">{sourceError}</small>}
    <div className="run-configuration-grid python-program-settings">
      <div className="research-parameter-field">
        <label htmlFor={id("parameters")}>{t("python.parameters")}</label>
        <textarea id={id("parameters")} rows={4} spellCheck={false} value={inputs.programParameters}
          aria-invalid={Boolean(parametersError)} aria-describedby={parametersError ? id("parameters-error") : undefined}
          onChange={event => onChange({ programParameters: event.target.value })} />
        {parametersError && <small id={id("parameters-error")} className="inline-status-error">{parametersError}</small>}
      </div>
      <div className="research-parameter-field">
        <label htmlFor={id("fields")}>{t("python.fields")}</label>
        <textarea id={id("fields")} rows={4} spellCheck={false} value={inputs.programFields}
          aria-invalid={Boolean(fieldsError)} aria-describedby={fieldsError ? id("fields-error") : undefined}
          onChange={event => onChange({ programFields: event.target.value })} />
        {fieldsError && <small id={id("fields-error")} className="inline-status-error">{fieldsError}</small>}
        <small>{t("python.fieldsHelp")}</small>
      </div>
      <div className="research-parameter-field">
        <label htmlFor={id("history")}>{t("python.history")}</label>
        <input id={id("history")} type="number" min={1} max={253} value={inputs.programHistorySessions}
          aria-invalid={Boolean(historyError)} aria-describedby={historyError ? id("history-error") : undefined}
          onChange={event => onChange({ programHistorySessions: event.target.value })} />
        {historyError && <small id={id("history-error")} className="inline-status-error">{historyError}</small>}
        <small>{t("python.historyHelp")}</small>
      </div>
    </div>
    <details className="research-notes python-program-contract"><summary>{t("python.contract")}</summary>
      <p>{stage ? t(`python.framework.${stage}`) : t("python.directExample")}</p>
      <p>{t("python.historyContext")}</p>
      <p>{t("python.context", { noUpdate: '{"output": None, "state": state}', unit: t(stage ? "python.module" : "python.strategy") })}</p>
      {stage && <p>{t("python.frameworkContext")}</p>}
      <p>{t("python.state")}</p>
    </details>
  </div>;
}
