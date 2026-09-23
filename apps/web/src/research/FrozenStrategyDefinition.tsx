import Decimal from "decimal.js";
import { takeProfitDraft } from "./takeProfit";
import { frameworkStageLabels, frameworkStages, frozenStopLossPercentage, type FrameworkModules } from "./frameworkModules";
import type { PythonProgram } from "./pythonStrategy";
import { costFields, type SimulationCosts } from "./simulationCosts";

export function FrozenSimulationCosts({ costs }: { costs: SimulationCosts }) {
  return <details className="research-run-fact-program">
    <summary>Frozen fees and slippage</summary>
    {costFields.map(({ key, label }) => <p key={key}><strong>{label}</strong> {costs[key]}</p>)}
    <p>Minimum commission applies to each filled child order. Slippage changes execution prices and is not charged again as a fee.</p>
  </details>;
}

export function FrozenPythonProgram({ program, title = "Frozen Python source and parameters" }: {
  program: PythonProgram; title?: string;
}) {
  return <details className="research-run-fact-program">
    <summary>{title}</summary>
    <p><strong>History</strong> {program.data_requirements.history_sessions} sessions</p>
    <p><strong>Declared fields</strong> <code>{program.data_requirements.field_ids.join(", ") || "None"}</code></p>
    <pre><code>{program.source}</code></pre>
    <strong>Parameters</strong><pre><code>{JSON.stringify(program.parameters, null, 2)}</code></pre>
  </details>;
}

export function FrozenFrameworkModules({ modules }: { modules: FrameworkModules }) {
  return <div className="research-run-fact-program" aria-label="Frozen Framework modules">
    {frameworkStages.map(stage => {
      const module = modules[stage];
      return typeof module === "string" ? <p key={stage}><strong>{frameworkStageLabels[stage]}</strong> <code>{module}</code></p>
        : module.kind === "builtin_risk/v1" ? <div key={stage}>
          {module.stop_loss_threshold !== undefined && <p><strong>Risk Management · Stop loss</strong> {frozenStopLossPercentage(modules)}%</p>}
          {module.maximum_holding_sessions !== undefined && <p><strong>Maximum holding (trading sessions)</strong> {module.maximum_holding_sessions}</p>}
          {module.portfolio_drawdown && <p><strong>Portfolio drawdown</strong> Threshold {new Decimal(module.portfolio_drawdown.drawdown_threshold).mul(100).toString()}%; stock exposure cap {new Decimal(module.portfolio_drawdown.maximum_stock_exposure).mul(100).toString()}%; cooldown {module.portfolio_drawdown.cooldown_sessions} trading sessions. A fresh portfolio decision is required for recovery.</p>}
          {module.take_profit_tiers && <div><strong>Cumulative take profit</strong><ol>{takeProfitDraft(module.take_profit_tiers).map((tier, index) => <li key={index}>Profit {tier.profitThreshold}% → cumulative reduction {tier.cumulativeReduction}%</li>)}</ol><p>Baseline freezes at the first trigger. No ordinary additions until full exit.</p></div>}
          <p>Evaluated at Close; the next Open determines execution.</p>
        </div> : module.kind === "periodic_top_n/v1" ? <p key={stage}><strong>Minimum holding (trading sessions)</strong> {module.minimum_holding_sessions}</p>
          : <FrozenPythonProgram key={stage} title={`${frameworkStageLabels[stage]} · Frozen Python source and parameters`} program={module.program} />;
    })}
  </div>;
}
