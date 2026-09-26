import { cn } from "cn";
import type { ReactNode } from "react";

import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { useTranslation } from "../i18n";
import type { ResearchInputField } from "./draft";
import { frameworkStages, type FrameworkModulesDraft, type FrameworkStage } from "./frameworkModules";
import { PortfolioDrawdownAuthoring } from "./PortfolioDrawdownAuthoring";
import type { DrawdownInputs } from "./portfolioDrawdown";
import { PythonStrategyAuthoring } from "./PythonStrategyAuthoring";
import type { ProgramInputs } from "./pythonStrategy";
import { TakeProfitAuthoring } from "./TakeProfitAuthoring";
import type { TakeProfitTierDraft } from "./takeProfit";

/** Keeps each editor at a stable position while the selected authoring mode changes. */
export function FrameworkAuthoring({ factor = false, drawdown, updateDrawdown, modules, selectModule, updateProgram,
  stopLossThreshold, updateStopLoss, maximumHoldingSessions, updateMaximumHoldingSessions,
  minimumHoldingSessions, updateMinimumHoldingSessions, takeProfitTiers, updateTakeProfitTiers,
  error, errorLine, fieldsButton, alphaEditor, portfolioSettings }: {
  factor?: boolean;
  drawdown: DrawdownInputs; updateDrawdown: (changes: Partial<DrawdownInputs>) => void;
  modules: FrameworkModulesDraft;
  takeProfitTiers: TakeProfitTierDraft[];
  updateTakeProfitTiers: (tiers: TakeProfitTierDraft[]) => void;
  stopLossThreshold: string;
  updateStopLoss: (value: string) => void;
  maximumHoldingSessions: string;
  updateMaximumHoldingSessions: (value: string) => void;
  minimumHoldingSessions: string;
  updateMinimumHoldingSessions: (value: string) => void;
  selectModule: (stage: FrameworkStage, kind: "builtin" | "python") => void;
  updateProgram: (stage: FrameworkStage, changes: Partial<ProgramInputs>) => void;
  error: (field: ResearchInputField) => string | undefined;
  errorLine?: (stage: FrameworkStage) => number | null;
  fieldsButton: () => ReactNode;
  alphaEditor: ReactNode;
  portfolioSettings?: ReactNode;
}) {
  const { t } = useTranslation("strategy");
  return <div className="grid min-w-0 gap-6">
    {!factor && <p className="m-0 text-sm text-muted-foreground">{t("authoring.order")}</p>}
    {frameworkStages.map((stage, index) => {
      const hidden = factor && stage !== "alpha";
      const python = !factor && modules[stage].kind === "python";
      const label = t("authoring.module", { stage: t(`stages.${stage}`) });
      return <section key={stage} hidden={hidden} aria-label={factor && stage === "alpha" ? undefined : label}
        className={cn("grid min-w-0 gap-4", !factor && "rounded-lg border border-border bg-card p-4", hidden && "hidden")}>
        {!factor && <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="m-0 flex items-center gap-2 text-base font-semibold">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-secondary text-xs text-secondary-foreground">{index + 1}</span>
              {t(`stages.${stage}`)}
            </h3>
            <Field className="w-auto max-w-full">
              <FieldLabel className="sr-only" htmlFor={`module-${stage}`}>{label}</FieldLabel>
              <Select value={modules[stage].kind} onValueChange={kind => {
                if (kind === "builtin" || kind === "python") selectModule(stage, kind);
              }}>
                <SelectTrigger id={`module-${stage}`} className="w-full max-w-full">
                  <SelectValue>{python ? t("authoring.pythonModule") : t("authoring.builtin", { name: t(`builtin.${stage}`) })}</SelectValue>
                </SelectTrigger>
                <SelectContent><SelectGroup>
                  <SelectItem value="builtin">{t("authoring.builtin", { name: t(`builtin.${stage}`) })}</SelectItem>
                  <SelectItem value="python">{t("authoring.pythonModule")}</SelectItem>
                </SelectGroup></SelectContent>
              </Select>
            </Field>
          </div>
          <p className="m-0 text-sm text-muted-foreground">{t(`explanations.${stage}`)}</p>
        </>}
        <div hidden={!python} className={cn("min-w-0", !python && "hidden")}>
          <PythonStrategyAuthoring stage={stage} inputs={modules[stage].program}
            onChange={changes => updateProgram(stage, changes)} error={field => error(`${stage}.${field}`)}
            errorLine={errorLine?.(stage)} fieldsButton={fieldsButton()} />
        </div>
        <div hidden={python} className={cn("min-w-0", python && "hidden")}>
          {stage === "alpha" ? alphaEditor : stage === "risk_management" ? <FieldGroup className="gap-6">
            <PortfolioDrawdownAuthoring values={drawdown} onChange={updateDrawdown} error={error} />
            <TakeProfitAuthoring tiers={takeProfitTiers} onChange={updateTakeProfitTiers} error={error} />
            <PolicyInput id="stop-loss-threshold" label={t("authoring.stopLoss")} help={t("authoring.stopLossHelp")}
              inputMode="decimal" value={stopLossThreshold} onChange={updateStopLoss} error={error("stopLossThreshold")} />
            <PolicyInput id="maximum-holding-sessions" label={t("authoring.maximumHolding")} help={t("authoring.maximumHoldingHelp")}
              value={maximumHoldingSessions} onChange={updateMaximumHoldingSessions} error={error("maximumHoldingSessions")} />
          </FieldGroup> : stage === "portfolio_construction" ? <FieldGroup className="gap-6">
            {portfolioSettings}
            <PolicyInput id="minimum-holding-sessions" label={t("authoring.minimumHolding")} help={t("authoring.minimumHoldingHelp")}
              value={minimumHoldingSessions} onChange={updateMinimumHoldingSessions} error={error("minimumHoldingSessions")} />
          </FieldGroup> : null}
        </div>
      </section>;
    })}
  </div>;
}

function PolicyInput({ id, label, help, value, onChange, error, inputMode = "numeric" }: {
  id: string; label: string; help: string; value: string; onChange: (value: string) => void;
  error?: string; inputMode?: "numeric" | "decimal";
}) {
  const { t } = useTranslation("strategy");
  return <Field data-invalid={Boolean(error)}>
    <FieldLabel htmlFor={id}>{label}</FieldLabel>
    <Input id={id} type="text" inputMode={inputMode} placeholder={t("authoring.off")}
      maxLength={inputMode === "numeric" ? 16 : 128} value={value} onChange={event => onChange(event.target.value)}
      aria-invalid={Boolean(error)} aria-describedby={`${id}-help${error ? ` ${id}-error` : ""}`} />
    <FieldDescription id={`${id}-help`}>{help}</FieldDescription>
    <FieldError id={`${id}-error`}>{error}</FieldError>
  </Field>;
}
