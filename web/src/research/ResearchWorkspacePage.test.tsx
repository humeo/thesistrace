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
  loadResearchDraft,
  persistResearchDraft,
  researchDraftKey,
  selectResearchKind,
  useResearchAsDraft,
} from "./draft";
import {
  ResearchDraftWorkspace,
  ResearchFolderNavigation,
} from "./ResearchWorkspacePage";
import { buildResearchDatePresets } from "./dateRange";

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
const catalog = {
  fields: [
    {
      identifier: "close",
      field_id: "price.close.adjusted",
      value_type: "numeric_series" as const,
      description: "Adjusted close",
      unit: "CNY",
      family_id: "equity.eod_price",
      availability: "after_close",
      report_period_selection: "research-session",
      applicable_company_types: [],
      missingness: "missing_when_no_valid_session_bar",
      example: "cs_rank(close)",
    },
    {
      identifier: "total_revenue_latest_fy",
      field_id: "financial.income.total_revenue.latest_fy",
      value_type: "numeric_series" as const,
      description: "Latest visible full-year consolidated total revenue",
      unit: "CNY",
      family_id: "equity.financial_pit",
      availability: "next_research_session_after_source_publication",
      report_period_selection: "latest_visible_full_year",
      applicable_company_types: ["1", "2", "3", "4"],
      missingness: "missing_when_no_visible_eligible_fact",
      example: "cs_rank(total_revenue_latest_fy)",
    },
  ],
  builtins: [{
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
  market_coverage: { start: "2025-01-01", end: "2026-08-12" },
  financial_coverage: null,
  data_through_session: "2026-08-12",
  last_market_refresh_at: "2026-08-13T00:00:00Z",
  last_financial_refresh_at: null,
  market_research_readiness: true,
  financial_research_readiness: false,
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
    expect(begun.command).not.toHaveProperty("rebalance_every_sessions");
  });

  it("clears Strategy-only values when Factor Evaluation is selected", () => {
    const strategy = {
      ...emptyResearchDraft(),
      researchKind: "strategy_backtest" as const,
      holdingsCount: "25",
      rebalanceEverySessions: "5",
    };

    expect(selectResearchKind(strategy, "factor_evaluation")).toMatchObject({
      researchKind: "factor_evaluation",
      holdingsCount: "",
      rebalanceEverySessions: "",
    });
    expect(selectResearchKind(emptyResearchDraft(), "strategy_backtest")).toMatchObject({
      researchKind: "strategy_backtest",
      holdingsCount: "",
      rebalanceEverySessions: "",
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
    const incompleteStrategy = selectResearchKind(factor.draft, "strategy_backtest");
    expect(isCompleteResearchInputs(incompleteStrategy)).toBe(false);
    const strategy = {
      ...incompleteStrategy,
      holdingsCount: "10",
      rebalanceEverySessions: "2",
    };
    expect(isCompleteResearchInputs(strategy)).toBe(true);
    const begun = beginResearchRun(strategy, folder.id, () => "strategy-request");
    expect(begun.command).toMatchObject({
      request_id: "strategy-request",
      research_kind: "strategy_backtest",
      holdings_count: 10,
      rebalance_every_sessions: 2,
    });
  });

  it("parses formula structure for language-driven syntax highlighting", () => {
    const formula = "cs_rank(pct_change(close, 20)) + 1 * 2";
    const tree = alphaLanguage.parser.parse(formula);

    expect(tree.toString()).toBe(
      "Formula(Expression(BinaryExpression(Expression(CallExpression(FunctionName(Identifier),ArgumentList(Expression(CallExpression(FunctionName(Identifier),ArgumentList(Expression(FieldName(Identifier)),Expression(Number))))))),AddOperator,Expression(BinaryExpression(Expression(Number),MultiplyOperator,Expression(Number))))))",
    );
    const highlights: Array<[string, string]> = [];
    highlightTree(tree, alphaHighlightStyle, (from, to, classes) => {
      highlights.push([formula.slice(from, to), classes]);
    });
    expect(highlights).toEqual([
      ["cs_rank", "cm-alpha-function"],
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
    persistResearchDraft(storage, "folder_target", {
      ...emptyResearchDraft(),
      name: "Keep prospective name",
      formula: "volume",
      lastAdmittedBaseline: {
        ...emptyResearchDraft(),
        name: "Keep prospective name",
        formula: "volume",
      },
    });
    persistResearchDraft(storage, "folder_other", {
      ...emptyResearchDraft(),
      formula: "open",
    });
    const otherBefore = storage.getItem(researchDraftKey("folder_other"));

    const confirmDiscard = vi.fn(() => false);
    const copied = useResearchAsDraft(storage, "folder_target", {
      formula: "ts_mean(close, 20)",
      hypothesis: "Frozen hypothesis",
      start_date: "2026-08-03",
      end_date: "2026-08-05",
      universe: "top1000",
      neutralization: "industry",
      research_kind: "strategy_backtest",
      holdings_count: 25,
      rebalance_every_sessions: 5,
    }, confirmDiscard);

    expect(copied).toBe(true);
    expect(confirmDiscard).not.toHaveBeenCalled();
    expect(loadResearchDraft(storage, "folder_target")).toMatchObject({
      name: "Keep prospective name",
      formula: "ts_mean(close, 20)",
      hypothesis: "Frozen hypothesis",
      startDate: "2026-08-03",
      endDate: "2026-08-05",
      universe: "top1000",
      neutralization: "industry",
      holdingsCount: "25",
      rebalanceEverySessions: "5",
      editor: { anchor: 18, head: 18 },
      pendingAdmission: null,
    });
    expect(storage.getItem(researchDraftKey("folder_other"))).toBe(otherBefore);
  });

  it("reuses Factor Evaluation without retaining Strategy-only values", () => {
    const storage = new MemoryStorage();
    persistResearchDraft(storage, folder.id, {
      ...emptyResearchDraft(),
      researchKind: "strategy_backtest",
      holdingsCount: "25",
      rebalanceEverySessions: "5",
    });

    expect(useResearchAsDraft(storage, folder.id, {
      formula: "cs_rank(close)",
      hypothesis: null,
      start_date: "2026-08-03",
      end_date: "2026-08-05",
      universe: "top300",
      neutralization: "industry",
      research_kind: "factor_evaluation",
    }, () => true)).toBe(true);
    expect(loadResearchDraft(storage, folder.id)).toMatchObject({
      researchKind: "factor_evaluation",
      formula: "cs_rank(close)",
      holdingsCount: "",
      rebalanceEverySessions: "",
      pendingAdmission: null,
    });
  });

  it("requires confirmation only before overwriting unexecuted local values", () => {
    const storage = new MemoryStorage();
    const target = {
      ...emptyResearchDraft(),
      formula: "volume",
    };
    persistResearchDraft(storage, "folder_target", target);
    const confirmDiscard = vi.fn(() => false);

    const copied = useResearchAsDraft(storage, "folder_target", {
      formula: "close",
      hypothesis: null,
      start_date: "2026-08-03",
      end_date: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      research_kind: "strategy_backtest",
      holdings_count: 10,
      rebalance_every_sessions: 2,
    }, confirmDiscard);

    expect(copied).toBe(false);
    expect(confirmDiscard).toHaveBeenCalledOnce();
    expect(loadResearchDraft(storage, "folder_target")).toEqual(target);
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
      rebalanceEverySessions: "2",
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
      research_kind: "strategy_backtest",
      holdings_count: 10,
      rebalance_every_sessions: 2,
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
      rebalanceEverySessions: "2",
    };
    const begun = beginResearchRun(initial, folder.id, () => "run-request-1");
    persistResearchDraft(storage, folder.id, {
      ...begun.draft,
      formula: "ts_mean(close, 3)",
    });

    const finished = finishResearchRun(storage, folder.id, "run-request-1");
    expect(finished).not.toBeNull();
    if (finished === null) throw new Error("Accepted Research was not finished");
    expect(finished.formula).toBe("ts_mean(close, 3)");
    expect(finished.lastAdmittedBaseline?.formula).toBe("ts_mean(close, 2)");
    expect(loadResearchDraft(storage, folder.id)).toEqual(finished);
  });

  it("does not accept or persist a stale response after its pending Draft was replaced", () => {
    const storage = new MemoryStorage();
    const replacement = { ...emptyResearchDraft(), formula: "close" };
    persistResearchDraft(storage, folder.id, replacement);

    expect(finishResearchRun(storage, folder.id, "stale-request")).toBeNull();
    expect(loadResearchDraft(storage, folder.id)).toEqual(replacement);
  });

  it("opens empty when its one Folder key is absent and round-trips the bounded payload", () => {
    const storage = new MemoryStorage();
    const empty = loadResearchDraft(storage, folder.id);
    expect(empty).toEqual(emptyResearchDraft());
    expect(storage.length).toBe(0);

    const draft = { ...empty, name: "Mean reversion", formula: "ts_mean(close, 20)", editor: { anchor: 8, head: 8 } };
    persistResearchDraft(storage, folder.id, draft);
    expect(storage.length).toBe(1);
    expect(storage.key(0)).toBe(researchDraftKey(folder.id));
    expect(loadResearchDraft(storage, folder.id)).toEqual(draft);
  });

  it("keeps independent Draft values under distinct Folder keys", () => {
    const storage = new MemoryStorage();
    persistResearchDraft(storage, "folder_default", { ...emptyResearchDraft(), formula: "close" });
    persistResearchDraft(storage, "folder_signals", { ...emptyResearchDraft(), formula: "volume" });

    expect(loadResearchDraft(storage, "folder_default").formula).toBe("close");
    expect(loadResearchDraft(storage, "folder_signals").formula).toBe("volume");
    storage.removeItem(researchDraftKey("folder_signals"));
    expect(loadResearchDraft(storage, "folder_default").formula).toBe("close");
    expect(loadResearchDraft(storage, "folder_signals")).toEqual(emptyResearchDraft());
  });

  it("requires confirmation only when New would discard unexecuted inputs", () => {
    expect(hasUnexecutedChanges(emptyResearchDraft())).toBe(false);
    expect(hasUnexecutedChanges({ ...emptyResearchDraft(), formula: "close" })).toBe(true);
    const admitted = { ...emptyResearchDraft(), formula: "close" };
    expect(hasUnexecutedChanges({ ...admitted, lastAdmittedBaseline: {
      researchKind: "factor_evaluation", name: "", formula: "close", hypothesis: "", startDate: "", endDate: "", universe: "", neutralization: "", holdingsCount: "", rebalanceEverySessions: "",
    } })).toBe(false);
  });

  it("renders the DSL as the only Alpha surface without server-edit controls", () => {
    const markup = renderToStaticMarkup(<ResearchDraftWorkspace catalog={catalog} data={data} folder={folder} storage={new MemoryStorage()} />);
    expect(markup).toContain("Alpha formula editor");
    expect(markup).toContain('class="formula-workbench"');
    expect(markup).toContain('id="alpha-formula-title">Alpha formula</h2>');
    expect(markup).toContain("Draft name");
    expect(markup).toContain("New research");
    expect(markup).toContain('autoComplete="off"');
    expect(markup).toContain('disabled="" type="button"><svg');
    expect(markup).toContain("Run research");
    expect(markup).toContain("Research parameters");
    expect(markup).toContain("<legend>Research type</legend>");
    expect(markup).not.toContain("Research period");
    expect(markup).toContain('name="research-kind"');
    expect(markup).toMatch(/<input[^>]*checked=""[^>]*value="factor_evaluation"/);
    expect(markup).toContain("Factor Evaluation");
    expect(markup).toContain("Strategy Backtest");
    expect(markup).not.toContain("Holdings count");
    expect(markup).not.toContain("Rebalance sessions");
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
    expect(markup).not.toContain("total_revenue_latest_fy");
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
    persistResearchDraft(storage, folder.id, {
      ...emptyResearchDraft(),
      researchKind: "strategy_backtest",
    });

    const markup = renderToStaticMarkup(
      <ResearchDraftWorkspace catalog={catalog} data={data} folder={folder} storage={storage} />,
    );
    expect(markup).toMatch(/<input[^>]*checked=""[^>]*value="strategy_backtest"/);
    expect(markup).toContain("Holdings count");
    expect(markup).toContain("Rebalance sessions");
    expect(markup.match(/required="" step="1" type="number"/g)).toHaveLength(2);
    expect(markup).toMatch(/<input[^>]*id="research-holdings-count"[^>]*max="100"[^>]*min="1"[^>]*required=""[^>]*step="1"[^>]*type="number"/);
    expect(markup).toMatch(/<input[^>]*id="research-rebalance-sessions"[^>]*max="20"[^>]*min="1"[^>]*required=""[^>]*step="1"[^>]*type="number"/);
    expect(markup).toContain('aria-label="Decrease number of holdings" disabled=""');
    expect(markup).toContain('aria-label="Increase number of holdings"');
    expect(markup).toContain('aria-label="Decrease rebalance interval" disabled=""');
    expect(markup).toContain('aria-label="Increase rebalance interval"');
  });

  it("enables Run for one complete retained Draft", () => {
    const storage = new MemoryStorage();
    persistResearchDraft(storage, folder.id, {
      ...emptyResearchDraft(),
      formula: "close",
      startDate: "2026-08-03",
      endDate: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      holdingsCount: "10",
      rebalanceEverySessions: "2",
    });

    const markup = renderToStaticMarkup(
      <ResearchDraftWorkspace catalog={catalog} data={data} folder={folder} storage={storage} />,
    );
    expect(markup).toContain("Run research");
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
