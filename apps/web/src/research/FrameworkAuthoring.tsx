import { cn } from "cn";
import type { ReactNode } from "react";
import { Code } from "@phosphor-icons/react";
import { Field, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { useTranslation } from "../i18n";
import type { ResearchInputField } from "./draft";
import { frameworkStages, type FrameworkModulesDraft, type FrameworkStage } from "./frameworkModules";
import { PortfolioDrawdownAuthoring } from "./PortfolioDrawdownAuthoring";
import { drawdownFields, type DrawdownInputs } from "./portfolioDrawdown";
import { PythonStrategyAuthoring, type PythonFieldsButton } from "./PythonStrategyAuthoring";
import type { ProgramInputs } from "./pythonStrategy";
import { TakeProfitAuthoring } from "./TakeProfitAuthoring";
import type { TakeProfitTierDraft } from "./takeProfit";
import { RuleDisclosure } from "./RuleDisclosure";
import { ResearchInfotip } from "./ResearchInfotip";

export function FrameworkAuthoring({ factor = false, drawdown, updateDrawdown, modules, selectModule, updateProgram,
  stopLossThreshold, updateStopLoss, maximumHoldingSessions, updateMaximumHoldingSessions,
  minimumHoldingSessions, updateMinimumHoldingSessions, takeProfitTiers, updateTakeProfitTiers,
  error, errorLine, fieldsButton, alphaEditor, portfolioSettings, universeSettings, neutralizationSettings,
  activeStage, onStageChange, stageSummaries }: {
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
  fieldsButton: PythonFieldsButton;
  alphaEditor: ReactNode; portfolioSettings?: ReactNode; universeSettings?: ReactNode; neutralizationSettings?: ReactNode;
  activeStage: FrameworkStage; onStageChange: (stage: FrameworkStage) => void;
  stageSummaries: Record<FrameworkStage, string>;
}) {
  const { t } = useTranslation("strategy");
  return <div className="grid min-w-0 gap-5">
    {!factor && <div role="tablist" aria-label={t("workbench.moduleNavigation")} className="research-stage-tabs">
      {frameworkStages.map((stage) => <Button key={stage} variant="ghost" type="button" role="tab"
        id={`research-stage-tab-${stage}`} aria-controls={`research-stage-panel-${stage}`}
        aria-selected={activeStage === stage} tabIndex={activeStage === stage ? 0 : -1}
        onClick={() => onStageChange(stage)}
        onKeyDown={event => {
          if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
          event.preventDefault();
          const offset = event.key === "ArrowRight" ? 1 : -1;
          const next = frameworkStages[(frameworkStages.indexOf(stage) + offset + frameworkStages.length) % frameworkStages.length];
          onStageChange(next);
          document.getElementById(`research-stage-tab-${next}`)?.focus();
        }}>
        <span className="research-stage-name">{t(`workbench.stageTab.${stage}`)}</span>
        <span className="research-stage-summary">{stageSummaries[stage]}</span>
      </Button>)}
    </div>}
    {frameworkStages.map((stage) => {
      const hidden = factor ? stage !== "alpha" : activeStage !== stage;
      const python = !factor && modules[stage].kind === "python";
      return <section key={stage} hidden={hidden} id={`research-stage-panel-${stage}`}
        role={factor ? undefined : "tabpanel"} aria-labelledby={factor ? undefined : `research-stage-tab-${stage}`}
        aria-label={factor && stage === "alpha" ? undefined : t(`workbench.stageHeading.${stage}`)}
        className={cn("research-stage-panel grid min-w-0 gap-5", hidden && "hidden")}>
        {!factor && <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-1">
            <h2 className="m-0 text-xl font-semibold">{t(`workbench.stageHeading.${stage}`)}</h2>
            <ResearchInfotip label={t(`workbench.stageHeading.${stage}`)}>{t(`workbench.sectionHelp.${stage}`)}</ResearchInfotip>
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
            errorLine={errorLine?.(stage)} fieldsButton={fieldsButton} />
        </div>
        <div hidden={python} className={cn("min-w-0", python && "hidden")}>
          {stage === "alpha" ? <div className="grid min-w-0 gap-4">{alphaEditor}{!factor && neutralizationSettings}</div>
            : stage === "portfolio_construction" ? <FieldGroup className="gap-4">
              {portfolioSettings}
              <RuleDisclosure title={t("workbench.minimumHolding")}
                configured={minimumHoldingSessions !== ""} invalid={Boolean(error("minimumHoldingSessions"))}>
                <PolicyInput id="minimum-holding-sessions" label={t("authoring.minimumHolding")} help={t("authoring.minimumHoldingHelp")}
                  value={minimumHoldingSessions} onChange={updateMinimumHoldingSessions} error={error("minimumHoldingSessions")} />
              </RuleDisclosure>
            </FieldGroup>
            : stage === "risk_management" ? <div className="grid gap-3">
              <RuleDisclosure title={t("workbench.basicRisk")}
                configured={stopLossThreshold !== "" || maximumHoldingSessions !== ""}
                invalid={Boolean(error("stopLossThreshold") || error("maximumHoldingSessions"))}>
                <FieldGroup className="grid gap-4 @min-[560px]:grid-cols-2">
                  <PolicyInput id="stop-loss-threshold" label={t("authoring.stopLoss")} help={t("authoring.stopLossHelp")}
                    inputMode="decimal" value={stopLossThreshold} onChange={updateStopLoss} error={error("stopLossThreshold")} />
                  <PolicyInput id="maximum-holding-sessions" label={t("authoring.maximumHolding")} help={t("authoring.maximumHoldingHelp")}
                    value={maximumHoldingSessions} onChange={updateMaximumHoldingSessions} error={error("maximumHoldingSessions")} />
                </FieldGroup>
              </RuleDisclosure>
              <RuleDisclosure title={t("workbench.profitRisk")} configured={takeProfitTiers.length > 0}
                invalid={takeProfitTiers.some((_, index) => Boolean(error(`takeProfitTiers.${index}.profitThreshold`) || error(`takeProfitTiers.${index}.cumulativeReduction`)))}>
                <TakeProfitAuthoring tiers={takeProfitTiers} onChange={updateTakeProfitTiers} error={error} />
              </RuleDisclosure>
              <RuleDisclosure title={t("workbench.drawdownRisk")}
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
    <div className="flex items-center gap-1"><FieldLabel htmlFor={id}>{label}</FieldLabel><ResearchInfotip label={label}>{help}</ResearchInfotip></div>
    <Input id={id} type="text" inputMode={inputMode} placeholder={t("authoring.off")}
      maxLength={inputMode === "numeric" ? 16 : 128} value={value} onChange={event => onChange(event.target.value)}
      aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} />
    <FieldError id={`${id}-error`}>{error}</FieldError>
  </Field>;
}
