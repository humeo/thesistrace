import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { AlphaCatalog } from "../alphaCatalog";
import { DataOverviewView, loadDataPage, type DataOverview } from "./DataPage";

const overview: DataOverview = {
  generation_manifest_sha256: "b".repeat(64),
  available_field_ids: ["price.close.adjusted", "financial.income.total_revenue.latest_fy"],
  field_families: [
    { family_id: "equity.eod_price", research_category: "market", source_endpoints: ["daily"],
      supported_field_ids: ["price.close.adjusted"], available_field_ids: ["price.close.adjusted"],
      coverage_start: "2025-08-08", coverage_end: "2026-08-07", readiness: "ready" },
    { family_id: "equity.financial_pit", research_category: "financial", source_endpoints: ["income"],
      supported_field_ids: ["financial.income.total_revenue.latest_fy"], available_field_ids: ["financial.income.total_revenue.latest_fy"],
      coverage_start: "2010-01-04", coverage_end: "2026-08-07", readiness: "ready" },
  ],
  market_coverage: { start: "2025-08-08", end: "2026-08-07" },
  financial_coverage: {
    start: "2010-01-04",
    discovery_baseline_session: "2026-08-06",
    discovery_attempted_through_session: "2026-08-07",
    discovery_complete_through_session: "2026-08-07",
    historical_reconciliation_watermark: "2026-08-06",
    revision_coverage: "cninfo-announcement-driven-tushare-observed",
    seed_policy: "latest-pre-start-annual-flow-and-balance-facts",
    readiness_status: "ready",
    pending_instrument_count: 0,
    discovery_gap_count: 0,
    earliest_unresolved_date: null,
    sparse_facts: true,
  },
  industry_coverage: {
    start: "2025-08-08",
    observation_through_session: "2026-08-07",
    classification_version: "SW2021",
  },
  benchmark_coverage: { start: "2010-01-04", end: "2026-08-07" },
  benchmark_snapshot_sha256: "a".repeat(64),
  benchmark_last_published_at: "2026-08-07T05:00:00Z",
  data_through_session: "2026-08-07",
  last_market_refresh_at: null,
  last_financial_refresh_at: "2026-08-07T03:00:00Z",
  last_industry_refresh_at: "2026-08-07T04:00:00Z",
  industry_refresh_status: "succeeded",
  industry_refresh_failure_code: null,
  market_research_readiness: true,
  benchmark_research_readiness: true,
  financial_research_readiness: "ready",
  industry_research_readiness: true,
};

const catalog: AlphaCatalog = {
  generation_manifest_sha256: "a".repeat(64),
  fields: [
    {
      identifier: "close",
      field_id: "price.close.adjusted",
      value_type: "numeric_series",
      description: "Causal cumulative-adjusted close",
      unit: "CNY/share",
      family_id: "equity.eod_price",
      research_category: "market",
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
      value_type: "numeric_series",
      description: "Latest visible full-year consolidated total revenue",
      unit: "CNY",
      family_id: "equity.financial_pit",
      research_category: "financial",
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
  industries: [], builtins: [],
};

describe("DataOverviewView", () => {
  it("renders dataset coverage and the formula fields owned by each dataset", () => {
    const markup = renderToStaticMarkup(createElement(DataOverviewView, {
      catalog,
      overview,
      onRefresh: vi.fn(),
    }));

    expect(markup).toContain("Data coverage");
    expect(markup).toContain("2025-08-08");
    expect(markup).toContain("2010-01-04");
    expect(markup).toContain("2026-08-07");
    expect(markup).toContain("CSI 300");
    expect(markup).toContain("SW2021");
    expect(markup).toContain("Available");
    expect(markup).toContain("Research fields");
    expect(markup).toContain("close");
    expect(markup).toContain("revenue");
    expect(markup).toContain("Reload status");
    expect(markup).not.toContain("Snapshot SHA-256");
    expect(markup).not.toContain("Discovery baseline");
    expect(markup).not.toContain("Last market refresh");
  });

  it("does not fabricate coverage or unavailable dataset fields", () => {
    const markup = renderToStaticMarkup(createElement(DataOverviewView, {
      catalog: { industries: [], generation_manifest_sha256: null, fields: catalog.fields.slice(0, 1), builtins: [] },
      overview: {
        generation_manifest_sha256: null,
        available_field_ids: [],
        field_families: [],
        market_coverage: null,
        financial_coverage: null,
        industry_coverage: null,
        benchmark_coverage: null,
        benchmark_snapshot_sha256: null,
        benchmark_last_published_at: null,
        data_through_session: null,
        last_market_refresh_at: null,
        last_financial_refresh_at: null,
        last_industry_refresh_at: null,
        industry_refresh_status: null,
        industry_refresh_failure_code: null,
        market_research_readiness: false,
        benchmark_research_readiness: false,
        financial_research_readiness: "not_ready",
        industry_research_readiness: false,
      },
      onRefresh: vi.fn(),
    }));

    expect(markup.match(/No published coverage/g)).toHaveLength(4);
    expect(markup.match(/health-dot health-dot-warning/g)).toHaveLength(4);
    expect(markup).not.toContain("2026-08-07");
  });

  it.each([
    {
      readiness: "ready_with_pending" as const,
      pending: 2,
      gaps: 0,
      expected: "2 instruments awaiting verification and 0 gaps",
    },
    {
      readiness: "ready_with_gaps" as const,
      pending: 1,
      gaps: 2,
      expected: "1 instruments awaiting verification and 2 gaps",
    },
  ])("renders $readiness as usable degraded data", ({ readiness, pending, gaps, expected }) => {
    const markup = renderToStaticMarkup(createElement(DataOverviewView, {
      catalog,
      overview: {
        ...overview,
        financial_coverage: {
          ...overview.financial_coverage!,
          discovery_attempted_through_session: "2026-08-14",
          discovery_complete_through_session: gaps === 0 ? "2026-08-14" : "2026-08-13",
          readiness_status: readiness,
          pending_instrument_count: pending,
          discovery_gap_count: gaps,
          earliest_unresolved_date: "2026-08-14",
        },
        data_through_session: "2026-08-14",
        financial_research_readiness: readiness,
        field_families: overview.field_families.map((family) => family.research_category === "financial"
          ? { ...family, readiness } : family),
      },
      onRefresh: vi.fn(),
    }));

    expect(markup).toContain(expected);
    expect(markup).toContain("Limited coverage");
    expect(markup).toContain("2026-08-14");
    expect(markup).not.toContain("Finance not ready");
  });

  it("distinguishes stale Industry coverage from the latest failed refresh", () => {
    const staleOverview: DataOverview = {
      ...overview,
      financial_coverage: null,
      industry_coverage: {
        start: "2025-08-08",
        observation_through_session: "2026-08-06",
        classification_version: "SW2021",
      },
      last_financial_refresh_at: null,
      last_industry_refresh_at: "2026-08-06T03:00:00Z",
      industry_refresh_status: "succeeded",
      financial_research_readiness: "not_ready",
      industry_research_readiness: false,
    };
    const stale = renderToStaticMarkup(createElement(DataOverviewView, {
      catalog,
      overview: staleOverview,
      onRefresh: vi.fn(),
    }));
    expect(stale).toContain("Limited coverage");
    expect(stale).toContain("health-dot health-dot-warning");
    expect(stale).not.toContain("Last refresh failed");

    const failed = renderToStaticMarkup(createElement(DataOverviewView, {
      catalog,
      overview: {
        ...staleOverview,
        industry_refresh_status: "failed",
        industry_refresh_failure_code: "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION",
      },
      onRefresh: vi.fn(),
    }));
    expect(failed).toContain("Limited coverage");
    expect(failed).not.toContain("OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION");
  });

  it("loads coverage and fields together and turns either failure into visible state", async () => {
    const unavailable = vi.fn<typeof fetch>().mockRejectedValue(new Error("network detail"));
    await expect(loadDataPage(unavailable)).resolves.toEqual({
      resources: null,
      error: "Data unavailable",
    });

    const recovered = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ ...overview, catalog }));
    await expect(loadDataPage(recovered)).resolves.toEqual({
      resources: { overview, catalog },
      error: null,
    });
    expect(recovered).toHaveBeenNthCalledWith(1, "/api/data");
    expect(recovered).toHaveBeenCalledTimes(1);
  });
});

it("explains the research Universe scope and formal industry choices for common inputs", () => {
  const markup = renderToStaticMarkup(createElement(DataOverviewView, {
    overview,
    onRefresh: vi.fn(),
    catalog: {
      ...catalog,
      industries: [{ code: 801010, name: "农林牧渔" }],
      builtins: [{
        identifier: "industry_return",
        parameters: [{ name: "industry", value_type: "industry", minimum: null, maximum: null }],
        result_type: "common_series",
        description: "Equal-weight return of the historical industry subset of the research Universe.",
        examples: ["close * industry_return(801010)"],
        missing_value_behavior: "Missing when no valid members remain.",
        numeric_behavior: "Adjusted Close return over one Session.",
      }],
    },
  }));
  expect(markup).toContain("Common market inputs");
  expect(markup).toContain("not a full industry or official index");
  expect(markup).toContain("does not change the stock selection Universe");
  expect(markup).toContain("801010");
  expect(markup).toContain("农林牧渔");
  expect(markup).toContain("data coverage is checked for the chosen research period");
});

it("groups fields by research category across different source families", () => {
  const markup = renderToStaticMarkup(createElement(DataOverviewView, {
    overview,
    onRefresh: vi.fn(),
    catalog: {
      ...catalog,
      fields: [...catalog.fields, {
        ...catalog.fields[1],
        identifier: "roe",
        field_id: "financial.indicator.roe",
        family_id: "equity.financial_indicator",
        source_endpoint: "fina_indicator",
        display_name: "净资产收益率",
      }],
    },
  }));
  expect(markup).toContain("净资产收益率");
  expect(markup).toContain("3 fields");
  expect(markup).toContain("Search fields");
  expect(markup).toContain("Research purpose");
  expect(markup).toContain("All purposes");
  expect(markup).not.toContain("Field source");
  expect(markup).not.toContain("Field period");
  expect(markup).not.toContain("More filters");
  expect(markup).not.toContain("Source &amp; calculation");
});
