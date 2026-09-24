import Decimal from "decimal.js";
import { takeProfitDraft } from "./takeProfit";
import { frameworkStages, frozenStopLossPercentage, type FrameworkModules } from "./frameworkModules";
import type { PythonProgram } from "./pythonStrategy";
import { costFields, type SimulationCosts } from "./simulationCosts";
import { useTranslation } from "../i18n";

export function FrozenSimulationCosts({ costs }: { costs: SimulationCosts }) {
  const { t } = useTranslation("strategy");
  return <details className="research-run-fact-program">
    <summary>{t("frozen.fees")}</summary>
    {costFields.map(({ key }) => <p key={key}><strong>{t(`cost.labels.${key}`)}</strong> {costs[key]}</p>)}
    <p>{t("frozen.feesHelp")}</p>
  </details>;
}

export function FrozenPythonProgram({ program, title }: {
  program: PythonProgram; title?: string;
}) {
  const { t } = useTranslation("strategy");
  return <details className="research-run-fact-program">
    <summary>{title ?? t("frozen.python")}</summary>
    <p><strong>{t("frozen.history")}</strong> {t("frozen.sessions", { count: program.data_requirements.history_sessions })}</p>
    <p><strong>{t("frozen.fields")}</strong> <code>{program.data_requirements.field_ids.join(", ") || t("frozen.none")}</code></p>
    <pre><code>{program.source}</code></pre>
    <strong>{t("frozen.parameters")}</strong><pre><code>{JSON.stringify(program.parameters, null, 2)}</code></pre>
  </details>;
}

export function FrozenFrameworkModules({ modules }: { modules: FrameworkModules }) {
  const { t } = useTranslation("strategy");
  return <div className="research-run-fact-program" aria-label={t("frozen.modules")}>
    {frameworkStages.map(stage => {
      const module = modules[stage];
      return typeof module === "string" ? <p key={stage}><strong>{t(`stages.${stage}`)}</strong> <code>{module}</code></p>
        : module.kind === "builtin_risk/v1" ? <div key={stage}>
          {module.stop_loss_threshold !== undefined && <p><strong>{t("frozen.stopLoss")}</strong> {frozenStopLossPercentage(modules)}%</p>}
          {module.maximum_holding_sessions !== undefined && <p><strong>{t("frozen.maximumHolding")}</strong> {module.maximum_holding_sessions}</p>}
          {module.portfolio_drawdown && <p><strong>{t("frozen.drawdown")}</strong> {t("frozen.drawdownSummary", { threshold: new Decimal(module.portfolio_drawdown.drawdown_threshold).mul(100).toString(), cap: new Decimal(module.portfolio_drawdown.maximum_stock_exposure).mul(100).toString(), cooldown: module.portfolio_drawdown.cooldown_sessions })}</p>}
          {module.take_profit_tiers && <div><strong>{t("frozen.takeProfit")}</strong><ol>{takeProfitDraft(module.take_profit_tiers).map((tier, index) => <li key={index}>{t("frozen.tier", { profit: tier.profitThreshold, reduction: tier.cumulativeReduction })}</li>)}</ol><p>{t("frozen.baseline")}</p></div>}
          <p>{t("frozen.evaluated")}</p>
        </div> : module.kind === "periodic_top_n/v1" ? <p key={stage}><strong>{t("frozen.minimumHolding")}</strong> {module.minimum_holding_sessions}</p>
          : <FrozenPythonProgram key={stage} title={t("frozen.modulePython", { stage: t(`stages.${stage}`) })} program={module.program} />;
    })}
  </div>;
}
