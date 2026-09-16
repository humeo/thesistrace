import { useEffect, useRef, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import { StrategyEventTable, eventSections as sections, instrumentLabel, type EventRow, type EventSection as Section } from "./StrategyEventDetails";
import "./strategy-events.css";

type Page = { section: Section; status: "recorded" | "not_recorded" | "expired" | "partially_expired"; expires_at: string | null; rows: EventRow[]; next_cursor: string | null };
type Filter = { start_session?: string; end_session?: string; instrument_id?: string; target_id?: string; order_id?: string; child_order_id?: string };
type View = { section: Section; filters: Filter; cursors: (string | null)[]; scope: string | null };
const descriptions: Record<Section, string> = {
  strategy_targets: "收盘时形成的选股和仓位目标，日期为决策日。",
  strategy_orders: "回测生成的买卖委托，包括被拒绝的委托，日期为执行日。",
  strategy_child_orders: "按单笔交易数量规则拆分的模拟委托。",
  strategy_fills: "模拟成交的股数、价格和费用，可展开核对现金变化。",
  strategy_adjustments: "模拟交易以外的估值变化，包括停牌估值和退市核销。",
  strategy_execution_constraints: "资金或交易单位限制导致的缩量与跳过；提交股数不代表成交股数。",
};
function stockFilter(value: string) {
  const trimmed = value.trim();
  return /^\d{6}\.(SH|SZ)$/i.test(trimmed) ? "equity:" + trimmed.toUpperCase() : trimmed || undefined;
}

export function StrategyEvents({ endpoint }: { endpoint: string }) {
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<Section>("strategy_orders");
  const [filters, setFilters] = useState<Filter>({});
  const [draft, setDraft] = useState({ start_session: "", end_session: "", instrument_id: "" });
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [scope, setScope] = useState<string | null>(null);
  const [history, setHistory] = useState<View[]>([]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const focusAfterNavigation = useRef(false);
  const cursor = cursors[cursors.length - 1];
  const filtered = Object.values(filters).some(value => !!value);
  function navigate(next: Section, relation: Filter = {}, context: string | null = null) {
    setHistory(context ? [...history, { section, filters, cursors, scope }] : []);
    setScope(context);
    setPage(null); setSection(next); setFilters(relation); setCursors([null]);
    setDraft({ start_session: "", end_session: "", instrument_id: "" });
    focusAfterNavigation.current = true;
  }
  function goBack() {
    const previous = history.at(-1);
    if (!previous) return;
    setHistory(history.slice(0, -1));
    setSection(previous.section); setFilters(previous.filters); setCursors(previous.cursors); setScope(previous.scope);
    setDraft({ start_session: previous.filters.start_session ?? "", end_session: previous.filters.end_session ?? "", instrument_id: previous.filters.instrument_id ?? "" });
    setPage(null); focusAfterNavigation.current = true;
  }
  useEffect(() => {
    if (!open) return;
    if (focusAfterNavigation.current) {
      heading.current?.focus({ preventScroll: true });
      heading.current?.scrollIntoView({ block: "nearest" });
      focusAfterNavigation.current = false;
    }
    const controller = new AbortController();
    setPage(null); setError(null);
    void coreFetch(endpoint, {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ section, ...filters, cursor, limit: 20 }),
    }).then(async response => {
      if (!response.ok) throw new Error(response.status === 400
        ? "当前分页已失效，请重新加载首页。"
        : response.status === 422 ? "查询条件无效，请检查日期和股票代码。" : "记录加载失败，请重试。");
      const result = await response.json() as Page;
      if (!controller.signal.aborted) setPage(result);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "记录加载失败，请重试。");
    });
    return () => controller.abort();
  }, [open, endpoint, section, filters, cursor, revision]);
  return <details className="strategy-events" onToggle={event => {
    if (event.target === event.currentTarget) setOpen(event.currentTarget.open);
  }}>
    <summary><span>Trading events</span></summary>
    {open && <div className="strategy-events-content">
      <header className="strategy-events-heading">
        <h3 ref={heading} tabIndex={-1}>{sections[section]}</h3>
        <p>{descriptions[section]}</p>
        <p>交易明细保留 7 天，成功查看后续期；到期不影响收益报告和最终持仓。</p>
      </header>
      <form className="strategy-event-filters" onSubmit={event => {
        event.preventDefault(); setPage(null); setCursors([null]);
        setFilters({ ...filters, start_session: draft.start_session || undefined, end_session: draft.end_session || undefined, instrument_id: stockFilter(draft.instrument_id) });
        focusAfterNavigation.current = true;
      }}>
        <label>事件类型<select value={section} onChange={event => navigate(event.target.value as Section)}>
          {Object.entries(sections).map(([value, title]) => <option key={value} value={value}>{title}</option>)}
        </select></label>
        <label>起始日期<input type="date" value={draft.start_session} max={draft.end_session || undefined} onChange={event => setDraft({ ...draft, start_session: event.target.value })} /></label>
        <label>结束日期<input type="date" value={draft.end_session} min={draft.start_session || undefined} onChange={event => setDraft({ ...draft, end_session: event.target.value })} /></label>
        <label>股票代码<input value={draft.instrument_id} placeholder="600000.SH" onChange={event => setDraft({ ...draft, instrument_id: event.target.value })} /></label>
        <button type="submit">查询</button>
        <button type="button" disabled={!filtered && !draft.start_session && !draft.end_session && !draft.instrument_id} onClick={() => navigate(section)}>重置</button>
      </form>
      {scope && <div className="strategy-event-scope" role="region" aria-label="当前关联范围">
        <span>仅查看关联记录：{scope}</span>
        <div className="strategy-event-links">
          {history.length > 0 && <button type="button" onClick={goBack}>返回{sections[history.at(-1)!.section]}</button>}
          <button type="button" onClick={() => navigate(section)}>查看全部{sections[section]}</button>
        </div>
      </div>}
      <div className="strategy-events-status">
        <span>{filters.start_session || filters.end_session ? (filters.start_session ?? "最早") + " 至 " + (filters.end_session ?? "最新") : "全部日期"} · {filters.instrument_id ? instrumentLabel(filters.instrument_id) : "全部股票"}</span>
        <span>{section === "strategy_targets" ? "决策日期" : section === "strategy_adjustments" ? "调整日期" : "执行日期"} · 每页最多 20 条</span>
      </div>
      {page?.status === "partially_expired" && <p role="status">部分历史交易明细已过期，以下展示仍在保留期内的记录。</p>}
      {error ? <p role="alert">{error}</p> : page === null ? <p role="status">正在加载记录…</p>
        : page.status === "expired" ? <p role="status">交易明细已过期。连续 7 天未查看后自动清理，收益报告和最终持仓仍然保留。</p>
        : page.status === "not_recorded" ? <p>{section === "strategy_execution_constraints"
          ? "所选范围未完整记录执行约束，无法据此判断是否发生过资金或交易单位限制。"
          : "此结果未记录交易事件。"}</p>
        : page.rows.length === 0 ? <p>{"没有匹配的" + sections[section] + "记录。"}</p>
        : <StrategyEventTable key={section + ":" + JSON.stringify(filters) + ":" + cursor}
            section={section} rows={page.rows} navigate={navigate} />}
      <nav aria-label="交易事件分页">
        <span className="strategy-event-page-count" role="status">{(page?.status === "recorded" || page?.status === "partially_expired") && !error && <>本页 {page.rows.length} 条{!page.next_cursor && <span>{filtered ? "已到筛选结果末尾" : "已到末尾"}</span>}</>}</span>
        <button type="button" onClick={() => { setPage(null); setCursors([null]); setRevision(value => value + 1); focusAfterNavigation.current = true; }}>重新加载首页</button>
        <button type="button" disabled={cursors.length === 1 || !page} onClick={() => { setPage(null); setCursors(values => values.slice(0, -1)); focusAfterNavigation.current = true; }}>上一页</button>
        <span>第 {cursors.length} 页</span>
        <button type="button" disabled={!page?.next_cursor} onClick={() => { if (page?.next_cursor) { setCursors(values => [...values, page.next_cursor]); setPage(null); focusAfterNavigation.current = true; } }}>下一页</button>
      </nav>
    </div>}
  </details>;
}
