import { cn } from "cn";
import { useState, type ReactNode } from "react";
import type { AlphaCatalog } from "../alphaCatalog";
import { useTranslation } from "../i18n";
import { Field, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { readScoringRule, scoringRuleFormula, supportsScoringRules } from "./strategyRules";
import { ResearchInfotip } from "./ResearchInfotip";

export function StrategyScoringRule({ enabled = true, formula, onChange, catalog, error, children }: {
  enabled?: boolean; formula: string; onChange: (formula: string) => void; catalog: AlphaCatalog; error?: string; children: ReactNode;
}) {
  const { t } = useTranslation("strategy");
  const [custom, setCustom] = useState(formula !== "" && readScoringRule(formula) === null);
  const rule = readScoringRule(formula);
  const selected = custom ? "custom" : rule?.kind ?? (formula === "" ? "" : "custom");
  const supported = supportsScoringRules(catalog);
  const windowInvalid = Boolean(rule && (!Number.isInteger(Number(rule.sessions)) || Number(rule.sessions) < 1 || Number(rule.sessions) > 252));
  return <FieldGroup className="gap-4">
    <Field hidden={!enabled} className={cn(!enabled && "hidden")} data-invalid={Boolean(error)}>
      <FieldLabel htmlFor="scoring-rule">{t("workbench.rankBy")}</FieldLabel>
      <Select value={selected || null} onValueChange={value => {
        setCustom(value === "custom");
        if (value === "momentum" || value === "reversal") onChange(scoringRuleFormula({ kind: value, sessions: rule?.sessions || (value === "momentum" ? "20" : "5") }));
      }}>
        <SelectTrigger id="scoring-rule" aria-invalid={Boolean(error)} className="w-full">
          <SelectValue placeholder={t("workbench.chooseRule")}>{selected ? t(`workbench.scoring.${selected}`) : undefined}</SelectValue>
        </SelectTrigger>
        <SelectContent><SelectGroup>
          <SelectItem value="momentum" disabled={!supported}>{t("workbench.scoring.momentum")}</SelectItem>
          <SelectItem value="reversal" disabled={!supported}>{t("workbench.scoring.reversal")}</SelectItem>
          <SelectItem value="custom">{t("workbench.scoring.custom")}</SelectItem>
        </SelectGroup></SelectContent>
      </Select>
      {selected !== "custom" && <FieldError>{error}</FieldError>}
    </Field>
    {enabled && rule && selected !== "custom" && <Field data-invalid={windowInvalid || Boolean(error)}>
      <div className="flex items-center gap-1"><FieldLabel htmlFor="scoring-window">{t("workbench.lookback")}</FieldLabel>
        <ResearchInfotip label={t("workbench.lookback")}>{t(`workbench.scoringHelp.${rule.kind}`, { count: Number(rule.sessions) || 0 })}</ResearchInfotip></div>
      <Input id="scoring-window" className="max-w-40" type="number" min={1} max={252} step={1}
        value={rule.sessions} aria-invalid={windowInvalid || Boolean(error)}
        onChange={event => onChange(scoringRuleFormula({ ...rule, sessions: event.target.value }))} />
      <FieldError>{windowInvalid ? t("workbench.windowInvalid") : undefined}</FieldError>
    </Field>}
    <div id="scoring-custom-formula" hidden={enabled && selected !== "custom"} className={cn("min-w-0", enabled && selected !== "custom" && "hidden")}>{children}</div>
  </FieldGroup>;
}
