import { PortfolioDrawdownAuthoring } from "./PortfolioDrawdownAuthoring";
import type { DrawdownInputs } from "./portfolioDrawdown";
import { TakeProfitAuthoring } from "./TakeProfitAuthoring";
import type { TakeProfitTierDraft } from "./takeProfit";
import type { ReactNode } from "react";
import type { ResearchInputField } from "./draft";
import {
  frameworkStages, type FrameworkModulesDraft, type FrameworkStage,
} from "./frameworkModules";
import type { ProgramInputs } from "./pythonStrategy";
import { PythonStrategyAuthoring } from "./PythonStrategyAuthoring";
import { useTranslation } from "../i18n";

export function FrameworkAuthoring({ drawdown, updateDrawdown, modules, selectModule, updateProgram, stopLossThreshold, updateStopLoss, maximumHoldingSessions, updateMaximumHoldingSessions, minimumHoldingSessions, updateMinimumHoldingSessions, takeProfitTiers, updateTakeProfitTiers, error, fieldsButton, alphaEditor }: {
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
  fieldsButton: () => ReactNode;
  alphaEditor: ReactNode;
}) {
  const { t } = useTranslation("strategy");
  return <div className="framework-authoring">
    <p className="framework-order">{t("authoring.order")}</p>
    {frameworkStages.map((stage, index) => <section key={stage} className="framework-module" aria-label={t("authoring.module", { stage: t(`stages.${stage}`) })}>
      <div className="framework-module-heading">
        <h3><span>{index + 1}</span> {t(`stages.${stage}`)}</h3>
        <select aria-label={t("authoring.module", { stage: t(`stages.${stage}`) })} value={modules[stage].kind} onChange={event => {
          if (event.target.value === "builtin" || event.target.value === "python") selectModule(stage, event.target.value);
        }}>
          <option value="builtin">{t("authoring.builtin", { name: t(`builtin.${stage}`) })}</option>
          <option value="python">{t("authoring.pythonModule")}</option>
        </select>
      </div>
      <p className="framework-module-help">{t(`explanations.${stage}`)}</p>
      {modules[stage].kind === "python" ? <PythonStrategyAuthoring stage={stage}
        inputs={modules[stage].program} onChange={changes => updateProgram(stage, changes)}
        error={field => error(`${stage}.${field}`)} fieldsButton={fieldsButton()} />
        : stage === "alpha" ? alphaEditor : stage === "risk_management" ? <div className="research-parameter-field">
          <PortfolioDrawdownAuthoring values={drawdown} onChange={updateDrawdown} error={error} />
          <TakeProfitAuthoring tiers={takeProfitTiers} onChange={updateTakeProfitTiers} error={error} />
          <label htmlFor="stop-loss-threshold">{t("authoring.stopLoss")}</label>
          <input id="stop-loss-threshold" type="text" inputMode="decimal" placeholder={t("authoring.off")} maxLength={128}
            value={stopLossThreshold} onChange={event => updateStopLoss(event.target.value)}
            aria-invalid={Boolean(error("stopLossThreshold"))}
            aria-describedby={error("stopLossThreshold") ? "stop-loss-help stop-loss-error" : "stop-loss-help"} />
          <p id="stop-loss-help" className="framework-module-help">{t("authoring.stopLossHelp")}</p>
          {error("stopLossThreshold") && <p id="stop-loss-error" className="inline-status-error">{error("stopLossThreshold")}</p>}
          <label htmlFor="maximum-holding-sessions">{t("authoring.maximumHolding")}</label>
          <input id="maximum-holding-sessions" type="text" inputMode="numeric" placeholder={t("authoring.off")} maxLength={16}
            value={maximumHoldingSessions} onChange={event => updateMaximumHoldingSessions(event.target.value)}
            aria-invalid={Boolean(error("maximumHoldingSessions"))}
            aria-describedby={error("maximumHoldingSessions") ? "maximum-holding-help maximum-holding-error" : "maximum-holding-help"} />
          <p id="maximum-holding-help" className="framework-module-help">{t("authoring.maximumHoldingHelp")}</p>
          {error("maximumHoldingSessions") && <p id="maximum-holding-error" className="inline-status-error">{error("maximumHoldingSessions")}</p>}
        </div> : stage === "portfolio_construction" ? <div className="research-parameter-field">
          <label htmlFor="minimum-holding-sessions">{t("authoring.minimumHolding")}</label>
          <input id="minimum-holding-sessions" type="text" inputMode="numeric" placeholder={t("authoring.off")} maxLength={16}
            value={minimumHoldingSessions} onChange={event => updateMinimumHoldingSessions(event.target.value)}
            aria-invalid={Boolean(error("minimumHoldingSessions"))}
            aria-describedby={error("minimumHoldingSessions") ? "minimum-holding-help minimum-holding-error" : "minimum-holding-help"} />
          <p id="minimum-holding-help" className="framework-module-help">{t("authoring.minimumHoldingHelp")}</p>
          {error("minimumHoldingSessions") && <p id="minimum-holding-error" className="inline-status-error">{error("minimumHoldingSessions")}</p>}
        </div> : null}
    </section>)}
  </div>;
}
