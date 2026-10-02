import type { TakeProfitField, TakeProfitTierDraft } from "./takeProfit";
import { useTranslation } from "../i18n";
import { Button } from "../components/ui/button";
import { Field, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "../components/ui/field";
import { ResearchNumberInput } from "./ResearchNumberInput";

export function TakeProfitAuthoring({ tiers, onChange, error }: {
  tiers: TakeProfitTierDraft[]; onChange: (tiers: TakeProfitTierDraft[]) => void;
  error: (field: TakeProfitField) => string | undefined;
}) {
  const { t } = useTranslation("strategy");
  return <FieldSet className="m-0 min-w-0 gap-4 border-0 p-0">
    <FieldLegend className="sr-only">{t("takeProfit.title")}</FieldLegend>
    {tiers.map((tier, index) => <FieldSet key={index} className="m-0 min-w-0 gap-3 border-0 p-0">
      <FieldLegend className="mb-0 w-full"><span className="flex items-center justify-between gap-4">
        <span>{t("takeProfit.tier", { count: index + 1 })}</span>
        <Button type="button" variant="ghost" size="xs" onClick={() => onChange(tiers.filter((_, row) => row !== index))}>{t("takeProfit.remove", { count: index + 1 })}</Button>
      </span></FieldLegend>
      <FieldGroup className="grid grid-cols-2 items-start gap-4">
      {(["profitThreshold", "cumulativeReduction"] as const).map((key) => {
        const field: TakeProfitField = `takeProfitTiers.${index}.${key}`;
        const id = `take-profit-${index}-${key}`;
        const message = error(field);
        return <Field key={key} data-invalid={Boolean(message)}>
          <FieldLabel htmlFor={id}>{t(`takeProfit.${key}`)}</FieldLabel>
          <ResearchNumberInput id={id} label={t(`takeProfit.${key}`)} percentage
            max={key === "cumulativeReduction" ? 100 : undefined} value={tier[key]} error={message}
            onChange={value => onChange(tiers.map((row, rowIndex) => rowIndex === index ? { ...row, [key]: value } : row))} />
          <FieldError id={`${id}-error`}>{message}</FieldError>
        </Field>;
      })}
      </FieldGroup>
    </FieldSet>)}
    <div className="flex items-center gap-1">
      <Button type="button" variant="outline" size="sm" disabled={tiers.length >= 100}
        onClick={() => onChange([...tiers, { profitThreshold: "", cumulativeReduction: "" }])}>{t("takeProfit.add")}</Button>
    </div>
  </FieldSet>;
}
