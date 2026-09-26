import { Metric, MetricGroup } from "../components/product/MetricGroup";
import { useTranslation } from "react-i18next";
import { formatPercent, formatDecimal, formatCurrency } from "../i18n/format";
import { catalogLabel } from "../i18n/catalog";
import { StrategyComparisonPanel } from "../analysis/StrategyComparisonPanel";
import type { StrategyComparison } from "../analysis/strategyComparison";


type DailyTrackStrategyObservation = {
  session: string;
  gross_nav: string;
  net_nav: string;
  net_cash: string;
  transaction_cost_cny: string;
  holdings_count: number;
  maximum_single_name_weight: number;
  upper_limit_buy_rejections: number;
  lower_limit_sell_rejections: number;
  suspension_rejections: number;
};

export type DailyTrackAnalysis = {
  strategy: {
    summary: {
      metrics: {
        net_cumulative_return: number;
        benchmark_cumulative_return: number | null;
        benchmark_cagr: number | null;
        annualized_excess_return: number | null;
        maximum_drawdown: { value: number | null };
        sharpe: number | null;
        transaction_costs: { cumulative_amount: number };
      };
    };
    observations: DailyTrackStrategyObservation[];
    comparison: StrategyComparison;
  };
};

export function DailyTrackAnalysisView({ analysis }: { analysis: DailyTrackAnalysis }) {
  const { t } = useTranslation("daily");
  const metrics = analysis.strategy.summary.metrics;
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <section className="flex min-w-0 flex-col gap-4">
        <StrategyComparisonPanel comparison={analysis.strategy.comparison} />
        <div>
          <h2 className="m-0 text-base font-semibold">{t("summary")}</h2>
        </div>
        <MetricGroup label={t("summary")} className="sm:grid-cols-3">
          <Metric label={t("netCumulative") } value={formatPercent(metrics.net_cumulative_return)} />
          <Metric
            label={t("benchmarkCumulative", { benchmark: catalogLabel("benchmarks", "csi300-price-index-open") })}
            value={formatPercent(metrics.benchmark_cumulative_return)}
          />
          <Metric
            label={t("annualizedExcess") }
            value={formatPercent(metrics.annualized_excess_return)}
          />
          <Metric
            label={t("maximumDrawdown") }
            value={formatPercent(metrics.maximum_drawdown.value)}
          />
          <Metric label={t("sharpe") } value={formatDecimal(metrics.sharpe)} />
          <Metric
            label={t("transactionCosts") }
            value={formatCurrency(metrics.transaction_costs.cumulative_amount, 0)}
          />
        </MetricGroup>
      </section>
    </div>
  );
}
