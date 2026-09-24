import { defaultSimulationCosts } from "./simulationCosts";
import { renderToStaticMarkup } from "react-dom/server";
import { highlightTree } from "@lezer/highlight";
import { describe, expect, it, vi } from "vitest";

import { alphaHighlightStyle, alphaLanguage } from "./alpha-language";
import { createDiagnosticsScheduler, type DiagnosticState } from "./diagnostics";
import {
  emptyResearchDraft,
  acceptPendingResearchRun,
  beginResearchRun,
  finishResearchRun,
  hasUnexecutedChanges,
  isCompleteResearchInputs,
  isValidInitialCash,
  loadResearchDraft,
  persistResearchDraft,
  researchDraftKey,
  researchInputs,
  selectResearchKind,
  selectStrategyMode,
  useResearchAsDraft,
} from "./draft";
import {
  ResearchDraftWorkspace,
  ResearchFolderNavigation,
} from "./ResearchWorkspacePage";
import { buildResearchDatePresets } from "./dateRange";
import { parseProgramParameters } from "./pythonStrategy";
import { builtinFrameworkModules } from "./frameworkModules";

describe("Python parameter JSON", () => {
  it.each(['{"threshold": 1e999}', '{"x": 9007199254740992}', '{"x": "\\ud800"}',
    '{"x": ' + '['.repeat(33) + '0' + ']'.repeat(33) + '}'])
  ("rejects %s before serialization can change its meaning", source => {
    expect(() => parseProgramParameters(source)).toThrow();
  });
});

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();
  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  getItem(key: string) { return this.values.get(key) ?? null; }
  key(index: number) { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string) { this.values.delete(key); }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

const folder = { id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-13T00:00:00Z" };
const researcherId = "00000000-0000-4000-8000-000000000001";
const catalog = {
  generation_manifest_sha256: "a".repeat(64),
  fields: [
    {
      identifier: "close",
      field_id: "price.close.adjusted",
      value_type: "numeric_series" as const,
      description: "Adjusted close",
      unit: "CNY",
      family_id: "equity.eod_price",
      research_category: "market" as const,
      display_name: "复权收盘价",
      research_purpose: "行情",
      source_unit: "CNY/share",
      source_endpoint: "daily",
      source_column: "close",
      source_lineage: "tushare.daily",
      reporting_scope: "market-observation",
      availability: "after_close",
      report_period_selection: "research-session",
      applicable_company_types: [],
      missingness: "missing_when_no_valid_session_bar",
      example: "rank(close)",
    },
    {
      identifier: "revenue",
      field_id: "financial.income.total_revenue.latest_fy",
      value_type: "numeric_series" as const,
      description: "Latest visible full-year consolidated total revenue",
      unit: "CNY",
      family_id: "equity.financial_pit",
      research_category: "financial" as const,
      display_name: "营业总收入",
      research_purpose: "盈利",
      source_unit: "CNY",
      source_endpoint: "income",
      source_column: "total_revenue",
      source_lineage: "tushare.income.total_revenue",
      reporting_scope: "report_type_1_consolidated",
      availability: "next_research_session_after_source_publication",
      report_period_selection: "latest_visible_full_year",
      applicable_company_types: ["1", "2", "3", "4"],
      missingness: "missing_when_no_visible_eligible_fact",
      example: "rank(revenue)",
    },
  ],
  industries: [], builtins: [{
    identifier: "ts_mean",
    parameters: [{ name: "value", value_type: "numeric_series", minimum: null, maximum: null }],
    result_type: "same_as_first",
    description: "Rolling mean",
    examples: ["ts_mean(close, 20)"],
    missing_value_behavior: "Missing remains missing",
    numeric_behavior: "Finite numeric result",
  }],
};
const data = {
  generation_manifest_sha256: "a".repeat(64),
  available_field_ids: ["price.close.adjusted"],
  field_families: [],
  market_coverage: { start: "2025-01-01", end: "2026-08-12" },
  financial_coverage: null,
  industry_coverage: null,
  benchmark_coverage: null,
  benchmark_snapshot_sha256: null,
  benchmark_last_published_at: null,
  data_through_session: "2026-08-12",
  last_market_refresh_at: "2026-08-13T00:00:00Z",
  last_financial_refresh_at: null,
  last_industry_refresh_at: null,
  industry_refresh_status: null,
  industry_refresh_failure_code: null,
  market_research_readiness: true,
  benchmark_research_readiness: false,
  financial_research_readiness: "not_ready" as const,
  industry_research_readiness: false,
};

describe("browser Research Draft", () => {
  it("defaults new work to Factor Evaluation and submits only its authorable contract", () => {
    const draft = {
      ...emptyResearchDraft(),
      formula: "close",
      startDate: "2026-08-03",
      endDate: "2026-08-05",
      universe: "top300",
      neutralization: "none",
    };

    expect(draft.researchKind).toBe("factor_evaluation");
    expect(isCompleteResearchInputs(draft)).toBe(true);
    expect(isCompleteResearchInputs({ ...draft, hypothesis: "📚".repeat(1024) })).toBe(true);
    expect(isCompleteResearchInputs({ ...draft, hypothesis: "📚".repeat(1025) })).toBe(false);
    const begun = beginResearchRun(draft, folder.id, () => "factor-request");
    expect(begun.command).toEqual({
      request_id: "factor-request",
      folder_id: folder.id,
      name: null,
      formula: "close",
      hypothesis: null,
      start_date: "2026-08-03",
      end_date: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      research_kind: "factor_evaluation",
    });
    expect(begun.command).not.toHaveProperty("holdings_count");
    expect(begun.command).not.toHaveProperty("selection_every_sessions");
  });

  it("clears Strategy-only values when Factor Evaluation is selected", () => {
    const strategy = {
      ...emptyResearchDraft(),
      researchKind: "strategy_backtest" as const,
      holdingsCount: "25",
      initialCashCny: "100000",
      selectionEverySessions: "5",
    };

    expect(selectResearchKind(strategy, "factor_evaluation")).toMatchObject({
      researchKind: "factor_evaluation",
      holdingsCount: "",
      initialCashCny: "",
      selectionEverySessions: "",
    });
    expect(selectResearchKind(emptyResearchDraft(), "strategy_backtest")).toMatchObject({
      researchKind: "strategy_backtest",
      holdingsCount: "10",
      initialCashCny: "100000",
      selectionEverySessions: "5",
    });
  });

  it("requires valid Strategy inputs and changes pending identity when Research Kind changes", () => {
    const common = {
      ...emptyResearchDraft(),
      formula: "close",
      startDate: "2026-08-03",
      endDate: "2026-08-05",
      universe: "top300",
      neutralization: "none",
    };
    const factor = beginResearchRun(common, folder.id, () => "factor-request");
    const defaultStrategy = selectResearchKind(factor.draft, "strategy_backtest");
    expect(isCompleteResearchInputs(defaultStrategy)).toBe(true);
    const incompleteStrategy = { ...defaultStrategy, initialCashCny: "" };
    expect(isCompleteResearchInputs(incompleteStrategy)).toBe(false);
    const strategy = {
      ...incompleteStrategy,
      holdingsCount: "10",
      initialCashCny: "100000",
      selectionEverySessions: "2",
    };
    expect(isCompleteResearchInputs(strategy)).toBe(true);
    const begun = beginResearchRun(strategy, folder.id, () => "strategy-request");
    expect(begun.command).toMatchObject({
      request_id: "strategy-request",
      research_kind: "strategy_backtest", strategy_mode: "framework", modules: builtinFrameworkModules,
      holdings_count: 10,
      initial_cash_cny: "100000", costs: defaultSimulationCosts(),
      selection_every_sessions: 2,
      exposure_expression: "1",
      weighting: "equal_weight", volatility_window: 20,
    });
  });

  it("parses formula structure for language-driven syntax highlighting", () => {
    const formula = "rank(pct_change(close, 20)) + 1 * 2";
    const tree = alphaLanguage.parser.parse(formula);

    expect(tree.toString()).toBe(
      "Formula(Expression(BinaryExpression(Expression(CallExpression(FunctionName(Identifier),ArgumentList(Expression(CallExpression(FunctionName(Identifier),ArgumentList(Expression(FieldName(Identifier)),Expression(Number))))))),AddOperator,Expression(BinaryExpression(Expression(Number),MultiplyOperator,Expression(Number))))))",
    );
    const highlights: Array<[string, string]> = [];
    highlightTree(tree, alphaHighlightStyle, (from, to, classes) => {
      highlights.push([formula.slice(from, to), classes]);
    });
    expect(highlights).toEqual([
      ["rank", "cm-alpha-function"],
      ["pct_change", "cm-alpha-function"],
      ["close", "cm-alpha-field"],
      ["20", "cm-alpha-number"],
      ["+", "cm-alpha-operator"],
      ["1", "cm-alpha-number"],
      ["*", "cm-alpha-operator"],
      ["2", "cm-alpha-number"],
    ]);
  });

  it("copies frozen authorable values into only the chosen Folder Draft", () => {
    const storage = new MemoryStorage();
    persistResearchDraft(storage, researcherId, "folder_target", {
      ...emptyResearchDraft(),
      name: "Keep prospective name",
      formula: "volume",
      lastAdmittedBaseline: {
        ...emptyResearchDraft(),
        name: "Keep prospective name",
        formula: "volume",
      },
    });
    persistResearchDraft(storage, researcherId, "folder_other", {
      ...emptyResearchDraft(),
      formula: "open",
    });
    const otherBefore = storage.getItem(researchDraftKey(researcherId, "folder_other"));

    const confirmDiscard = vi.fn(() => false);
    const frozenCosts = { ...defaultSimulationCosts(), commission_min_cny: "2", slippage_bps: "15" };
    const copied = useResearchAsDraft(storage, researcherId, "folder_target", {
      formula: "ts_mean(close, 20)",
      hypothesis: "Frozen hypothesis",
      start_date: "2026-08-03",
      end_date: "2026-08-05",
      universe: "top1000",
      neutralization: "industry",
      research_kind: "strategy_backtest", strategy_mode: "framework", modules: builtinFrameworkModules,
      holdings_count: 25,
      initial_cash_cny: "100000", costs: frozenCosts,
      selection_every_sessions: 5,
      exposure_expression: "1",
      weighting: "equal_weight", volatility_window: 20,
    }, confirmDiscard);

    expect(copied).toBe(true);
    expect(confirmDiscard).not.toHaveBeenCalled();
    expect(loadResearchDraft(storage, researcherId, "folder_target")).toMatchObject({
      name: "Keep prospective name",
      formula: "ts_mean(close, 20)",
      hypothesis: "Frozen hypothesis",
      startDate: "2026-08-03",
      endDate: "2026-08-05",
      universe: "top1000",
      neutralization: "industry",
      holdingsCount: "25",
      initialCashCny: "100000",
      costs: frozenCosts,
      selectionEverySessions: "5",
      editor: { anchor: 18, head: 18 },
      pendingAdmission: null,
    });
    const edited = loadResearchDraft(storage, researcherId, "folder_target");
    edited.costs.slippage_bps = "20";
    persistResearchDraft(storage, researcherId, "folder_target", edited);
    expect(frozenCosts.slippage_bps).toBe("15");
    expect(storage.getItem(researchDraftKey(researcherId, "folder_other"))).toBe(otherBefore);
  });

  it("reuses Factor Evaluation without retaining Strategy-only values", () => {
    const storage = new MemoryStorage();
    persistResearchDraft(storage, researcherId, folder.id, {
      ...emptyResearchDraft(),
      researchKind: "strategy_backtest",
      holdingsCount: "25",
      initialCashCny: "100000",
      selectionEverySessions: "5",
    });

    expect(useResearchAsDraft(storage, researcherId, folder.id, {
      formula: "rank(close)",
      hypothesis: null,
      start_date: "2026-08-03",
      end_date: "2026-08-05",
      universe: "top300",
      neutralization: "industry",
      research_kind: "factor_evaluation",
    }, () => true)).toBe(true);
    expect(loadResearchDraft(storage, researcherId, folder.id)).toMatchObject({
      researchKind: "factor_evaluation",
      formula: "rank(close)",
      holdingsCount: "",
      initialCashCny: "",
      selectionEverySessions: "",
      pendingAdmission: null,
    });
  });

  it("copies a Batch Research child into an ordinary browser Draft", () => {
    const storage = new MemoryStorage();

    expect(useResearchAsDraft(storage, researcherId, "folder_batch_research", {
      formula: "rank(close)",
      hypothesis: "Batch hypothesis",
      start_date: "2026-08-03",
      end_date: "2026-08-05",
      universe: "top1000",
      neutralization: "industry",
      research_kind: "strategy_backtest", strategy_mode: "framework", modules: builtinFrameworkModules,
      holdings_count: 25,
      initial_cash_cny: "100000", costs: defaultSimulationCosts(),
      selection_every_sessions: 5,
      exposure_expression: "1",
      weighting: "equal_weight", volatility_window: 20,
    }, () => true)).toBe(true);

    expect(loadResearchDraft(storage, researcherId, "folder_batch_research")).toMatchObject({
      researchKind: "strategy_backtest",
      formula: "rank(close)",
      hypothesis: "Batch hypothesis",
      startDate: "2026-08-03",
      endDate: "2026-08-05",
      universe: "top1000",
      neutralization: "industry",
      holdingsCount: "25",
      initialCashCny: "100000",
      selectionEverySessions: "5",
      pendingAdmission: null,
    });
  });

  it("requires confirmation only before overwriting unexecuted local values", () => {
    const storage = new MemoryStorage();
    const target = {
      ...emptyResearchDraft(),
      formula: "volume",
    };
    persistResearchDraft(storage, researcherId, "folder_target", target);
    const confirmDiscard = vi.fn(() => false);

    const copied = useResearchAsDraft(storage, researcherId, "folder_target", {
      formula: "close",
      hypothesis: null,
      start_date: "2026-08-03",
      end_date: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      research_kind: "strategy_backtest", strategy_mode: "framework", modules: builtinFrameworkModules,
      holdings_count: 10,
      initial_cash_cny: "100000", costs: defaultSimulationCosts(),
      selection_every_sessions: 2,
      exposure_expression: "1",
      weighting: "equal_weight", volatility_window: 20,
    }, confirmDiscard);

    expect(copied).toBe(false);
    expect(confirmDiscard).toHaveBeenCalledOnce();
    expect(loadResearchDraft(storage, researcherId, "folder_target")).toEqual(target);
  });

  it("reuses one request ID for the same pending snapshot and preserves later edits on acceptance", () => {
    const initial = {
      ...emptyResearchDraft(),
      name: "Mean",
      formula: "ts_mean(close, 20)",
      startDate: "2026-08-03",
      endDate: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      researchKind: "strategy_backtest" as const,
      holdingsCount: "10",
      initialCashCny: "100000",
      selectionEverySessions: "2",
    };
    const first = beginResearchRun(initial, "folder_default", () => "run-request-1");
    const retry = beginResearchRun(first.draft, "folder_default", () => "run-request-2");

    expect(retry.command).toEqual(first.command);
    expect(first.command).toMatchObject({
      request_id: "run-request-1",
      folder_id: "folder_default",
      name: "Mean",
      formula: "ts_mean(close, 20)",
      start_date: "2026-08-03",
      end_date: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      research_kind: "strategy_backtest", strategy_mode: "framework", modules: builtinFrameworkModules,
      holdings_count: 10,
      initial_cash_cny: "100000", costs: defaultSimulationCosts(),
      selection_every_sessions: 2,
      exposure_expression: "1",
      weighting: "equal_weight", volatility_window: 20,
    });

    const editedWhilePending = { ...first.draft, formula: "ts_mean(close, 60)" };
    const accepted = acceptPendingResearchRun(editedWhilePending, "run-request-1");
    expect(accepted.formula).toBe("ts_mean(close, 60)");
    expect(accepted.lastAdmittedBaseline?.formula).toBe("ts_mean(close, 20)");
    expect(accepted.pendingAdmission).toBeNull();
    expect(hasUnexecutedChanges(accepted)).toBe(true);
  });

  it("persists the latest pending edit and accepted baseline before navigation", () => {
    const storage = new MemoryStorage();
    const initial = {
      ...emptyResearchDraft(),
      formula: "ts_mean(close, 2)",
      startDate: "2026-08-04",
      endDate: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      holdingsCount: "10",
      initialCashCny: "100000",
      selectionEverySessions: "2",
    };
    const begun = beginResearchRun(initial, folder.id, () => "run-request-1");
    persistResearchDraft(storage, researcherId, folder.id, {
      ...begun.draft,
      formula: "ts_mean(close, 3)",
    });

    const finished = finishResearchRun(storage, researcherId, folder.id, "run-request-1");
    expect(finished).not.toBeNull();
    if (finished === null) throw new Error("Accepted Research was not finished");
    expect(finished.formula).toBe("ts_mean(close, 3)");
    expect(finished.lastAdmittedBaseline?.formula).toBe("ts_mean(close, 2)");
    expect(loadResearchDraft(storage, researcherId, folder.id)).toEqual(finished);
  });

  it("does not accept or persist a stale response after its pending Draft was replaced", () => {
    const storage = new MemoryStorage();
    const replacement = { ...emptyResearchDraft(), formula: "close" };
    persistResearchDraft(storage, researcherId, folder.id, replacement);

    expect(finishResearchRun(storage, researcherId, folder.id, "stale-request")).toBeNull();
    expect(loadResearchDraft(storage, researcherId, folder.id)).toEqual(replacement);
  });

  it("opens empty when its one Folder key is absent and round-trips the bounded payload", () => {
    const storage = new MemoryStorage();
    const empty = loadResearchDraft(storage, researcherId, folder.id);
    expect(empty).toEqual(emptyResearchDraft());
    expect(storage.length).toBe(0);

    const draft = { ...empty, name: "Mean reversion", formula: "ts_mean(close, 20)", editor: { anchor: 8, head: 8 } };
    persistResearchDraft(storage, researcherId, folder.id, draft);
    expect(storage.length).toBe(1);
    expect(storage.key(0)).toBe(researchDraftKey(researcherId, folder.id));
    expect(loadResearchDraft(storage, researcherId, folder.id)).toEqual(draft);
  });

  it("keeps independent Draft values under distinct Folder keys", () => {
    const storage = new MemoryStorage();
    persistResearchDraft(storage, researcherId, "folder_default", { ...emptyResearchDraft(), formula: "close" });
    persistResearchDraft(storage, researcherId, "folder_signals", { ...emptyResearchDraft(), formula: "volume" });

    expect(loadResearchDraft(storage, researcherId, "folder_default").formula).toBe("close");
    expect(loadResearchDraft(storage, researcherId, "folder_signals").formula).toBe("volume");
    storage.removeItem(researchDraftKey(researcherId, "folder_signals"));
    expect(loadResearchDraft(storage, researcherId, "folder_default").formula).toBe("close");
    expect(loadResearchDraft(storage, researcherId, "folder_signals")).toEqual(emptyResearchDraft());
  });

  it("requires confirmation only when New would discard unexecuted inputs", () => {
    expect(hasUnexecutedChanges(emptyResearchDraft())).toBe(false);
    expect(hasUnexecutedChanges({ ...emptyResearchDraft(), formula: "close" })).toBe(true);
    const admitted = { ...emptyResearchDraft(), formula: "close" };
    expect(hasUnexecutedChanges({ ...admitted, lastAdmittedBaseline: researchInputs(admitted) })).toBe(false);
  });

  it("renders the DSL as the only Alpha surface without server-edit controls", () => {
    const markup = renderToStaticMarkup(<ResearchDraftWorkspace catalog={catalog} data={data} folder={folder} researcherId={researcherId} storage={new MemoryStorage()} />);
    expect(markup).toContain("Alpha formula editor");
    expect(markup).toContain('class="formula-workbench"');
    expect(markup).toContain('id="alpha-formula-title">Alpha formula</h2>');
    expect(markup).toContain("Draft name");
    expect(markup).toContain("New research");
    expect(markup).toContain('autoComplete="off"');

    expect(markup).toContain("Run evaluation");
    expect(markup).toContain('aria-controls="research-parameters"');
    expect(markup).toContain('class="visually-hidden">Research type</legend>');
    expect(markup).not.toContain("Research period");
    expect(markup).toContain('name="research-kind"');
    expect(markup).toMatch(/<input[^>]*checked=""[^>]*value="factor_evaluation"/);
    expect(markup).toContain("Factor Evaluation");
    expect(markup).toContain("Strategy Backtest");
    expect(markup).not.toContain("Holdings count");
    expect(markup).not.toContain("Selection interval (trading days)");
    expect(markup).toContain('aria-label="Open start date calendar"');
    expect(markup).toContain('aria-label="Open end date calendar"');
    expect(markup).toContain('aria-label="Use last 1 year"');
    expect(markup).toContain('aria-label="Use all available data"');
    expect(markup).toContain('for="research-notes">Notes</label>');
    expect(markup).not.toContain("context-disclosure");
    expect(markup).not.toContain("formula-validity");
    expect(markup).not.toContain("run-settings-link");
    expect(markup).not.toContain("Close run settings");
    expect(markup).not.toContain(">Cancel<");
    expect(markup).not.toContain("Saved in this browser");
    expect(markup).not.toContain("Financial fields");
    expect(markup).not.toContain("revenue");
    for (const removed of ["Save Research", "Refresh", "Revision", "Definition", "Add Alpha"]) expect(markup).not.toContain(removed);
  });

  it("builds exact data-bounded quick date ranges", () => {
    expect(buildResearchDatePresets("2010-01-04", "2026-08-13")).toEqual([
      { label: "1Y", accessibleLabel: "Use last 1 year", startDate: "2025-08-13", endDate: "2026-08-13" },
      { label: "3Y", accessibleLabel: "Use last 3 years", startDate: "2023-08-13", endDate: "2026-08-13" },
      { label: "5Y", accessibleLabel: "Use last 5 years", startDate: "2021-08-13", endDate: "2026-08-13" },
      { label: "Max", accessibleLabel: "Use all available data", startDate: "2010-01-04", endDate: "2026-08-13" },
    ]);
    expect(buildResearchDatePresets("2024-01-01", "2024-02-29")[0]).toMatchObject({
      startDate: null,
      endDate: null,
    });
    expect(buildResearchDatePresets("2020-01-01", "2024-02-29")[0]).toMatchObject({
      startDate: "2023-02-28",
      endDate: "2024-02-29",
    });
  });

  it("renders required bounded Strategy inputs only for Strategy Backtest", () => {
    const storage = new MemoryStorage();
    persistResearchDraft(storage, researcherId, folder.id, {
      ...emptyResearchDraft(),
      researchKind: "strategy_backtest",
    });

    const markup = renderToStaticMarkup(
      <ResearchDraftWorkspace catalog={catalog} data={data} folder={folder} researcherId={researcherId} storage={storage} />,
    );
    expect(markup).toMatch(/<input[^>]*checked=""[^>]*value="strategy_backtest"/);
    expect(markup).toContain("Holdings count");
    expect(markup).toContain("Selection interval (trading days)");
    expect(markup.match(/required="" step="1" type="number"/g)).toHaveLength(2);
    expect(markup).toMatch(/<input[^>]*id="research-holdings-count"[^>]*max="100"[^>]*min="1"[^>]*required=""[^>]*step="1"[^>]*type="number"/);
    expect(markup).toMatch(/<input[^>]*id="research-selection-sessions"[^>]*max="20"[^>]*min="1"[^>]*required=""[^>]*step="1"[^>]*type="number"/);
    expect(markup).toContain('aria-label="Decrease number of holdings" disabled=""');
    expect(markup).toContain('aria-label="Increase number of holdings"');
    expect(markup).toContain('aria-label="Decrease selection interval" disabled=""');
    expect(markup).toContain('aria-label="Increase selection interval"');
  });

  it("enables Run for one complete retained Draft", () => {
    const storage = new MemoryStorage();
    persistResearchDraft(storage, researcherId, folder.id, {
      ...emptyResearchDraft(),
      formula: "close",
      startDate: "2026-08-03",
      endDate: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      holdingsCount: "10",
      initialCashCny: "100000",
      selectionEverySessions: "2",
    });

    const markup = renderToStaticMarkup(
      <ResearchDraftWorkspace catalog={catalog} data={data} folder={folder} researcherId={researcherId} storage={storage} />,
    );
    expect(markup).toContain("Run evaluation");
    expect(markup).not.toContain('disabled="" type="button"><svg');
  });

  it("renders one-level Folder navigation and protects Default management actions", () => {
    const custom = { ...folder, id: "folder_signals", name: "Signals", is_default: false };
    const markup = renderToStaticMarkup(
      <ResearchFolderNavigation
        activeFolder={folder}
        error={null}
        folders={[folder, custom]}
        onCreate={async () => undefined}
        onDelete={async () => undefined}
        onRename={async () => undefined}
      />,
    );
    expect(markup).toContain('href="/research"');
    expect(markup).toContain('href="/research?folder=folder_signals"');
    expect(markup).toContain("Folder");
    expect(markup).toContain("Signals");
    expect(markup).not.toContain("Rename Folder");
    expect(markup).not.toContain("Delete Folder");
  });
});

describe("formula diagnostics scheduling", () => {
  it("ignores an older response after a newer Formula request", async () => {
    vi.useFakeTimers();
    const resolvers: Array<(response: Response) => void> = [];
    const request = vi.fn(() => new Promise<Response>((resolve) => resolvers.push(resolve)));
    const states: DiagnosticState[] = [];
    const scheduler = createDiagnosticsScheduler(request as typeof fetch, 10);

    scheduler.diagnose("close", (state) => states.push(state));
    await vi.advanceTimersByTimeAsync(10);
    scheduler.diagnose("ts_mean(close, 20)", (state) => states.push(state));
    await vi.advanceTimersByTimeAsync(10);
    resolvers[1](new Response(JSON.stringify({ valid: true, diagnostics: [] }), { status: 200 }));
    await flushPromises();
    resolvers[0](new Response(JSON.stringify({ valid: false, diagnostics: [] }), { status: 200 }));
    await flushPromises();

    expect(states.at(-1)).toEqual({ kind: "complete", result: { valid: true, diagnostics: [] } });
    scheduler.dispose();
    vi.useRealTimers();
  });

  it("never represents a network failure as valid", async () => {
    vi.useFakeTimers();
    const states: DiagnosticState[] = [];
    const scheduler = createDiagnosticsScheduler(vi.fn(async () => { throw new Error("offline"); }) as typeof fetch, 10);
    scheduler.diagnose("close", (state) => states.push(state));
    await vi.advanceTimersByTimeAsync(10);
    await Promise.resolve();
    expect(states.at(-1)).toEqual({ kind: "unavailable", result: null });
    scheduler.dispose();
    vi.useRealTimers();
  });
});

async function flushPromises(): Promise<void> {
  for (let index = 0; index < 5; index += 1) await Promise.resolve();
}


it.each([
  ["0.01", true], ["1000000000.00", true], ["00100000.00", true],
  ["0", false], ["1000000000.01", false], ["1.001", false],
  ["10000000000000000000000000000000001", false],
])("validates exact CNY amount %s", (cash, valid) => {
  expect(isValidInitialCash(cash as string)).toBe(valid);
});


it("freezes the single Exposure source and renews pending identity when it changes", () => {
  const draft = {
    ...emptyResearchDraft(), researchKind: "strategy_backtest" as const,
    formula: "close", startDate: "2026-08-03", endDate: "2026-08-05",
    universe: "top300", neutralization: "none", initialCashCny: "100000",
    holdingsCount: "10", selectionEverySessions: "5", exposureExpression: "7 / 10",
  };
  const first = beginResearchRun(draft, "folder_default", () => "first");
  expect(first.command).toMatchObject({ exposure_expression: "7 / 10" });
  const second = beginResearchRun(
    { ...first.draft, exposureExpression: "0" }, "folder_default", () => "second",
  );
  expect(second.command).toMatchObject({ request_id: "second", exposure_expression: "0" });
  const factor = beginResearchRun(
    selectResearchKind(second.draft, "factor_evaluation"), "folder_default", () => "factor",
  );
  expect(factor.command).not.toHaveProperty("exposure_expression");
  expect(emptyResearchDraft().exposureExpression).toBe("1");
});


it("restores a frozen Exposure source exactly when reusing a Run as a draft", () => {
  const storage = new MemoryStorage();
  expect(useResearchAsDraft(storage, "exposure", "folder_default", {
    research_kind: "strategy_backtest", strategy_mode: "framework", modules: builtinFrameworkModules, formula: "close", hypothesis: null,
    start_date: "2026-08-03", end_date: "2026-08-05", universe: "top300", neutralization: "none",
    initial_cash_cny: "100000", costs: defaultSimulationCosts(), holdings_count: 10, selection_every_sessions: 5,
    exposure_expression: "7 / 10",
    weighting: "equal_weight", volatility_window: 20,
  }, () => false)).toBe(true);
  const restored = loadResearchDraft(storage, "exposure", "folder_default");
  expect(restored.exposureExpression).toBe("7 / 10");
  expect(beginResearchRun(restored, "folder_default", () => "reuse").command)
    .toMatchObject({ exposure_expression: "7 / 10" });
});


describe("Direct Python authoring", () => {
  it("reuses and reloads legal parameters whose formatted text exceeds 64 KiB", () => {
    const parameters = Object.fromEntries(Array.from({ length: 3500 }, (_, i) =>
      [`key${String(i).padStart(4, "0")}`, "value"]));
    expect(JSON.stringify(parameters).length).toBeLessThan(65536);
    const formatted = JSON.stringify(parameters, null, 2);
    expect(formatted.length).toBeGreaterThan(65536);
    const draft = { ...selectStrategyMode(selectResearchKind(emptyResearchDraft(), "strategy_backtest"), "direct"),
      startDate: "2026-08-03", endDate: "2026-08-05", universe: "top300", programParameters: formatted };
    expect(isCompleteResearchInputs(draft)).toBe(true);
    const storage = new MemoryStorage();
    persistResearchDraft(storage, researcherId, folder.id, draft);
    expect(loadResearchDraft(storage, researcherId, folder.id).programParameters).toBe(formatted);
    const { command } = beginResearchRun(draft, folder.id, () => "large-parameters");
    if (command.research_kind !== "strategy_backtest" || command.strategy_mode !== "direct") throw new Error("Direct expected");
    expect(useResearchAsDraft(storage, researcherId, folder.id, {
      ...command, universe: "top300",
    }, () => true)).toBe(true);
    const restored = loadResearchDraft(storage, researcherId, folder.id);
    expect(restored.strategyMode).toBe("direct");
    expect(restored.programSource).toBe(draft.programSource);
    expect(JSON.parse(restored.programParameters)).toEqual(parameters);
  });

  it("switches the active strategy, submits only Python, and restores its frozen draft", () => {
    const framework = { ...selectResearchKind(emptyResearchDraft(), "strategy_backtest"),
      formula: "close", startDate: "2026-08-03", endDate: "2026-08-05", universe: "top300" };
    const draft = selectStrategyMode(framework, "direct");
    expect(draft.formula).toBe("");
    expect(isCompleteResearchInputs(draft)).toBe(true);
    const { command } = beginResearchRun(draft, folder.id, () => "direct-one");
    expect(command).toHaveProperty("strategy_mode", "direct");
    expect(command).not.toHaveProperty("formula");
    expect(command).not.toHaveProperty("neutralization");
    expect(command).not.toHaveProperty("holdings_count");
    expect(command).not.toHaveProperty("selection_every_sessions");
    if (command.research_kind !== "strategy_backtest" || command.strategy_mode !== "direct") throw new Error("Direct expected");
    const storage = new MemoryStorage();
    expect(useResearchAsDraft(storage, researcherId, folder.id, {
      ...command, universe: "top300",
    }, () => true)).toBe(true);
    const restored = loadResearchDraft(storage, researcherId, folder.id);
    expect(restored.programSource).toBe(draft.programSource);
    expect(JSON.parse(restored.programParameters)).toEqual(command.program.parameters);
    const switched = selectStrategyMode(restored, "framework");
    expect(switched.programSource).toBe("");
    expect(switched.programParameters).toBe("");
    expect(switched.holdingsCount).toBe("10");
  });

  it("keeps incomplete Python parameters editable and explains the invalid field", () => {
    const draft = { ...selectStrategyMode(selectResearchKind(emptyResearchDraft(), "strategy_backtest"), "direct"),
      startDate: "2026-08-03", endDate: "2026-08-05", universe: "top300", programParameters: "{" };
    const storage = new MemoryStorage();
    persistResearchDraft(storage, researcherId, folder.id, draft);
    expect(loadResearchDraft(storage, researcherId, folder.id).programParameters).toBe("{");
    expect(isCompleteResearchInputs(draft)).toBe(false);
    const markup = renderToStaticMarkup(<ResearchDraftWorkspace researcherId={researcherId} folder={folder} catalog={catalog} data={data} storage={storage} />);
    expect(markup).toContain("Python source");
    expect(markup).toContain("Parameters (JSON)");
    expect(markup).toContain("Declared fields");
    expect(markup).not.toContain('id="research-holdings-count"');
    expect(markup).not.toContain("Alpha formula");
    expect(markup).not.toContain("Framework · Built-in strategy. Decide");
  });
});
