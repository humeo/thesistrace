import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { AlphaCatalog } from "../alphaCatalog";
import { DataOverviewView, loadDataPage, type DataOverview } from "./DataPage";

const overview: DataOverview = {
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
  fields: [
    {
      identifier: "close",
      field_id: "price.close.adjusted",
      value_type: "numeric_series",
      description: "Causal cumulative-adjusted close",
      unit: "CNY/share",
      family_id: "equity.eod_price",
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
      availability: "next_research_session_after_source_publication",
      report_period_selection: "latest_visible_full_year",
      applicable_company_types: ["1", "2", "3", "4"],
      missingness: "missing_when_no_visible_eligible_fact",
      example: "rank(revenue)",
    },
  ],
  builtins: [],
};

describe("DataOverviewView", () => {
  it("renders dataset coverage and the formula fields owned by each dataset", () => {
    const markup = renderToStaticMarkup(createElement(DataOverviewView, {
      catalog,
      overview,
      onRefresh: vi.fn(),
    }));

    expect(markup).toContain("Market coverage start");
    expect(markup).toContain("2025-08-08");
    expect(markup).toContain("Market coverage end");
    expect(markup).toContain("Data through");
    expect(markup).toContain("Last market refresh");
    expect(markup).toContain("Market data");
    expect(markup).toContain("Market ready");
    expect(markup).toContain("Strategy Benchmark");
    expect(markup).toContain("沪深300 ready");
    expect(markup).toContain(
      'aria-hidden="true" class="health-dot"></span> Strategy Benchmark',
    );
    expect(markup).toContain("Benchmark coverage start");
    expect(markup).toContain("Snapshot SHA-256");
    expect(markup).toContain("a".repeat(64));
    expect(markup).toContain("2026-08-07T05:00:00Z");
    expect(markup).toContain("Financial coverage start");
    expect(markup).toContain("2010-01-04");
    expect(markup).toContain("Discovery baseline");
    expect(markup).toContain("Attempted through");
    expect(markup).toContain("Complete through");
    expect(markup).toContain("2026-08-07");
    expect(markup).toContain("Pending instruments");
    expect(markup).toContain("Discovery gaps");
    expect(markup).toContain("Earliest unresolved");
    expect(markup).toContain("Last financial refresh");
    expect(markup).toContain("Finance ready");
    expect(markup).toContain("Industry ready");
    expect(markup).toContain("SW2021");
    expect(markup).toContain("2026-08-07T04:00:00Z");
    expect(markup).toContain("Research fields");
    expect(markup).toContain("Market data fields");
    expect(markup).toContain("Financial data fields");
    expect(markup).toContain("close");
    expect(markup).toContain("revenue");
    expect(markup).toContain("Latest full year visible on each Research Session");
    expect(markup).toContain("Company types 1, 2, 3, 4");
    expect(markup).toContain("Missing when no visible eligible fact");
    expect(markup).toContain("rank(revenue)");
    expect(markup).toContain("Reload");
    expect(markup).not.toContain("Current research data");
    expect(markup).not.toContain("Canonical data");
    expect(markup).not.toContain("Identifiers accepted by the Alpha formula editor");
    expect(markup).not.toContain("Adjusted prices and trading activity");
    expect(markup).not.toContain("Point-in-time financial facts limited to information visible");
    expect(markup).not.toContain("Financial coverage explanation");
    expect(markup).not.toMatch(/Update data|Release|Generation|history|operator/i);
  });

  it("does not fabricate coverage or unavailable dataset fields", () => {
    const markup = renderToStaticMarkup(createElement(DataOverviewView, {
      catalog: { fields: catalog.fields.slice(0, 1), builtins: [] },
      overview: {
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

    expect(markup).toContain("Market not ready");
    expect(markup).toContain("沪深300 not ready");
    expect(markup).toContain(
      'aria-hidden="true" class="health-dot health-dot-warning"></span> Strategy Benchmark',
    );
    expect(markup).toContain("Finance not ready");
    expect(markup).toContain("Industry not ready");
    expect(markup.match(/<dd>Not available<\/dd>/g)).toHaveLength(20);
    expect(markup).toContain("No fields are currently available for research.");
  });

  it.each([
    {
      readiness: "ready_with_pending" as const,
      pending: 2,
      gaps: 0,
      expected: "Finance ready with pending instruments",
    },
    {
      readiness: "ready_with_gaps" as const,
      pending: 1,
      gaps: 2,
      expected: "Finance ready with discovery gaps",
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
      },
      onRefresh: vi.fn(),
    }));

    expect(markup).toContain(expected);
    expect(markup).toContain(`<dd>${pending}</dd>`);
    expect(markup).toContain(`<dd>${gaps}</dd>`);
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
    expect(stale).toContain("Industry stale");
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
    expect(failed).toContain("Last refresh failed");
    expect(failed).toContain("OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION");
  });

  it("loads coverage and fields together and turns either failure into visible state", async () => {
    const unavailable = vi.fn<typeof fetch>().mockRejectedValue(new Error("network detail"));
    await expect(loadDataPage(unavailable)).resolves.toEqual({
      resources: null,
      error: "Data unavailable",
    });

    const recovered = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(overview), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(catalog), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    await expect(loadDataPage(recovered)).resolves.toEqual({
      resources: { overview, catalog },
      error: null,
    });
    expect(recovered).toHaveBeenNthCalledWith(1, "/api/data");
    expect(recovered).toHaveBeenNthCalledWith(2, "/api/alpha/catalog");
  });
});
