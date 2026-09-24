import { drawdownFields, type DrawdownField, type DrawdownInputs } from "./portfolioDrawdown";
import { useTranslation } from "../i18n";
export function PortfolioDrawdownAuthoring({ values, onChange, error }: {
  values: DrawdownInputs; onChange: (changes: Partial<DrawdownInputs>) => void;
  error: (field: DrawdownField) => string | undefined;
}) {
  const { t } = useTranslation("strategy");
  return <section aria-label={t("drawdown.title")} className="research-parameter-field">
    <h4>{t("drawdown.title")}</h4>
    <p className="framework-module-help">{t("drawdown.help")}</p>
    {drawdownFields.map(field => {
      const id = `risk-${field}`, message = error(field);
      return <div key={field}>
        <label htmlFor={id}>{t(`drawdown.labels.${field}`)}</label>
        <input id={id} type="text" inputMode={field === "drawdownCooldownSessions" ? "numeric" : "decimal"}
          maxLength={128} value={values[field]} onChange={event => onChange({ [field]: event.target.value })}
          aria-invalid={Boolean(message)} aria-describedby={message ? `${id}-error` : undefined} />
        {message && <p id={`${id}-error`} className="inline-status-error">{message}</p>}
      </div>;
    })}
    <p className="framework-module-help">{t("drawdown.recovery")}</p>
  </section>;
}
