import type { TakeProfitField, TakeProfitTierDraft } from "./takeProfit";
import { useTranslation } from "../i18n";

export function TakeProfitAuthoring({ tiers, onChange, error }: {
  tiers: TakeProfitTierDraft[]; onChange: (tiers: TakeProfitTierDraft[]) => void;
  error: (field: TakeProfitField) => string | undefined;
}) {
  const { t } = useTranslation("strategy");
  return <section aria-label={t("takeProfit.title")} className="research-parameter-field take-profit-authoring">
    <h4>{t("takeProfit.title")}</h4>
    <p className="framework-module-help">{t("takeProfit.help")}</p>
    {tiers.map((tier, index) => <fieldset key={index}>
      <legend>{t("takeProfit.tier", { count: index + 1 })}</legend>
      {(["profitThreshold", "cumulativeReduction"] as const).map((key) => {
        const field: TakeProfitField = `takeProfitTiers.${index}.${key}`;
        const id = `take-profit-${index}-${key}`;
        const message = error(field);
        return <div key={key}>
          <label htmlFor={id}>{t(`takeProfit.${key}`)}</label>
          <input id={id} type="text" inputMode="decimal" maxLength={128} value={tier[key]}
            aria-invalid={Boolean(message)} aria-describedby={message ? `${id}-error` : undefined}
            onChange={event => onChange(tiers.map((row, rowIndex) => rowIndex === index ? { ...row, [key]: event.target.value } : row))} />
          {message && <p id={`${id}-error`} className="inline-status-error">{message}</p>}
        </div>;
      })}
      <button type="button" className="secondary-button" onClick={() => onChange(tiers.filter((_, row) => row !== index))}>{t("takeProfit.remove", { count: index + 1 })}</button>
    </fieldset>)}
    <button type="button" className="secondary-button" disabled={tiers.length >= 100}
      onClick={() => onChange([...tiers, { profitThreshold: "", cumulativeReduction: "" }])}>{t("takeProfit.add")}</button>
    <p className="framework-module-help">{t("takeProfit.footer")}</p>
  </section>;
}
