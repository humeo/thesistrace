import { cn } from "cn";
import { useEffect, useState } from "react";
import { CaretDown } from "@phosphor-icons/react";
import { costFields, type CostField, type SimulationCosts } from "./simulationCosts";
import { useTranslation } from "../i18n";
import { Field, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { ResearchInfotip } from "./ResearchInfotip";

export function SimulationCostSettings({ costs, onChange, error }: {
  costs: SimulationCosts;
  onChange: (costs: SimulationCosts) => void;
  error: (field: CostField) => string | undefined;
}) {
  const { t } = useTranslation("strategy");
  const [open, setOpen] = useState(false);
  const invalid = costFields.some(({ key }) => Boolean(error(key)));
  const expanded = open || invalid;
  useEffect(() => { if (invalid) setOpen(true); }, [invalid]);
  function costField(key: CostField, paired = true) {
    const issue = error(key);
    return <Field key={key} data-invalid={Boolean(issue)} className={cn(paired && "row-span-3 grid grid-rows-subgrid gap-2")}>
      <div className="flex items-start gap-1">
        <FieldLabel htmlFor={`cost-${key}`}>{t(`cost.compactLabels.${key}`)}</FieldLabel>
        <ResearchInfotip label={t(`cost.labels.${key}`)}>{t(`cost.helpText.${key}`)}</ResearchInfotip>
      </div>
      <Input id={`cost-${key}`} type="text" inputMode="decimal" value={costs[key]} aria-label={t(`cost.labels.${key}`)}
        className={cn(!paired && "max-w-[160px]")}
        aria-invalid={Boolean(issue)} aria-describedby={issue ? `cost-${key}-error` : undefined}
        onChange={event => onChange({ ...costs, [key]: event.target.value })} />
      <FieldError id={`cost-${key}-error`}>{issue}</FieldError>
    </Field>;
  }
  return <section className="min-w-0" aria-label={t("cost.title")}>
    <Collapsible open={expanded} onOpenChange={setOpen}>
    <div className="flex items-center gap-1"><h3 className="m-0 min-w-0 flex-1">
      <CollapsibleTrigger render={<Button variant="ghost" className="h-auto min-h-10 w-full justify-between px-0 text-left text-base font-semibold" />}>
        {t("cost.title")}<CaretDown aria-hidden="true" className={cn("transition-transform", expanded && "rotate-180")} />
      </CollapsibleTrigger>
    </h3>
      <ResearchInfotip label={t("cost.title")}>{t("cost.help")}</ResearchInfotip></div>
    <CollapsibleContent keepMounted className="pt-4">
    <FieldGroup className="gap-4">
      <FieldSet className="m-0 min-w-0 gap-2 border-0 p-0">
        <FieldLegend className="sr-only">{t("cost.groups.commission")}</FieldLegend>
        <FieldGroup className="grid grid-cols-2 items-start gap-x-3 gap-y-2">
          {costField("commission_rate_all_in")}
          {costField("commission_min_cny")}
        </FieldGroup>
      </FieldSet>
      <FieldSet className="m-0 min-w-0 gap-2 border-0 p-0">
        <FieldLegend className="sr-only">{t("cost.groups.taxes")}</FieldLegend>
        <FieldGroup className="grid grid-cols-2 items-start gap-x-3 gap-y-2">
          {costField("stamp_duty_sell_rate")}
          {costField("transfer_fee_rate")}
        </FieldGroup>
      </FieldSet>
      {costField("slippage_bps", false)}
    </FieldGroup>
    </CollapsibleContent>
    </Collapsible>
  </section>;
}
