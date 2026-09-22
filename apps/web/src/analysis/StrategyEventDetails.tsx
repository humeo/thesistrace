import { Fragment, useId, useState } from "react";

export const eventSections = {
  strategy_targets: "调仓目标", strategy_orders: "委托", strategy_child_orders: "子委托",
  strategy_fills: "成交", strategy_adjustments: "估值调整", strategy_execution_constraints: "执行约束",
} as const;
export type EventSection = keyof typeof eventSections;
type EventValue = string | number | null | EventValue[] | { [key: string]: EventValue };
export type EventRow = Record<string, EventValue>;
export type EventRelation = { target_id?: string; order_id?: string; child_order_id?: string };
type Navigate = (section: EventSection, relation: EventRelation, context: string) => void;
const labels: Record<string, string> = {
  selection: "选股调仓", reduce: "降低仓位", increase: "增加仓位",
  rebalance: "完整组合", local: "局部减仓",
  valuation_carry: "沿用估值", terminal_delisting_writeoff: "退市核销",
  suspension: "停牌", data_unavailable: "行情不可用",
  upper_limit_buy: "涨停买入受限", lower_limit_sell: "跌停卖出受限",
  below_board_lot: "不足最小交易单位", insufficient_cash: "资金不足",
  buy: "买入", sell: "卖出",
};
const idFields: Record<EventSection, string> = {
  strategy_targets: "target_id", strategy_orders: "order_id", strategy_child_orders: "child_order_id",
  strategy_fills: "fill_id", strategy_adjustments: "adjustment_id", strategy_execution_constraints: "constraint_id",
};
const columns: Record<EventSection, { key: string; label: string; numeric?: boolean }[]> = {
  strategy_targets: [
    { key: "decision_session", label: "决策日期" }, { key: "reason", label: "原因" },
    { key: "allocation.mode", label: "作用范围" },
    { key: "allocation.instrument_ids", label: "组合股票数", numeric: true },
    { key: "allocation.exposure", label: "目标仓位", numeric: true },
    { key: "position_limits", label: "局部持仓上限（股）" },
  ],
  strategy_orders: [
    { key: "session", label: "执行日期" }, { key: "instrument_id", label: "股票" },
    { key: "side", label: "方向" }, { key: "legal_quantity", label: "委托股数", numeric: true },
    { key: "rejection_reason", label: "拒单原因" },
  ],
  strategy_child_orders: [
    { key: "session", label: "执行日期" }, { key: "instrument_id", label: "股票" },
    { key: "side", label: "方向" }, { key: "quantity", label: "股数", numeric: true },
  ],
  strategy_fills: [
    { key: "session", label: "执行日期" }, { key: "instrument_id", label: "股票" },
    { key: "side", label: "方向" }, { key: "quantity", label: "成交股数", numeric: true },
    { key: "raw_open", label: "成交价（元）", numeric: true },
    { key: "cost", label: "费用（元）", numeric: true },
  ],
  strategy_adjustments: [
    { key: "session", label: "调整日期" }, { key: "instrument_id", label: "股票" },
    { key: "type", label: "调整类型" }, { key: "valuation_delta", label: "估值变化（元）", numeric: true },
  ],
  strategy_execution_constraints: [
    { key: "session", label: "执行日期" }, { key: "instrument_id", label: "股票" },
    { key: "side", label: "方向" }, { key: "unrounded_quantity", label: "计划股数", numeric: true },
    { key: "legal_quantity", label: "取整后", numeric: true },
    { key: "submitted_quantity", label: "提交股数", numeric: true }, { key: "reason", label: "约束原因" },
  ],
};
export function instrumentLabel(value: string) { return value.replace(/^equity:/, ""); }
function cellValue(path: string, row: EventRow) {
  const [section, nested] = path.split(".");
  const parent = row[section];
  const value = nested && parent !== null && typeof parent === "object" && !Array.isArray(parent)
    ? parent[nested] : nested ? undefined : parent;
  const key = nested ?? section;
  if (path === "allocation.mode" && parent === null) return labels.local;
  if (value == null) return "—";
  if (key === "instrument_id") return instrumentLabel(String(value));
  if (key === "instrument_ids") return (value as string[]).length.toLocaleString("zh-CN");
  if (key === "position_limits") return Object.entries(value).map(([id, shares]) =>
    `${instrumentLabel(id)} ≤ ${Number(shares).toLocaleString("zh-CN")}`).join("；") || "—";
  if (key === "exposure") return (Number(value) * 100).toFixed(2) + "%";
  if (["side", "mode", "reason", "rejection_reason", "type"].includes(key)) return labels[String(value)] ?? String(value);
  if (key.endsWith("quantity")) return Number(value).toLocaleString("zh-CN");
  if (["raw_open", "cost", "valuation_delta"].includes(key)) return Number(value).toLocaleString("zh-CN", {
    minimumFractionDigits: 2, maximumFractionDigits: key === "raw_open" ? 6 : 2,
  });
  return String(value);
}

function EventRecord({ row, section, navigate }: { row: EventRow; section: EventSection; navigate: Navigate }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const json = JSON.stringify(row, null, 2);
  const targetId = row.target_id == null ? undefined : String(row.target_id);
  const orderId = row.order_id == null ? undefined : String(row.order_id);
  const childId = row.child_order_id == null ? undefined : String(row.child_order_id);
  const context = section === "strategy_targets"
    ? String(row.decision_session) + " 的调仓目标"
    : String(row.session) + " · " + instrumentLabel(String(row.instrument_id)) + " · " + eventSections[section];
  const linkedFills = section === "strategy_targets" ? { target_id: targetId }
    : section === "strategy_child_orders" ? { child_order_id: childId } : { order_id: orderId };
  return <div className="strategy-event-record">
    <div className="strategy-event-record-toolbar"><span>原始记录</span>
      <button type="button" onClick={async () => {
        setCopyError(false);
        try { await navigator.clipboard.writeText(json); setCopied(true); }
        catch { setCopied(false); setCopyError(true); }
      }}>{copied ? "已复制" : "复制 JSON"}</button>
    </div>
    {copyError && <p role="alert">复制失败，请在下方选择文本后手动复制。</p>}
    <pre tabIndex={0} aria-label="原始 JSON">{json}</pre>
    <div className="strategy-event-links" aria-label="关联记录">
      {targetId && section !== "strategy_targets" && <button type="button" onClick={() => navigate("strategy_targets", { target_id: targetId }, context)}>查看目标</button>}
      {section === "strategy_targets" && <button type="button" onClick={() => navigate("strategy_orders", { target_id: targetId }, context)}>查看委托</button>}
      {orderId && section !== "strategy_orders" && <button type="button" onClick={() => navigate("strategy_orders", { order_id: orderId }, context)}>查看委托</button>}
      {section === "strategy_orders" && <button type="button" onClick={() => navigate("strategy_child_orders", { order_id: orderId }, context)}>查看子委托</button>}
      {["strategy_targets", "strategy_orders", "strategy_child_orders", "strategy_execution_constraints"].includes(section)
        && Object.values(linkedFills).some(Boolean) && <button type="button" onClick={() => navigate("strategy_fills", linkedFills, context)}>查看成交</button>}
      {(section === "strategy_targets" || section === "strategy_orders") && <button type="button" onClick={() => navigate(
        "strategy_execution_constraints", section === "strategy_targets" ? { target_id: targetId } : { order_id: orderId }, context,
      )}>查看执行约束</button>}
    </div>
  </div>;
}

export function StrategyEventTable({ rows, section, navigate }: {
  rows: EventRow[]; section: EventSection; navigate: Navigate;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const prefix = useId();
  const selectedColumns = columns[section];
  return <div className="strategy-events-table-scroll" role="region" aria-label={eventSections[section] + "记录"} tabIndex={0}>
    <table className="strategy-events-table" aria-label={eventSections[section]}>
      <thead><tr>{selectedColumns.map(column => <th key={column.key} scope="col" className={column.numeric ? "numeric" : undefined}>{column.label}</th>)}
        <th scope="col"><span className="strategy-events-sr-only">原始记录</span></th>
      </tr></thead>
      <tbody>{rows.map(row => {
        const id = String(row[idFields[section]]);
        const open = expanded === id;
        const toggle = () => setExpanded(open ? null : id);
        const label = String(row.session ?? row.decision_session) + (row.instrument_id ? " " + instrumentLabel(String(row.instrument_id)) : "");
        const detailId = prefix + "-" + id;
        return <Fragment key={id}>
          <tr className={"strategy-event-row" + (open ? " is-expanded" : "")} onClick={toggle}>
            {selectedColumns.map(column => <td key={column.key} className={[
              column.numeric ? "numeric" : "",
              column.key.endsWith("session") || column.key === "instrument_id" ? "mono" : "",
              column.key === "rejection_reason" && row[column.key] ? "strategy-event-rejected" : "",
            ].filter(Boolean).join(" ")}>{cellValue(column.key, row)}</td>)}
            <td className="strategy-event-expand"><button type="button" aria-label={"查看原始记录：" + label}
              aria-expanded={open} aria-controls={open ? detailId : undefined} onClick={event => { event.stopPropagation(); toggle(); }}>
              <span aria-hidden="true" className={open ? "is-open" : undefined}>›</span>
            </button></td>
          </tr>
          {open && <tr id={detailId} className="strategy-event-detail-row"><td colSpan={selectedColumns.length + 1}>
            <EventRecord row={row} section={section} navigate={navigate} />
          </td></tr>}
        </Fragment>;
      })}</tbody>
    </table>
  </div>;
}
