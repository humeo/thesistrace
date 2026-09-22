import type { ReactNode } from "react";

import type { ResearchInputs, ResearchInputField } from "./draft";

export function PythonStrategyAuthoring({ inputs, onChange, error, fieldsButton }: {
  inputs: ResearchInputs;
  onChange: (changes: Partial<ResearchInputs>) => void;
  error: (field: ResearchInputField) => string | undefined;
  fieldsButton: ReactNode;
}) {
  const sourceError = error("programSource");
  const parametersError = error("programParameters");
  const fieldsError = error("programFields");
  const historyError = error("programHistorySessions");
  return <div className="python-strategy-authoring">
    <div className="formula-workbench">
      <header className="formula-heading"><h2><label htmlFor="python-source">Python source</label></h2>{fieldsButton}</header>
      <textarea id="python-source" className="python-program-source" spellCheck={false} autoCapitalize="off" autoCorrect="off"
        aria-invalid={Boolean(sourceError)} aria-describedby={`python-program-help${sourceError ? " python-source-error" : ""}`}
        value={inputs.programSource} onChange={event => onChange({ programSource: event.target.value })} />
      <footer id="python-program-help" className="formula-status">decide(context, state, parameters) → output and state</footer>
    </div>
    {sourceError && <small id="python-source-error" className="inline-status-error">{sourceError}</small>}
    <div className="run-configuration-grid python-program-settings">
      <div className="research-parameter-field">
        <label htmlFor="python-parameters">Parameters (JSON)</label>
        <textarea id="python-parameters" rows={4} spellCheck={false} value={inputs.programParameters}
          aria-invalid={Boolean(parametersError)} aria-describedby={parametersError ? "python-parameters-error" : undefined}
          onChange={event => onChange({ programParameters: event.target.value })} />
        {parametersError && <small id="python-parameters-error" className="inline-status-error">{parametersError}</small>}
      </div>
      <div className="research-parameter-field">
        <label htmlFor="python-fields">Declared fields</label>
        <textarea id="python-fields" rows={4} spellCheck={false} value={inputs.programFields}
          aria-invalid={Boolean(fieldsError)} aria-describedby={fieldsError ? "python-fields-error" : undefined}
          onChange={event => onChange({ programFields: event.target.value })} />
        {fieldsError && <small id="python-fields-error" className="inline-status-error">{fieldsError}</small>}
        <small>Canonical field IDs, separated by commas or new lines. Only declared fields are available to the program.</small>
      </div>
      <div className="research-parameter-field">
        <label htmlFor="python-history">History (trading sessions)</label>
        <input id="python-history" type="number" min={1} max={253} value={inputs.programHistorySessions}
          aria-invalid={Boolean(historyError)} aria-describedby={historyError ? "python-history-error" : undefined}
          onChange={event => onChange({ programHistorySessions: event.target.value })} />
        {historyError && <small id="python-history-error" className="inline-status-error">{historyError}</small>}
        <small>Includes the decision day. Earlier sessions provide warmup without moving the research start date.</small>
      </div>
    </div>
    <details className="research-notes python-program-contract"><summary>Python contract and example</summary>
      <p>The initial example replaces a holding only when another visible candidate has better momentum. Parameters set the required improvement.</p>
      <p><code>context.history</code> contains declared fields with rows in <code>instruments</code> order and columns in <code>sessions</code> order, through the current close. Missing values are <code>None</code>.</p>
      <p><code>context.candidates</code>, <code>context.account</code>, <code>context.fills</code> and <code>context.rejections</code> are read-only. Return <code>{'{"output": None, "state": state}'}</code> to keep holdings unchanged. A target contains <code>reason</code>, <code>allocation</code> and <code>position_limits</code>; weights use exact ratio strings such as <code>"1/2"</code>.</p>
      <p>State must be a JSON object and is restored explicitly each day. Source, parameters, data requirements and the execution environment are frozen when accepted. Execution uses the next trading session’s open.</p>
    </details>
  </div>;
}
