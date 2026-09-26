import { CloseRiskFacts } from "../analysis/CloseRiskFacts";
import { MetricHelp } from "../analysis/MetricHelp";
import { StrategyComparisonPanel } from "../analysis/StrategyComparisonPanel";
import { Disclosure } from "../components/layout/Disclosure";
import { Metric, MetricGroup } from "../components/product/MetricGroup";
import { useTranslation } from "../i18n";
import { catalogLabel } from "../i18n/catalog";
import { formatDecimal, formatPercent } from "../i18n/format";
import { FrameworkStateView } from "../research/FrameworkStateView";
import { SelectionEligibilityView } from "../research/SelectionEligibility";
import { isBuiltinFrameworkState, strategySelection } from "../research/strategyDecisionState";
import { strategyMetricHelp } from "./metricHelp";
import type { StrategyBacktestResearchResult } from "./ResearchRunsPage";

export function StrategyResultView({ result: strategyResult }: { result: StrategyBacktestResearchResult }) {
  const { t } = useTranslation("runs");
  const strategyHelp = strategyMetricHelp();
  const selection = strategySelection(strategyResult.terminal_strategy_state.decision_state);
  return (<section aria-label={t("result.strategy")} className="flex min-w-0 flex-col gap-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="m-0 text-base font-semibold">{t("result.strategy")}</h2>
          <p>{t("result.accountThrough")} <time>{strategyResult.terminal_strategy_state.session}</time></p>
        </div>
        <MetricGroup label={t("result.strategy")} className="sm:grid-cols-3 xl:grid-cols-6">
          <Metric label={t("result.netCumulative")} help={<MetricHelp label={t("result.netCumulative")} content={strategyHelp.netCumulative} />} value={formatPercent(strategyResult.strategy.summary.metrics.net_cumulative_return)} />
          <Metric
            label={t("result.benchmarkCumulative", { benchmark: catalogLabel("benchmarks", "csi300-price-index-open") })}
            help={<MetricHelp label={t("result.benchmarkCumulative", { benchmark: catalogLabel("benchmarks", "csi300-price-index-open") })} content={strategyHelp.benchmarkCumulative} />}
            value={formatPercent(strategyResult.strategy.summary.metrics.benchmark_cumulative_return)}
          />
          <Metric
            label={t("result.annualizedExcess")}
            help={<MetricHelp label={t("result.annualizedExcess")} content={strategyHelp.annualizedExcess} />}
            value={formatPercent(strategyResult.strategy.summary.metrics.annualized_excess_return)}
          />
          <Metric
            label={t("result.maximumDrawdown")}
            help={<MetricHelp label={t("result.maximumDrawdown")} content={strategyHelp.maximumDrawdown} />}
            value={formatPercent(strategyResult.strategy.summary.metrics.maximum_drawdown.value)}
          />
          <Metric label={t("result.sharpe")} help={<MetricHelp label={t("result.sharpe")} content={strategyHelp.sharpe} />} value={formatDecimal(strategyResult.strategy.summary.metrics.sharpe)} />
          <Metric
            label={t("result.costRatio")}
            help={<MetricHelp label={t("result.costRatio")} content={strategyHelp.cumulativeCostRatio} />}
            value={formatPercent(strategyResult.strategy.summary.metrics.transaction_costs.ratio)}
          />
        </MetricGroup>
        <StrategyComparisonPanel comparison={strategyResult.strategy.comparison} />
        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-col gap-3">
            <h3>{t("result.exposure")}</h3>
            <dl className="m-0 grid grid-cols-2 gap-4 [&_dd]:m-0 [&_dd]:font-mono [&_dt]:text-muted-foreground">
              <div><dt>{t("result.lastCloseTarget")}</dt><dd>{formatPercent(isBuiltinFrameworkState(strategyResult.terminal_strategy_state.decision_state)
                ? strategyResult.terminal_strategy_state.decision_state.exposure
                : strategyResult.terminal_strategy_state.pending_target?.allocation?.exposure ?? null)}</dd></div>
              <div><dt>{t("result.actualOpenAllocation")}</dt><dd>{formatPercent(1 - Number(strategyResult.terminal_strategy_state.net_cash) / Number(strategyResult.terminal_strategy_state.net_nav))}</dd></div>
            </dl>
          </div>
          {selection !== null ? <div className="flex flex-col gap-3">
            <h3>{t("result.selection")}</h3>
            <SelectionEligibilityView selection={selection} />
          </div> : null}
          <CloseRiskFacts session={strategyResult.terminal_strategy_state.session}
            nav={strategyResult.terminal_strategy_state.close_risk_nav_cny}
            positions={strategyResult.terminal_strategy_state.positions} />
          <FrameworkStateView state={strategyResult.terminal_strategy_state.decision_state} />
          <Disclosure title={t("result.conventions")}>
            <ul>
              <li>{t("result.nextOpen")}</li>
              <li>{t("result.allocation")}</li>
            </ul>
          </Disclosure>
        </div>
      </section>
);
}
