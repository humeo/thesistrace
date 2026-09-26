import { drawdownFields, type DrawdownField, type DrawdownInputs } from "./portfolioDrawdown";
import { useTranslation } from "../i18n";
import { Field, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";
export function PortfolioDrawdownAuthoring({ values, onChange, error }: {
  values: DrawdownInputs; onChange: (changes: Partial<DrawdownInputs>) => void;
  error: (field: DrawdownField) => string | undefined;
}) {
  const { t } = useTranslation("strategy");
  return <section aria-label={t("drawdown.title")} className="grid gap-4">
    <h4 className="m-0 text-base font-semibold">{t("drawdown.title")}</h4>
    <p className="m-0 text-sm text-muted-foreground">{t("drawdown.help")}</p>
    <FieldGroup className="grid gap-4 @min-[560px]:grid-cols-3">
    {drawdownFields.map(field => {
      const id = `risk-${field}`, message = error(field);
      return <Field key={field} data-invalid={Boolean(message)}>
        <FieldLabel htmlFor={id}>{t(`drawdown.labels.${field}`)}</FieldLabel>
        <Input id={id} type="text" inputMode={field === "drawdownCooldownSessions" ? "numeric" : "decimal"}
          maxLength={128} value={values[field]} onChange={event => onChange({ [field]: event.target.value })}
          aria-invalid={Boolean(message)} aria-describedby={message ? `${id}-error` : undefined} />
        <FieldError id={`${id}-error`}>{message}</FieldError>
      </Field>;
    })}
    </FieldGroup>
    <p className="m-0 text-sm text-muted-foreground">{t("drawdown.recovery")}</p>
  </section>;
}
