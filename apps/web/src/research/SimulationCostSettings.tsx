import { costFields, type CostField, type SimulationCosts } from "./simulationCosts";

export function SimulationCostSettings({ costs, onChange, error }: {
  costs: SimulationCosts;
  onChange: (costs: SimulationCosts) => void;
  error: (field: CostField) => string | undefined;
}) {
  return <section className="research-cost-settings" aria-label="Fees and slippage">
    <h3>Fees and slippage</h3>
    <p>Frozen for this backtest and its DailyTrack. Defaults are simulation assumptions; actual broker and historical charges may differ.</p>
    <div className="run-configuration-grid">
      {costFields.map(({ key, label, help }) => {
        const issue = error(key);
        return <div key={key} className="research-parameter-field">
          <label htmlFor={`cost-${key}`}>{label}</label>
          <input id={`cost-${key}`} type="text" inputMode="decimal" value={costs[key]}
            aria-invalid={Boolean(issue)} aria-describedby={`cost-${key}-help${issue ? ` cost-${key}-error` : ""}`}
            onChange={event => onChange({ ...costs, [key]: event.target.value })} />
          <small id={`cost-${key}-help`}>{help}</small>
          {issue && <small id={`cost-${key}-error`} className="inline-status-error">{issue}</small>}
        </div>;
      })}
    </div>
  </section>;
}
