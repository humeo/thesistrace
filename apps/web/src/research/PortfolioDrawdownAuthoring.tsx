import { drawdownFields, type DrawdownField, type DrawdownInputs } from "./portfolioDrawdown";

const labels: Record<DrawdownField, string> = {
  drawdownThreshold: "Drawdown threshold (%)", drawdownMaximumExposure: "Maximum stock exposure (%)",
  drawdownCooldownSessions: "Cooldown (trading sessions)",
};
export function PortfolioDrawdownAuthoring({ values, onChange, error }: {
  values: DrawdownInputs; onChange: (changes: Partial<DrawdownInputs>) => void;
  error: (field: DrawdownField) => string | undefined;
}) {
  return <section aria-label="Portfolio drawdown" className="research-parameter-field">
    <h4>Portfolio drawdown</h4>
    <p className="framework-module-help">Leave all three fields blank to disable. When enabled, complete every field. Close account value is compared with the current risk-cycle peak; the next Open applies the stock exposure cap.</p>
    {drawdownFields.map(field => {
      const id = `risk-${field}`, message = error(field);
      return <div key={field}>
        <label htmlFor={id}>{labels[field]}</label>
        <input id={id} type="text" inputMode={field === "drawdownCooldownSessions" ? "numeric" : "decimal"}
          maxLength={128} value={values[field]} onChange={event => onChange({ [field]: event.target.value })}
          aria-invalid={Boolean(message)} aria-describedby={message ? `${id}-error` : undefined} />
        {message && <p id={`${id}-error`} className="inline-status-error">{message}</p>}
      </div>;
    })}
    <p className="framework-module-help">Cooldown starts after the trigger day. Recovery also requires a new portfolio decision; it never buys back from an old target. The cap only reduces higher targets. Execution can be blocked, and the main Open performance history is not reset.</p>
  </section>;
}
