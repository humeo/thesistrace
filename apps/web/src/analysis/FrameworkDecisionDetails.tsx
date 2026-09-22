type Proposal = {
  reason: string;
  allocation: { mode: "rebalance" | "reduce" | "increase"; instrument_ids: string[];
    relative_weights: Record<string, string>; exposure: number } | null;
  position_limits: Record<string, number>;
};
type Signal = { instrument_id: string; value: number; created_session: string;
  created_session_number: number; valid_for_sessions: number };
export type FrameworkRecord = {
  decision_session: string;
  modules: Record<string, string>;
  universe: { instrument_ids: string[]; updated: boolean; reason: string | null };
  alpha: { kind: "formula"; values: { instrument_id: string; value: number }[] }
    | { kind: "signals"; signals: Signal[]; updated: boolean; reason: string | null;
      expired_signals: string[]; removed_signals: string[] };
  proposal: Proposal | null;
  risk_adjustment: { mode: "replace"; reason: string; target: Proposal | null }
    | { mode: "limit_positions"; reason: string; position_limits: Record<string, number> } | null;
  target_id: string | null;
};
const stock = (id: string) => id.replace(/^equity:/, "");
const stageLabels: Record<string, string> = {
  universe_selection: "候选选择", alpha: "信号", portfolio_construction: "组合建议", risk_management: "风险调整",
};

function Limits({ limits }: { limits: Record<string, number> }) {
  return <ul>{Object.entries(limits).map(([id, shares]) => <li key={id}>
    {stock(id)}：最多保留 {shares.toLocaleString("zh-CN")} 股
  </li>)}</ul>;
}

function Portfolio({ value }: { value: Proposal }) {
  return <>
    <p>原因：{value.reason}</p>
    {value.allocation && <>
      <p>{({ rebalance: "完整组合", reduce: "降低仓位", increase: "增加仓位" })[value.allocation.mode]}
        {" · 目标仓位 " + (value.allocation.exposure * 100).toFixed(2) + "%"}</p>
      <details><summary>组合权重（{value.allocation.instrument_ids.length} 只）</summary>
        <ul>{value.allocation.instrument_ids.map(id => <li key={id}>
          {stock(id)}：{value.allocation!.relative_weights[id]}
        </li>)}</ul>
      </details>
    </>}
    {Object.keys(value.position_limits).length > 0 && <Limits limits={value.position_limits} />}
  </>;
}

export function FrameworkDecisionDetails({ row }: { row: FrameworkRecord }) {
  const alpha = row.alpha;
  const risk = row.risk_adjustment;
  return <div className="framework-decision-details">
    <p>{row.decision_session} 收盘判断，最终目标交由下一研究交易日开盘执行。</p>
    <section aria-label="候选选择"><h4>1 · 候选选择</h4>
      <p>{row.universe.updated ? "已更新候选选择" : "本日无新选择，保留仍可用的候选"}
        {" · " + row.universe.instrument_ids.length + " 只"}</p>
      {row.universe.reason && <p>原因：{row.universe.reason}</p>}
      <details><summary>候选股票</summary><p className="framework-instruments">
        {row.universe.instrument_ids.map(stock).join("、") || "空候选集"}
      </p></details>
    </section>
    <section aria-label="信号"><h4>2 · {alpha.kind === "formula" ? "Alpha Values" : "策略信号"}</h4>
      {alpha.kind === "formula" ? <>
        <p>本日公式计算值，共 {alpha.values.length} 只股票。</p>
        <details><summary>查看 Alpha Values</summary><ul>{alpha.values.map(item =>
          <li key={item.instrument_id}>{stock(item.instrument_id)}：{item.value}</li>)}</ul></details>
      </> : <>
        <p>{alpha.updated ? "已更新信号" : "本日无新信号，保留尚未到期的信号"}
          {" · 当前 " + alpha.signals.length + " 条"}</p>
        {alpha.reason && <p>原因：{alpha.reason}</p>}
        {alpha.expired_signals.length > 0 && <p>本日到期：{alpha.expired_signals.map(stock).join("、")}</p>}
        {alpha.removed_signals.length > 0 && <p>移出候选：{alpha.removed_signals.map(stock).join("、")}</p>}
        <p>信号变化由组合模块判断，不会自动生成卖单。</p>
        {alpha.signals.length > 0 && <details><summary>信号与有效期</summary><ul>{alpha.signals.map(item =>
          <li key={item.instrument_id}>{stock(item.instrument_id)}：{item.value} · {item.created_session} 产生
            · 含产生日在内有效 {item.valid_for_sessions} 个研究交易日</li>)}</ul></details>}
      </>}
    </section>
    <section aria-label="组合建议"><h4>3 · 组合建议</h4>
      {row.proposal ? <Portfolio value={row.proposal} /> : <p>本日无新组合建议（NoUpdate）。</p>}
    </section>
    <section aria-label="风险调整"><h4>4 · 风险调整</h4>
      {!risk ? <p>本日无风险调整。</p> : <>
        <p>原因：{risk.reason}</p>
        {risk.mode === "limit_positions" ? <><p>局部持仓上限；未列出的持仓数量不因此改变。</p>
          <Limits limits={risk.position_limits} /></>
          : risk.target ? <><p>替换本日组合建议。</p><Portfolio value={risk.target} /></>
            : <p>明确取消本日组合建议，不产生新目标。</p>}
      </>}
    </section>
    <p>{row.target_id ? "已形成最终目标；实际成交或拒绝请查看关联记录。" : "未形成新的目标，不会因此自动调仓。"}</p>
    <details><summary>模块身份</summary><dl>{Object.entries(row.modules).map(([stage, identity]) =>
      <div key={stage}><dt>{stageLabels[stage]}</dt><dd>{identity}</dd></div>)}</dl></details>
  </div>;
}
