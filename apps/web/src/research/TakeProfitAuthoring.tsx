import type { TakeProfitField, TakeProfitTierDraft } from "./takeProfit";
import { useTranslation } from "../i18n";
import { Button } from "../components/ui/button";
import { Field, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "../components/ui/field";
import { Input } from "../components/ui/input";

export function TakeProfitAuthoring({ tiers, onChange, error }: {
  tiers: TakeProfitTierDraft[]; onChange: (tiers: TakeProfitTierDraft[]) => void;
  error: (field: TakeProfitField) => string | undefined;
}) {
  const { t } = useTranslation("strategy");
  return <section aria-label={t("takeProfit.title")} className="grid gap-4">
    <h4 className="m-0 text-base font-semibold">{t("takeProfit.title")}</h4>
    <p className="m-0 text-sm text-muted-foreground">{t("takeProfit.help")}</p>
    {tiers.map((tier, index) => <FieldSet key={index} className="min-w-0 rounded-md border border-border p-4">
      <FieldLegend>{t("takeProfit.tier", { count: index + 1 })}</FieldLegend>
      <FieldGroup className="grid gap-4 @min-[560px]:grid-cols-2">
      {(["profitThreshold", "cumulativeReduction"] as const).map((key) => {
        const field: TakeProfitField = `takeProfitTiers.${index}.${key}`;
        const id = `take-profit-${index}-${key}`;
        const message = error(field);
        return <Field key={key} data-invalid={Boolean(message)}>
          <FieldLabel htmlFor={id}>{t(`takeProfit.${key}`)}</FieldLabel>
          <Input id={id} type="text" inputMode="decimal" maxLength={128} value={tier[key]}
            aria-invalid={Boolean(message)} aria-describedby={message ? `${id}-error` : undefined}
            onChange={event => onChange(tiers.map((row, rowIndex) => rowIndex === index ? { ...row, [key]: event.target.value } : row))} />
          <FieldError id={`${id}-error`}>{message}</FieldError>
        </Field>;
      })}
      </FieldGroup>
      <Button type="button" variant="outline" className="justify-self-start" onClick={() => onChange(tiers.filter((_, row) => row !== index))}>{t("takeProfit.remove", { count: index + 1 })}</Button>
    </FieldSet>)}
    <Button type="button" variant="outline" className="justify-self-start" disabled={tiers.length >= 100}
      onClick={() => onChange([...tiers, { profitThreshold: "", cumulativeReduction: "" }])}>{t("takeProfit.add")}</Button>
    <p className="m-0 text-sm text-muted-foreground">{t("takeProfit.footer")}</p>
  </section>;
}
