import { costFields, type CostField, type SimulationCosts } from "./simulationCosts";
import { useTranslation } from "../i18n";

export function SimulationCostSettings({ costs, onChange, error }: {
  costs: SimulationCosts;
  onChange: (costs: SimulationCosts) => void;
  error: (field: CostField) => string | undefined;
}) {
  const { t } = useTranslation("strategy");
  return <section className="research-cost-settings" aria-label={t("cost.title")}>
    <h3>{t("cost.title")}</h3>
    <p>{t("cost.help")}</p>
    <div className="run-configuration-grid">
      {costFields.map(({ key }) => {
        const issue = error(key);
        return <div key={key} className="research-parameter-field">
          <label htmlFor={`cost-${key}`}>{t(`cost.labels.${key}`)}</label>
          <input id={`cost-${key}`} type="text" inputMode="decimal" value={costs[key]}
            aria-invalid={Boolean(issue)} aria-describedby={`cost-${key}-help${issue ? ` cost-${key}-error` : ""}`}
            onChange={event => onChange({ ...costs, [key]: event.target.value })} />
          <small id={`cost-${key}-help`}>{t(`cost.helpText.${key}`)}</small>
          {issue && <small id={`cost-${key}-error`} className="inline-status-error">{issue}</small>}
        </div>;
      })}
    </div>
  </section>;
}
