import type { ReactNode } from "react";

import type { ProgramInputs, ProgramInputField } from "./pythonStrategy";
import type { FrameworkStage } from "./frameworkModules";

export function PythonStrategyAuthoring({ inputs, onChange, error, fieldsButton, stage }: {
  inputs: ProgramInputs;
  onChange: (changes: Partial<ProgramInputs>) => void;
  error: (field: ProgramInputField) => string | undefined;
  fieldsButton: ReactNode;
  stage?: FrameworkStage;
}) {
  const id = (suffix: string) => `${stage ? `${stage}-` : ""}python-${suffix}`;
  const sourceError = error("programSource");
  const parametersError = error("programParameters");
  const fieldsError = error("programFields");
  const historyError = error("programHistorySessions");
  return <div className="python-strategy-authoring">
    <div className="formula-workbench">
      <header className="formula-heading"><h2><label htmlFor={id("source")}>Python source</label></h2>{fieldsButton}</header>
      <textarea id={id("source")} className="python-program-source" spellCheck={false} autoCapitalize="off" autoCorrect="off"
        aria-invalid={Boolean(sourceError)} aria-describedby={`${id("program-help")}${sourceError ? ` ${id("source-error")}` : ""}`}
        value={inputs.programSource} onChange={event => onChange({ programSource: event.target.value })} />
      <footer id={id("program-help")} className="formula-status">decide(context, state, parameters) → output and state</footer>
    </div>
    {sourceError && <small id={id("source-error")} className="inline-status-error">{sourceError}</small>}
    <div className="run-configuration-grid python-program-settings">
      <div className="research-parameter-field">
        <label htmlFor={id("parameters")}>Parameters (JSON)</label>
        <textarea id={id("parameters")} rows={4} spellCheck={false} value={inputs.programParameters}
          aria-invalid={Boolean(parametersError)} aria-describedby={parametersError ? id("parameters-error") : undefined}
          onChange={event => onChange({ programParameters: event.target.value })} />
        {parametersError && <small id={id("parameters-error")} className="inline-status-error">{parametersError}</small>}
      </div>
      <div className="research-parameter-field">
        <label htmlFor={id("fields")}>Declared fields</label>
        <textarea id={id("fields")} rows={4} spellCheck={false} value={inputs.programFields}
          aria-invalid={Boolean(fieldsError)} aria-describedby={fieldsError ? id("fields-error") : undefined}
          onChange={event => onChange({ programFields: event.target.value })} />
        {fieldsError && <small id={id("fields-error")} className="inline-status-error">{fieldsError}</small>}
        <small>Canonical field IDs, separated by commas or new lines. Only declared fields are available to the program.</small>
      </div>
      <div className="research-parameter-field">
        <label htmlFor={id("history")}>History (trading sessions)</label>
        <input id={id("history")} type="number" min={1} max={253} value={inputs.programHistorySessions}
          aria-invalid={Boolean(historyError)} aria-describedby={historyError ? id("history-error") : undefined}
          onChange={event => onChange({ programHistorySessions: event.target.value })} />
        {historyError && <small id={id("history-error")} className="inline-status-error">{historyError}</small>}
        <small>Includes the decision day. Earlier sessions provide warmup without moving the research start date.</small>
      </div>
    </div>
    <details className="research-notes python-program-contract"><summary>Python contract and example</summary>
      <p>{stage ? frameworkContracts[stage] : "The initial example replaces a holding only when another visible candidate has better momentum. Parameters set the required improvement."}</p>
      <p><code>context.history</code> contains declared fields with rows in <code>instruments</code> order and columns in <code>sessions</code> order, through the current close. Missing values are <code>None</code>.</p>
      <p><code>context.candidates</code>, <code>context.account</code>, <code>context.fills</code> and <code>context.rejections</code> are read-only. Return <code>{'{"output": None, "state": state}'}</code> for no update from this {stage ? "module" : "strategy"}. A target contains <code>reason</code>, <code>allocation</code> and <code>position_limits</code>; weights use exact ratio strings such as <code>"1/2"</code>.</p>
      {stage && <p><code>context.framework</code> contains the selected <code>universe</code>, active <code>signals</code>, <code>universe_changed</code>, <code>signals_updated</code>, <code>expired_signals</code>, <code>removed_signals</code>, this Close’s <code>proposal</code> and the last <code>retained_proposal</code>. A retained proposal is a reference, not a new order.</p>}
      <p>State must be a JSON object and is restored explicitly each day. Source, parameters, data requirements and the execution environment are frozen when accepted. Execution uses the next trading session’s open.</p>
    </details>
  </div>;
}

const frameworkContracts: Record<FrameworkStage, string> = {
  universe_selection: 'Return {reason, instrument_ids} to select available Dataset candidates. None retains the previous available selection, initially empty. The example includes all current candidates.',
  alpha: 'Return {reason, signals}. Each signal has instrument_id, value and valid_for_sessions (1–252). The host stamps its creation session. None retains unexpired signals. Expiry does not itself sell a holding. The example publishes six-session momentum signals.',
  portfolio_construction: 'Return a target or None. The example buys a better-scoring candidate only when the improvement threshold is met, using current holdings and active signals. No update leaves holdings and drift unchanged.',
  risk_management: 'Runs every Close, even without a new proposal. Return {mode: "limit_positions", reason, position_limits} to cap held shares; unspecified positions keep their shares when there is no proposal. Return {mode: "replace", reason, target} to replace the proposal, or target: None to cancel it. None leaves the new proposal unchanged. The example exits only symbols listed in exit_instruments; an empty list makes no adjustment.',
};
