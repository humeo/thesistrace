import type { ParseKeys } from "i18next";
import { i18n, useTranslation } from "../i18n";
import { formatNumber, formatPercent } from "../i18n/format";
import { Fragment, useId, useState } from "react";
import Decimal from "decimal.js";
import { FrameworkDecisionDetails, type FrameworkRecord } from "./FrameworkDecisionDetails";

export const eventSections = [
  "strategy_framework", "strategy_targets", "strategy_orders", "strategy_child_orders", "strategy_fills", "strategy_adjustments", "strategy_execution_constraints",
] as const;
export type EventSection = typeof eventSections[number];
export type EventScope = { section: EventSection; session: string; instrument?: string };
export function eventSectionLabel(section: EventSection): string {
  return i18n.t(`analysis:events.sections.${section}`);
}
export function eventScopeLabel(scope: EventScope): string {
  return scope.section === "strategy_targets" || scope.section === "strategy_framework"
    ? i18n.t("analysis:events.targetContext", { date: scope.session, section: eventSectionLabel(scope.section) })
    : i18n.t("analysis:events.recordContext", { date: scope.session, instrument: scope.instrument ?? "", section: eventSectionLabel(scope.section) });
}
type EventValue = string | number | boolean | null | EventValue[] | { [key: string]: EventValue };
export type EventRow = Record<string, EventValue>;
export type EventRelation = { target_id?: string; order_id?: string; child_order_id?: string };
type Navigate = (section: EventSection, relation: EventRelation, context: EventScope) => void;
const idFields: Record<EventSection, string> = {
  strategy_framework: "decision_id",
  strategy_targets: "target_id", strategy_orders: "order_id", strategy_child_orders: "child_order_id",
  strategy_fills: "fill_id", strategy_adjustments: "adjustment_id", strategy_execution_constraints: "constraint_id",
};
const columns: Record<EventSection, { key: string; label: ParseKeys<"analysis">; numeric?: boolean }[]> = {
  strategy_framework: [
    { key: "decision_session", label: "events.decisionDate" },
    { key: "universe.instrument_ids", label: "events.columns.candidates", numeric: true },
    { key: "proposal.reason", label: "events.columns.proposal" },
    { key: "risk_adjustment.mode", label: "events.columns.riskAdjustment" },
    { key: "target_id", label: "events.columns.finalTarget" },
  ],
  strategy_targets: [
    { key: "decision_session", label: "events.decisionDate" }, { key: "reason", label: "events.columns.reason" },
    { key: "allocation.mode", label: "events.columns.scope" },
    { key: "allocation.instrument_ids", label: "events.columns.portfolioStocks", numeric: true },
    { key: "allocation.exposure", label: "events.columns.exposure", numeric: true },
    { key: "position_limits", label: "events.columns.positionLimits" },
  ],
  strategy_orders: [
    { key: "session", label: "events.executionDate" }, { key: "instrument_id", label: "events.columns.instrument" },
    { key: "side", label: "events.columns.side" }, { key: "legal_quantity", label: "events.columns.orderQuantity", numeric: true },
    { key: "rejection_reason", label: "events.columns.rejection" },
  ],
  strategy_child_orders: [
    { key: "session", label: "events.executionDate" }, { key: "instrument_id", label: "events.columns.instrument" },
    { key: "side", label: "events.columns.side" }, { key: "quantity", label: "events.columns.quantity", numeric: true },
  ],
  strategy_fills: [
    { key: "session", label: "events.executionDate" }, { key: "instrument_id", label: "events.columns.instrument" },
    { key: "side", label: "events.columns.side" }, { key: "quantity", label: "events.columns.fillQuantity", numeric: true },
    { key: "raw_open", label: "events.columns.rawOpen", numeric: true },
    { key: "execution_price", label: "events.columns.executionPrice", numeric: true },
    { key: "cost", label: "events.columns.cost", numeric: true },
  ],
  strategy_adjustments: [
    { key: "session", label: "events.adjustmentDate" }, { key: "instrument_id", label: "events.columns.instrument" },
    { key: "type", label: "events.columns.mode" }, { key: "valuation_delta", label: "events.columns.valuation", numeric: true },
  ],
  strategy_execution_constraints: [
    { key: "session", label: "events.executionDate" }, { key: "instrument_id", label: "events.columns.instrument" },
    { key: "side", label: "events.columns.side" }, { key: "unrounded_quantity", label: "events.columns.planned", numeric: true },
    { key: "legal_quantity", label: "events.columns.legal", numeric: true },
    { key: "submitted_quantity", label: "events.columns.submitted", numeric: true }, { key: "reason", label: "events.columns.reason" },
  ],
};
export function instrumentLabel(value: string) { return value.replace(/^equity:/, ""); }
function cellValue(path: string, row: EventRow) {
  const labels = i18n.t("analysis:events.labels", { returnObjects: true });
  const [section, nested] = path.split(".");
  const parent = row[section];
  const value = nested && parent !== null && typeof parent === "object" && !Array.isArray(parent)
    ? parent[nested] : nested ? undefined : parent;
  const key = nested ?? section;
  if (path === "proposal.reason" && parent === null) return i18n.t("analysis:events.noUpdate");
  if (path === "target_id" && row.decision_id) return value ? i18n.t("analysis:events.formed") : i18n.t("analysis:events.noUpdate");
  if (path === "risk_adjustment.mode" && value) return value === "replace" ? i18n.t("analysis:events.replaceRisk") : i18n.t("analysis:events.localCap");
  if (path === "allocation.mode" && parent === null) return labels.local;
  if (value == null) return "—";
  if (key === "instrument_id") return instrumentLabel(String(value));
  if (key === "instrument_ids" || key === "selected_instrument_ids") return formatNumber((value as string[]).length);
  if (key === "position_limits") return Object.entries(value as Record<string, EventValue>).map(([id, shares]) =>
    `${instrumentLabel(id)} ≤ ${formatNumber(Number(shares))}`).join("; ") || "—";
  if (key === "exposure") return formatPercent(Number(value));
  if (["side", "mode", "reason", "rejection_reason", "type"].includes(key)) return labels[String(value) as keyof typeof labels] ?? String(value);
  if (key.endsWith("quantity")) return formatNumber(Number(value));
  if (["raw_open", "execution_price", "cost", "valuation_delta"].includes(key)) return formatNumber(Number(value), {
    minimumFractionDigits: 2, maximumFractionDigits: ["raw_open", "execution_price"].includes(key) ? 6 : 2,
  });
  return String(value);
}

function EventRecord({ row, section, navigate }: { row: EventRow; section: EventSection; navigate: Navigate }) {
  const { t } = useTranslation("analysis");
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const json = JSON.stringify(row, null, 2);
  const targetId = row.target_id == null ? undefined : String(row.target_id);
  const orderId = row.order_id == null ? undefined : String(row.order_id);
  const childId = row.child_order_id == null ? undefined : String(row.child_order_id);
  const context: EventScope = { section, session: String(section === "strategy_targets" || section === "strategy_framework" ? row.decision_session : row.session),
    ...(row.instrument_id == null ? {} : { instrument: instrumentLabel(String(row.instrument_id)) }) };
  const linkedFills = section === "strategy_targets" ? { target_id: targetId }
    : section === "strategy_child_orders" ? { child_order_id: childId } : { order_id: orderId };
  return <div className="strategy-event-record">
    {section === "strategy_framework" && <FrameworkDecisionDetails row={row as FrameworkRecord} />}
    {section === "strategy_fills" && <section aria-label={t("events.fillDetails.title")}>
      <p>{t("events.fillDetails.explanation")}</p>
      <dl className="research-run-facts">{([
        ["raw_open", "rawOpen"], ["execution_price", "executionPrice"],
        ["price_slippage", "priceSlippage"], ["research_settlement", "researchSettlement"],
        ["commission_cny", "commission"], ["stamp_duty_cny", "stampDuty"],
        ["transfer_fee_cny", "transferFee"], ["cost", "cost"],
        ["cash_rounding_delta", "cashRounding"],
      ] as const).map(([key, label]) => <div key={key}><dt>{t(`events.fillDetails.${label}`)}</dt>
        <dd>{new Decimal(String(row[key])).toString()}</dd></div>)}</dl>
    </section>}
    <div className="strategy-event-record-toolbar"><span>{t("events.raw")}</span>
      <button type="button" onClick={async () => {
        setCopyError(false);
        try { await navigator.clipboard.writeText(json); setCopied(true); }
        catch { setCopied(false); setCopyError(true); }
      }}>{copied ? t("events.copied") : t("events.copy")}</button>
    </div>
    {copyError && <p role="alert">{t("events.copyError")}</p>}
    <pre tabIndex={0} aria-label={t("events.rawJson")}>{json}</pre>
    <div className="strategy-event-links" aria-label={t("events.related")}>
      {targetId && section !== "strategy_targets" && <button type="button" onClick={() => navigate("strategy_targets", { target_id: targetId }, context)}>{t("events.viewTargets")}</button>}
      {section === "strategy_targets" && <button type="button" onClick={() => navigate("strategy_orders", { target_id: targetId }, context)}>{t("events.viewOrders")}</button>}
      {orderId && section !== "strategy_orders" && <button type="button" onClick={() => navigate("strategy_orders", { order_id: orderId }, context)}>{t("events.viewOrders")}</button>}
      {section === "strategy_orders" && <button type="button" onClick={() => navigate("strategy_child_orders", { order_id: orderId }, context)}>{t("events.viewChildren")}</button>}
      {["strategy_targets", "strategy_orders", "strategy_child_orders", "strategy_execution_constraints"].includes(section)
        && Object.values(linkedFills).some(Boolean) && <button type="button" onClick={() => navigate("strategy_fills", linkedFills, context)}>{t("events.viewFills")}</button>}
      {(section === "strategy_targets" || section === "strategy_orders") && <button type="button" onClick={() => navigate(
        "strategy_execution_constraints", section === "strategy_targets" ? { target_id: targetId } : { order_id: orderId }, context,
      )}>{t("events.viewConstraints")}</button>}
    </div>
  </div>;
}

export function StrategyEventTable({ rows, section, navigate }: {
  rows: EventRow[]; section: EventSection; navigate: Navigate;
}) {
  const { t } = useTranslation("analysis");
  const [expanded, setExpanded] = useState<string | null>(null);
  const prefix = useId();
  const selectedColumns = columns[section];
  return <div className="strategy-events-table-scroll" role="region" aria-label={t("events.records", { section: eventSectionLabel(section) })} tabIndex={0}>
    <table className="strategy-events-table" aria-label={eventSectionLabel(section)}>
      <thead><tr>{selectedColumns.map(column => <th key={column.key} scope="col" className={column.numeric ? "numeric" : undefined}>{t(column.label)}</th>)}
        <th scope="col"><span className="strategy-events-sr-only">{t("events.raw")}</span></th>
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
            <td className="strategy-event-expand"><button type="button" aria-label={t("events.viewRaw", { label })}
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
