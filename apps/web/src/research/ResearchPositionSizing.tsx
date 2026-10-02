import { useState, type Ref } from "react";
import { cn } from "cn";
import type { AlphaCatalog } from "../alphaCatalog";
import { useTranslation } from "../i18n";
import { Trans } from "react-i18next";
import { ResearchParameterHelp } from "./ResearchParameterHelp";
import { Field, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { AlphaFormulaEditor, type AlphaFormulaEditorHandle } from "./AlphaFormulaEditor";
import type { FormulaDiagnostic } from "./diagnostics";
import { exposurePercentage, percentageExposure } from "./strategyRules";
import { ResearchInfotip } from "./ResearchInfotip";
import { ResearchCodeInput } from "./ResearchCodeInput";

export function ResearchPositionSizing({ ref, catalog, expression, diagnostics, onChange, error }: {
  ref: Ref<AlphaFormulaEditorHandle>; error?: string;
  catalog: AlphaCatalog; expression: string; diagnostics: FormulaDiagnostic[]; onChange: (expression: string) => void;
}) {
  const { t } = useTranslation("research");
  const { t: strategyT } = useTranslation("strategy");
  const [selection, setSelection] = useState({ anchor: 0, head: 0 });
  const [dynamic, setDynamic] = useState(exposurePercentage(expression) === null && expression !== "");
  return <FieldGroup className="grid grid-cols-2 items-start gap-4">
    <Field>
      <div className="flex items-center gap-1">
        <FieldLabel htmlFor="stock-exposure-mode">{strategyT("workbench.exposureMode")}</FieldLabel>
        <ResearchInfotip label={strategyT("workbench.exposureMode")}>{t("allocationExplanation")}</ResearchInfotip>
      </div>
      <Select value={dynamic ? "dynamic" : "fixed"} onValueChange={value => {
        setDynamic(value === "dynamic");
        if (value === "fixed" && exposurePercentage(expression) === null) onChange("1");
      }}>
        <SelectTrigger id="stock-exposure-mode" className="w-full"><SelectValue>{strategyT(dynamic ? "workbench.dynamicMode" : "workbench.fixedMode")}</SelectValue></SelectTrigger>
        <SelectContent><SelectGroup>
          <SelectItem value="fixed">{strategyT("workbench.fixedMode")}</SelectItem>
          <SelectItem value="dynamic">{strategyT("workbench.dynamicMode")}</SelectItem>
        </SelectGroup></SelectContent>
      </Select>
    </Field>
    {!dynamic && <Field data-invalid={Boolean(error)}>
      <div className="flex items-center gap-1"><FieldLabel htmlFor="stock-exposure-percent">{strategyT("workbench.fixedExposure")}</FieldLabel>
        <ResearchInfotip label={strategyT("workbench.fixedExposure")}>{strategyT("workbench.fixedHelp")}</ResearchInfotip></div>
      <Input id="stock-exposure-percent" className="max-w-40" type="number" min={0} max={100} step="any"
        value={expression === "" ? "" : exposurePercentage(expression) ?? ""}
        aria-invalid={Boolean(error)} aria-describedby={error ? "position-sizing-error" : undefined}
        onChange={event => onChange(percentageExposure(event.target.value))} />
    </Field>}
    <div hidden={!dynamic} className={cn("col-span-2 min-w-0", !dynamic && "hidden")}>
      <Field>
        <div className="flex items-center gap-2"><FieldLabel>{t("positionSizing")}</FieldLabel>
          <ResearchParameterHelp helpId="exposure" text={<span className="grid gap-3">
            <span>{t("positionSizingHelp")}</span>
            <span><strong>{t("fixedExposure")}</strong><Trans t={t} i18nKey="fixedExposureExample" components={{ code: <code /> }} /></span>
            <span><strong>{t("marketExposure")}</strong><code className="block whitespace-pre-wrap py-2 font-mono text-xs">{"if_else(universe_advancing_fraction() > 0.5, 1, 0.3)"}</code>{t("marketExposureExample")}</span>
            <span>{t("exposureRules")}</span>
          </span>} />
        </div>
        <ResearchCodeInput>
        <AlphaFormulaEditor ref={ref} error={error}
          catalog={catalog} context="exposure" diagnostics={diagnostics} formula={expression} selection={selection}
          onChange={(value, nextSelection) => { setSelection(nextSelection); onChange(value); }} />
        </ResearchCodeInput>
      </Field>
    </div>
    <FieldError id="position-sizing-error" className="col-span-2">{error}</FieldError>
  </FieldGroup>;
}
