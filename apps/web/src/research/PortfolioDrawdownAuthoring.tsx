import { drawdownFields, type DrawdownField, type DrawdownInputs } from "./portfolioDrawdown";
import { useTranslation } from "../i18n";
import { Field, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "../components/ui/field";
import { ResearchNumberInput } from "./ResearchNumberInput";
export function PortfolioDrawdownAuthoring({ values, onChange, error }: {
  values: DrawdownInputs; onChange: (changes: Partial<DrawdownInputs>) => void;
  error: (field: DrawdownField) => string | undefined;
}) {
  const { t } = useTranslation("strategy");
  return <FieldSet className="m-0 min-w-0 gap-4 border-0 p-0">
    <FieldLegend className="sr-only">{t("drawdown.title")}</FieldLegend>
    <FieldGroup className="grid grid-cols-2 items-start gap-4">
    {drawdownFields.map(field => {
      const id = `risk-${field}`, message = error(field);
      return <Field key={field} data-invalid={Boolean(message)} className="row-span-3 grid grid-rows-subgrid gap-2">
        <div className="flex items-center gap-1">
          <FieldLabel htmlFor={id}>{t(`drawdown.labels.${field}`)}</FieldLabel>
        </div>
        <ResearchNumberInput id={id} label={t(`drawdown.labels.${field}`)} percentage={field !== "drawdownCooldownSessions"}
          min={field === "drawdownCooldownSessions" ? 1 : 0} max={field === "drawdownCooldownSessions" ? undefined : 100}
          value={values[field]} onChange={value => onChange({ [field]: value })} error={message} />
        <FieldError id={`${id}-error`}>{message}</FieldError>
      </Field>;
    })}
    </FieldGroup>
  </FieldSet>;
}
