import { cn } from "cn";
import type { ReactNode } from "react";
import { Field, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "../components/ui/field";
import { Badge } from "../components/ui/badge";
import { ResearchNumberInput } from "./ResearchNumberInput";
import { RadioGroup, RadioGroupItem } from "../components/ui/radio-group";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useTranslation } from "../i18n";
import type { ResearchInputField } from "./draft";
import { frameworkStages, type FrameworkModulesDraft, type FrameworkStage } from "./frameworkModules";
import { PortfolioDrawdownAuthoring } from "./PortfolioDrawdownAuthoring";
import type { DrawdownInputs } from "./portfolioDrawdown";
import { PythonStrategyAuthoring, type PythonFieldsButton } from "./PythonStrategyAuthoring";
import type { ProgramInputs } from "./pythonStrategy";
import { TakeProfitAuthoring } from "./TakeProfitAuthoring";
import type { TakeProfitTierDraft } from "./takeProfit";
import { ResearchInfotip } from "./ResearchInfotip";
import { RiskPolicyField } from "./RiskPolicyField";
import type { RiskPolicy } from "./riskPolicies";

export function FrameworkAuthoring({ factor = false, drawdown, updateDrawdown, modules, selectModule, updateProgram,
  stopLossThreshold, updateStopLoss, maximumHoldingSessions, updateMaximumHoldingSessions,
  minimumHoldingSessions, updateMinimumHoldingSessions, takeProfitTiers, updateTakeProfitTiers,
  error, errorLine, fieldsButton, alphaEditor, portfolioSettings, universeSettings, neutralizationSettings,
  activeStage, onStageChange, stageIssues, riskPolicyEnabled, selectRiskPolicy }: {
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
  alphaEditor: ReactNode; portfolioSettings: (minimumHoldingInput: ReactNode) => ReactNode; universeSettings?: ReactNode; neutralizationSettings?: ReactNode;
  activeStage: FrameworkStage; onStageChange: (stage: FrameworkStage) => void;
  stageIssues?: Partial<Record<FrameworkStage, number>>;
  riskPolicyEnabled: (policy: RiskPolicy) => boolean;
  selectRiskPolicy: (policy: RiskPolicy, enabled: boolean) => void;
}) {
  const { t } = useTranslation("strategy");
  const panels = frameworkStages.map((stage) => {
    const python = !factor && modules[stage].kind === "python";
    const modeLabel = t("workbench.stageMode", { stage: t(`workbench.stageHeading.${stage}`) });
    const codeEditor = <PythonStrategyAuthoring stage={stage} inputs={modules[stage].program}
      onChange={changes => updateProgram(stage, changes)} error={field => error(`${stage}.${field}`)}
      errorLine={errorLine?.(stage)} fieldsButton={fieldsButton} />;
    const configuredContents = stage === "alpha" ? <div className="grid min-w-0 gap-4">{alphaEditor}{!factor && neutralizationSettings}</div>
      : stage === "portfolio_construction" ? portfolioSettings(
        <PolicyInput id="minimum-holding-sessions" label={t("authoring.minimumHolding")} help={t("authoring.minimumHoldingHelp")}
          value={minimumHoldingSessions} onChange={updateMinimumHoldingSessions} error={error("minimumHoldingSessions")} />
      )
      : stage === "risk_management" ? <FieldGroup className="max-w-[640px] gap-4">
        <RiskPolicyField policy="stopLoss" title={t("riskPolicies.stopLoss")} help={t("authoring.stopLossHelp")}
          enabled={riskPolicyEnabled("stopLoss")} onChange={enabled => selectRiskPolicy("stopLoss", enabled)}>
          <PolicyInput id="stop-loss-threshold" label={t("authoring.stopLoss")}
            inputMode="decimal" value={stopLossThreshold} onChange={updateStopLoss} error={error("stopLossThreshold")} />
        </RiskPolicyField>
        <RiskPolicyField policy="maximumHolding" title={t("riskPolicies.maximumHolding")} help={t("authoring.maximumHoldingHelp")}
          enabled={riskPolicyEnabled("maximumHolding")} onChange={enabled => selectRiskPolicy("maximumHolding", enabled)}>
          <PolicyInput id="maximum-holding-sessions" label={t("authoring.maximumHolding")}
            value={maximumHoldingSessions} onChange={updateMaximumHoldingSessions} error={error("maximumHoldingSessions")} />
        </RiskPolicyField>
        <RiskPolicyField policy="takeProfit" title={t("takeProfit.title")} help={<span className="grid gap-2"><span>{t("takeProfit.help")}</span><span>{t("takeProfit.footer")}</span></span>}
          enabled={riskPolicyEnabled("takeProfit")} onChange={enabled => selectRiskPolicy("takeProfit", enabled)}>
          <TakeProfitAuthoring tiers={takeProfitTiers} onChange={updateTakeProfitTiers} error={error} />
        </RiskPolicyField>
        <RiskPolicyField policy="drawdown" title={t("riskPolicies.drawdown")} help={<span className="grid gap-2"><span>{t("drawdown.help")}</span><span>{t("drawdown.recovery")}</span></span>}
          enabled={riskPolicyEnabled("drawdown")} onChange={enabled => selectRiskPolicy("drawdown", enabled)}>
          <PortfolioDrawdownAuthoring values={drawdown} onChange={updateDrawdown} error={error} />
        </RiskPolicyField>
      </FieldGroup> : null;
    return <TabsContent key={stage} value={stage} keepMounted render={<section />} id={`research-stage-panel-${stage}`}
      role={factor ? "group" : "tabpanel"} aria-label={factor ? t(`stages.${stage}`) : undefined}
      className="research-stage-panel grid min-w-0 content-start gap-4">
        {stage === "universe_selection" && universeSettings}
        {!factor && <FieldSet className="m-0 min-w-0 flex-row items-center gap-1 border-0 p-0">
          <FieldLegend className="sr-only">{modeLabel}</FieldLegend>
          <RadioGroup aria-label={modeLabel} className="flex w-auto flex-wrap gap-6" value={modules[stage].kind}
            onValueChange={kind => {
              if (kind === "builtin" || kind === "python") selectModule(stage, kind);
            }}>
            <Field orientation="horizontal" className="w-auto">
              <RadioGroupItem id={`research-${stage}-configure`} value="builtin" />
              <FieldLabel htmlFor={`research-${stage}-configure`} className="min-h-9 cursor-pointer items-center">{t("workbench.formMode")}</FieldLabel>
            </Field>
            <Field orientation="horizontal" className="w-auto">
              <RadioGroupItem id={`research-${stage}-code`} value="python" />
              <FieldLabel htmlFor={`research-${stage}-code`} className="min-h-9 cursor-pointer items-center">{t("workbench.pythonMode")}</FieldLabel>
            </Field>
          </RadioGroup>
          <ResearchInfotip label={modeLabel}>{t(stage === "universe_selection" ? "workbench.universeFilterHelp" : "workbench.stageModeHelp")}</ResearchInfotip>
        </FieldSet>}
        <div hidden={!python} className={cn("min-w-0", !python && "hidden")}>{codeEditor}</div>
        <div hidden={python} className={cn("min-w-0", python && "hidden")}>{configuredContents}</div>
    </TabsContent>;
  });
  return <Tabs value={factor ? "alpha" : activeStage} onValueChange={value => {
    const stage = frameworkStages.find(stage => stage === value);
    if (stage) onStageChange(stage);
  }} className="min-w-0 gap-4">
    {!factor && <TabsList variant="line" activateOnFocus aria-label={t("workbench.moduleNavigation")} className="w-full justify-start">
      {frameworkStages.map(stage => <TabsTrigger key={stage} value={stage} id={`research-stage-tab-${stage}`} className="flex-none">
        {t(`workbench.stageTab.${stage}`)}
        {Boolean(stageIssues?.[stage]) && <Badge variant="destructive" aria-label={t("workbench.stageIssueCount", { count: stageIssues?.[stage] })}>{stageIssues?.[stage]}</Badge>}
      </TabsTrigger>)}
    </TabsList>}
    {panels}
  </Tabs>;
}

function PolicyInput({ id, label, help, value, onChange, error, inputMode = "numeric" }: {
  id: string; label: string; help?: string; value: string; onChange: (value: string) => void;
  error?: string; inputMode?: "numeric" | "decimal";
}) {
  const { t } = useTranslation("strategy");
  return <Field data-invalid={Boolean(error)}>
    <div className="flex items-center gap-1"><FieldLabel htmlFor={id}>{label}</FieldLabel>{help && <ResearchInfotip label={label}>{help}</ResearchInfotip>}</div>
    <ResearchNumberInput id={id} label={label} percentage={inputMode === "decimal"} min={inputMode === "numeric" ? 1 : 0}
      max={inputMode === "decimal" ? 100 : undefined} placeholder={id === "minimum-holding-sessions" ? t("authoring.off") : undefined}
      value={value} onChange={onChange} error={error} />
    <FieldError id={`${id}-error`}>{error}</FieldError>
  </Field>;
}
