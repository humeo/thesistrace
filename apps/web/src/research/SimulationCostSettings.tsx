import { costFields, type CostField, type SimulationCosts } from "./simulationCosts";
import { useTranslation } from "../i18n";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";

export function SimulationCostSettings({ costs, onChange, error }: {
  costs: SimulationCosts;
  onChange: (costs: SimulationCosts) => void;
  error: (field: CostField) => string | undefined;
}) {
  const { t } = useTranslation("strategy");
  return <section className="grid min-w-0 gap-4" aria-label={t("cost.title")}>
    <h3 className="m-0 text-base font-semibold">{t("cost.title")}</h3>
    <p className="m-0 text-sm text-muted-foreground">{t("cost.help")}</p>
    <FieldGroup className="gap-4">
      {costFields.map(({ key }) => {
        const issue = error(key);
        return <Field key={key} data-invalid={Boolean(issue)}>
          <FieldLabel htmlFor={`cost-${key}`}>{t(`cost.labels.${key}`)}</FieldLabel>
          <Input id={`cost-${key}`} type="text" inputMode="decimal" value={costs[key]}
            aria-invalid={Boolean(issue)} aria-describedby={`cost-${key}-help${issue ? ` cost-${key}-error` : ""}`}
            onChange={event => onChange({ ...costs, [key]: event.target.value })} />
          <FieldDescription id={`cost-${key}-help`}>{t(`cost.helpText.${key}`)}</FieldDescription>
          <FieldError id={`cost-${key}-error`}>{issue}</FieldError>
        </Field>;
      })}
    </FieldGroup>
  </section>;
}
