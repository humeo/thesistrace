import { StrategyPerformanceChart } from "./StrategyPerformanceChart";
import type { StrategyComparison } from "./strategyComparison";

export function StrategyComparisonPanel({
  comparison,
}: {
  comparison: StrategyComparison;
}) {
  if (comparison.status === "unavailable") {
    return (
      <section
        aria-label="沪深300 Strategy Comparison"
        className="strategy-comparison-unavailable"
        role="status"
      >
        <strong>沪深300 comparison unavailable</strong>
        <p>
          The fixed Benchmark Snapshot is unavailable. No comparison chart is shown.
        </p>
      </section>
    );
  }

  const { benchmark, entry, terminal } = comparison;
  return (
    <section aria-label="沪深300 Strategy Comparison" className="strategy-comparison">
      <header className="strategy-comparison-header">
        <div>
          <p className="eyebrow">Fixed Strategy Benchmark</p>
          <h3>{benchmark.display_name}</h3>
          <p>{benchmark.ts_code} · Price Index · Open</p>
        </div>
        <p className="strategy-comparison-through">
          数据截至 <time dateTime={benchmark.coverage.end_session}>{benchmark.coverage.end_session}</time>
        </p>
      </header>
      <dl aria-label="沪深300 comparison metadata" className="strategy-comparison-metadata">
        <div>
          <dt>Snapshot SHA-256</dt>
          <dd><code title={benchmark.snapshot_sha256}>{benchmark.snapshot_sha256}</code></dd>
        </div>
        <div>
          <dt>Coverage</dt>
          <dd>{benchmark.coverage.start_session} to {benchmark.coverage.end_session}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd><time dateTime={benchmark.published_at}>{benchmark.published_at}</time></dd>
        </div>
        <div>
          <dt>Entry Open</dt>
          <dd>{entry.session} · level {entry.benchmark_open_level} · Initial Cash {entry.initial_cash_cny}</dd>
        </div>
        <div>
          <dt>Terminal Open</dt>
          <dd>{terminal.session} · level {terminal.benchmark_open_level} · Net NAV {terminal.net_nav}</dd>
        </div>
      </dl>
      <StrategyPerformanceChart curves={comparison.curves} />
    </section>
  );
}
