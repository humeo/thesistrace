import { costFields, type CostField, type SimulationCosts } from "./simulationCosts";
import { useTranslation } from "../i18n";
import { Field, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { ResearchInfotip } from "./ResearchInfotip";

export function SimulationCostSettings({ costs, onChange, error }: {
  costs: SimulationCosts;
  onChange: (costs: SimulationCosts) => void;
  error: (field: CostField) => string | undefined;
}) {
  const { t } = useTranslation("strategy");
  return <section className="grid min-w-0 gap-4" aria-label={t("cost.title")}>
    <div className="flex items-center gap-1"><h3 className="m-0 text-base font-semibold">{t("cost.title")}</h3>
      <ResearchInfotip label={t("cost.title")}>{t("cost.help")}</ResearchInfotip></div>
    <FieldGroup className="gap-4">
      {costFields.map(({ key }) => {
        const issue = error(key);
        return <Field key={key} data-invalid={Boolean(issue)}>
          <div className="flex items-center gap-1"><FieldLabel htmlFor={`cost-${key}`}>{t(`cost.labels.${key}`)}</FieldLabel><ResearchInfotip label={t(`cost.labels.${key}`)}>{t(`cost.helpText.${key}`)}</ResearchInfotip></div>
          <Input id={`cost-${key}`} type="text" inputMode="decimal" value={costs[key]}
            aria-invalid={Boolean(issue)} aria-describedby={issue ? `cost-${key}-error` : undefined}
            onChange={event => onChange({ ...costs, [key]: event.target.value })} />
          <FieldError id={`cost-${key}-error`}>{issue}</FieldError>
        </Field>;
      })}
    </FieldGroup>
  </section>;
}
