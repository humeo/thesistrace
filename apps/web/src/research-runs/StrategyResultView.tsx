import { CloseRiskFacts } from "../analysis/CloseRiskFacts";
import { MetricHelp } from "../analysis/MetricHelp";
import { StrategyComparisonPanel } from "../analysis/StrategyComparisonPanel";
import { Disclosure } from "../components/layout/Disclosure";
import { Metric, MetricGroup } from "../components/product/MetricGroup";
import { useTranslation } from "../i18n";
import { catalogLabel } from "../i18n/catalog";
import { formatDecimal, formatPercent } from "../i18n/format";
import { FrameworkStateView } from "../research/FrameworkStateView";
import { ResearchInfotip } from "../research/ResearchInfotip";
import { SelectionEligibilityView } from "../research/SelectionEligibility";
import { isBuiltinFrameworkState, strategySelection } from "../research/strategyDecisionState";
import { strategyMetricHelp } from "./metricHelp";
import type { StrategyBacktestResearchResult } from "./ResearchRunsPage";

export function StrategyResultView({ result }: { result: StrategyBacktestResearchResult }) {
  const { t } = useTranslation("runs");
  const help = strategyMetricHelp();
  const { metrics } = result.strategy.summary;
  const state = result.terminal_strategy_state;
  const selection = strategySelection(state.decision_state);
  const returnTone = (value: number | null) => value === null || value === 0 ? undefined : value > 0 ? "positive" as const : "negative" as const;
  const items = [
    { key: "net", label: t("result.netCumulative"), help: help.netCumulative, value: formatPercent(metrics.net_cumulative_return, { signed: true }), tone: returnTone(metrics.net_cumulative_return) },
    { key: "benchmark", label: t("result.benchmarkCumulative", { benchmark: catalogLabel("benchmarks", "csi300-price-index-open") }), help: help.benchmarkCumulative, value: formatPercent(metrics.benchmark_cumulative_return, { signed: true }), tone: "benchmark" as const },
    { key: "excess", label: t("result.annualizedExcess"), help: help.annualizedExcess, value: formatPercent(metrics.annualized_excess_return, { signed: true }), tone: returnTone(metrics.annualized_excess_return) },
    { key: "drawdown", label: t("result.maximumDrawdown"), help: help.maximumDrawdown, value: formatPercent(metrics.maximum_drawdown.value) },
    { key: "sharpe", label: t("result.sharpe"), help: help.sharpe, value: formatDecimal(metrics.sharpe) },
    { key: "costs", label: t("result.costRatio"), help: help.cumulativeCostRatio, value: formatPercent(metrics.transaction_costs.ratio) },
  ];

  return <section aria-label={t("result.strategy")} className="strategy-result flex min-w-0 flex-col gap-3">
    <MetricGroup label={t("result.strategy")} variant="result">
      {items.map(item => <Metric key={item.key} variant="result" label={item.label} value={item.value} tone={item.tone}
        help={<MetricHelp hover label={item.label} content={item.help} />} />)}
    </MetricGroup>
    <StrategyComparisonPanel comparison={result.strategy.comparison} variant="result" />
    <section aria-labelledby="result-ending-state" className="rounded-md border border-border bg-card px-5 py-2">
      <h2 id="result-ending-state" className="m-0 text-base leading-6 font-semibold">{t("result.terminalState")}</h2>
      <dl className="m-0 mt-2 grid grid-cols-3 [&>div]:border-r [&>div]:border-border [&>div]:px-6 [&>div:first-child]:pl-0 [&>div:last-child]:border-r-0 [&_dd]:m-0 [&_dd]:font-sans [&_dd]:text-xl [&_dd]:leading-7 [&_dd]:tabular-nums [&_dt]:flex [&_dt]:items-center [&_dt]:gap-1 [&_dt]:text-sm [&_dt]:text-muted-foreground">
        <div>
          <dt>{t("result.targetExposure")}<ResearchInfotip label={t("result.targetExposure")}>{t("result.targetExposureHelp")}</ResearchInfotip></dt>
          <dd>{formatPercent(isBuiltinFrameworkState(state.decision_state) ? state.decision_state.exposure : state.pending_target?.allocation?.exposure ?? null)}</dd>
        </div>
        <div>
          <dt>{t("result.actualExposure")}<ResearchInfotip label={t("result.actualExposure")}>{t("result.allocation")}</ResearchInfotip></dt>
          <dd>{formatPercent(1 - Number(state.net_cash) / Number(state.net_nav))}</dd>
        </div>
        <div>
          <dt>{t("result.terminalAccount")}<ResearchInfotip label={t("result.terminalAccount")}>{t("result.nextOpen")}</ResearchInfotip></dt>
          <dd><time dateTime={state.session}>{state.session}</time></dd>
        </div>
      </dl>
    </section>
    <div className="overflow-hidden rounded-md border border-border bg-card">
      {selection !== null ? <Disclosure title={t("result.selection")} variant="row"><SelectionEligibilityView selection={selection} /></Disclosure> : null}
      <CloseRiskFacts variant="row" session={state.session} nav={state.close_risk_nav_cny} positions={state.positions} />
      <FrameworkStateView variant="row" state={state.decision_state} />
      <Disclosure title={t("result.conventions")} variant="row">
        <ul className="m-0 pl-5"><li>{t("result.nextOpen")}</li><li>{t("result.allocation")}</li></ul>
      </Disclosure>
    </div>
  </section>;
}
