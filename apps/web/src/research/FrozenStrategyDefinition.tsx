import { Disclosure } from "../components/layout/Disclosure";
import Decimal from "decimal.js";
import { takeProfitDraft } from "./takeProfit";
import { frameworkStages, frozenStopLossPercentage, type FrameworkModules } from "./frameworkModules";
import type { PythonProgram } from "./pythonStrategy";
import { costFields, type SimulationCosts } from "./simulationCosts";
import { useTranslation } from "../i18n";

export function FrozenSimulationCosts({ costs }: { costs: SimulationCosts }) {
  const { t } = useTranslation("strategy");
  return <Disclosure title={<>{t("frozen.fees")}</>}>
    {costFields.map(({ key }) => <p key={key}><strong>{t(`cost.labels.${key}`)}</strong> {costs[key]}</p>)}
    <p>{t("frozen.feesHelp")}</p>
  </Disclosure>;
}

export function FrozenPythonProgram({ program, title }: {
  program: PythonProgram; title?: string;
}) {
  const { t } = useTranslation("strategy");
  return <Disclosure title={<>{title ?? t("frozen.python")}</>}>
    <pre className="max-h-96 min-w-0 overflow-auto rounded-md bg-muted p-4 font-mono text-sm" tabIndex={0}><code>{program.source}</code></pre>
  </Disclosure>;
}

export function FrozenFrameworkModules({ modules }: { modules: FrameworkModules }) {
  const { t } = useTranslation("strategy");
  return <div className="col-span-full grid min-w-0 gap-4" aria-label={t("frozen.modules")}>
    {frameworkStages.map(stage => {
      const module = modules[stage];
      return typeof module === "string" ? <p key={stage}><strong>{t(`workbench.section.${stage}`)}</strong> {t(`builtin.${stage}`)}</p>
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
