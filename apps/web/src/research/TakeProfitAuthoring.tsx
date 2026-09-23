import type { TakeProfitField, TakeProfitTierDraft } from "./takeProfit";

export function TakeProfitAuthoring({ tiers, onChange, error }: {
  tiers: TakeProfitTierDraft[]; onChange: (tiers: TakeProfitTierDraft[]) => void;
  error: (field: TakeProfitField) => string | undefined;
}) {
  return <section aria-label="Cumulative take profit" className="research-parameter-field take-profit-authoring">
    <h4>Cumulative take profit</h4>
    <p className="framework-module-help">Off when no tiers are configured. At the first trigger, freeze the holding baseline. A 30% tier followed by 60% sells another 30% of that baseline, not 60% of the remaining shares. Ordinary selections cannot add shares until this holding fully exits.</p>
    {tiers.map((tier, index) => <fieldset key={index}>
      <legend>Tier {index + 1}</legend>
      {([ ["profitThreshold", "Profit threshold (%)"], ["cumulativeReduction", "Cumulative reduction (%)"] ] as const).map(([key, label]) => {
        const field: TakeProfitField = `takeProfitTiers.${index}.${key}`;
        const id = `take-profit-${index}-${key}`;
        const message = error(field);
        return <div key={key}>
          <label htmlFor={id}>{label}</label>
          <input id={id} type="text" inputMode="decimal" maxLength={128} value={tier[key]}
            aria-invalid={Boolean(message)} aria-describedby={message ? `${id}-error` : undefined}
            onChange={event => onChange(tiers.map((row, rowIndex) => rowIndex === index ? { ...row, [key]: event.target.value } : row))} />
          {message && <p id={`${id}-error`} className="inline-status-error">{message}</p>}
        </div>;
      })}
      <button type="button" className="secondary-button" onClick={() => onChange(tiers.filter((_, row) => row !== index))}>Remove tier {index + 1}</button>
    </fieldset>)}
    <button type="button" className="secondary-button" disabled={tiers.length >= 100}
      onClick={() => onChange([...tiers, { profitThreshold: "", cumulativeReduction: "" }])}>Add take-profit tier</button>
    <p className="framework-module-help">Both percentages must increase with each tier. Checks use acquisition cost at Close; fills at the following Open determine actual progress. Blocked sales and rounding remain uncompleted.</p>
  </section>;
}
