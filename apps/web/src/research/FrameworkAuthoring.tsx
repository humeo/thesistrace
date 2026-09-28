import { cn } from "cn";
import type { ReactNode } from "react";
import { Code } from "@phosphor-icons/react";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { useTranslation } from "../i18n";
import type { ResearchInputField } from "./draft";
import { frameworkStages, type FrameworkModulesDraft, type FrameworkStage } from "./frameworkModules";
import { PortfolioDrawdownAuthoring } from "./PortfolioDrawdownAuthoring";
import { drawdownFields, type DrawdownInputs } from "./portfolioDrawdown";
import { PythonStrategyAuthoring } from "./PythonStrategyAuthoring";
import type { ProgramInputs } from "./pythonStrategy";
import { TakeProfitAuthoring } from "./TakeProfitAuthoring";
import type { TakeProfitTierDraft } from "./takeProfit";
import { RuleDisclosure } from "./RuleDisclosure";

export function FrameworkAuthoring({ factor = false, drawdown, updateDrawdown, modules, selectModule, updateProgram,
  stopLossThreshold, updateStopLoss, maximumHoldingSessions, updateMaximumHoldingSessions,
  minimumHoldingSessions, updateMinimumHoldingSessions, takeProfitTiers, updateTakeProfitTiers,
  error, errorLine, fieldsButton, alphaEditor, portfolioSettings, universeSettings, neutralizationSettings }: {
  factor?: boolean;
  drawdown: DrawdownInputs; updateDrawdown: (changes: Partial<DrawdownInputs>) => void;
  modules: FrameworkModulesDraft;
  takeProfitTiers: TakeProfitTierDraft[];
  updateTakeProfitTiers: (tiers: TakeProfitTierDraft[]) => void;
  stopLossThreshold: string; updateStopLoss: (value: string) => void;
  maximumHoldingSessions: string; updateMaximumHoldingSessions: (value: string) => void;
  minimumHoldingSessions: string; updateMinimumHoldingSessions: (value: string) => void;
  selectModule: (stage: FrameworkStage, kind: "builtin" | "python") => void;
  updateProgram: (stage: FrameworkStage, changes: Partial<ProgramInputs>) => void;
  error: (field: ResearchInputField) => string | undefined;
  errorLine?: (stage: FrameworkStage) => number | null;
  fieldsButton: () => ReactNode;
  alphaEditor: ReactNode; portfolioSettings?: ReactNode; universeSettings?: ReactNode; neutralizationSettings?: ReactNode;
}) {
  const { t } = useTranslation("strategy");
  return <div className="grid min-w-0 gap-8">
    {frameworkStages.map((stage) => {
      const hidden = factor && stage !== "alpha";
      const python = !factor && modules[stage].kind === "python";
      return <section key={stage} hidden={hidden} aria-label={factor && stage === "alpha" ? undefined : t(`workbench.section.${stage}`)}
        className={cn("grid min-w-0 gap-4", !factor && "border-b border-border pb-8 last:border-b-0 last:pb-0", hidden && "hidden")}>
        {!factor && <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="m-0 text-base font-semibold">{t(`workbench.section.${stage}`)}</h2>
            <p className="mb-0 mt-1 text-sm text-muted-foreground">{t(`workbench.sectionHelp.${stage}`)}</p>
          </div>
          <Button variant="ghost" size="sm" type="button"
            aria-label={t(python ? "workbench.backToRule" : "workbench.customizeRule", { stage: t(`stages.${stage}`) })}
            onClick={() => selectModule(stage, python ? "builtin" : "python")}>
            <Code data-icon="inline-start" aria-hidden="true" />{t(python ? "workbench.configure" : "workbench.python")}
          </Button>
        </header>}
        {stage === "universe_selection" && universeSettings}
        <div hidden={!python} className={cn("min-w-0", !python && "hidden")}>
          <PythonStrategyAuthoring stage={stage} inputs={modules[stage].program}
            onChange={changes => updateProgram(stage, changes)} error={field => error(`${stage}.${field}`)}
            errorLine={errorLine?.(stage)} fieldsButton={fieldsButton()} />
        </div>
        <div hidden={python} className={cn("min-w-0", python && "hidden")}>
          {stage === "alpha" ? <div className="grid min-w-0 gap-4">{alphaEditor}{!factor && neutralizationSettings}</div>
            : stage === "portfolio_construction" ? <FieldGroup className="gap-4">
              {portfolioSettings}
              <RuleDisclosure title={t("workbench.minimumHolding")} description={t("workbench.minimumHoldingHelp")}
                configured={minimumHoldingSessions !== ""} invalid={Boolean(error("minimumHoldingSessions"))}>
                <PolicyInput id="minimum-holding-sessions" label={t("authoring.minimumHolding")} help={t("authoring.minimumHoldingHelp")}
                  value={minimumHoldingSessions} onChange={updateMinimumHoldingSessions} error={error("minimumHoldingSessions")} />
              </RuleDisclosure>
            </FieldGroup>
            : stage === "risk_management" ? <div className="grid gap-3">
              <RuleDisclosure title={t("workbench.basicRisk")} description={t("workbench.basicRiskHelp")}
                configured={stopLossThreshold !== "" || maximumHoldingSessions !== ""}
                invalid={Boolean(error("stopLossThreshold") || error("maximumHoldingSessions"))}>
                <FieldGroup className="grid gap-4 @min-[560px]:grid-cols-2">
                  <PolicyInput id="stop-loss-threshold" label={t("authoring.stopLoss")} help={t("authoring.stopLossHelp")}
                    inputMode="decimal" value={stopLossThreshold} onChange={updateStopLoss} error={error("stopLossThreshold")} />
                  <PolicyInput id="maximum-holding-sessions" label={t("authoring.maximumHolding")} help={t("authoring.maximumHoldingHelp")}
                    value={maximumHoldingSessions} onChange={updateMaximumHoldingSessions} error={error("maximumHoldingSessions")} />
                </FieldGroup>
              </RuleDisclosure>
              <RuleDisclosure title={t("workbench.profitRisk")} description={t("workbench.profitRiskHelp")} configured={takeProfitTiers.length > 0}
                invalid={takeProfitTiers.some((_, index) => Boolean(error(`takeProfitTiers.${index}.profitThreshold`) || error(`takeProfitTiers.${index}.cumulativeReduction`)))}>
                <TakeProfitAuthoring tiers={takeProfitTiers} onChange={updateTakeProfitTiers} error={error} />
              </RuleDisclosure>
              <RuleDisclosure title={t("workbench.drawdownRisk")} description={t("workbench.drawdownRiskHelp")}
                configured={drawdownFields.some(field => drawdown[field] !== "")} invalid={drawdownFields.some(field => Boolean(error(field)))}>
                <PortfolioDrawdownAuthoring values={drawdown} onChange={updateDrawdown} error={error} />
              </RuleDisclosure>
            </div> : null}
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
