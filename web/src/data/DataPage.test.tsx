import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { AlphaCatalog } from "../alphaCatalog";
import { DataOverviewView, loadDataPage, type DataOverview } from "./DataPage";

const overview: DataOverview = {
  market_coverage: { start: "2025-08-08", end: "2026-08-07" },
  financial_coverage: {
    start: "2010-01-04",
    observation_through_session: "2026-08-06",
    reconciliation_status: "complete",
    historical_reconciliation_watermark: "2026-08-06",
    revision_coverage: "source-dated-and-first-observed-corrections",
    seed_policy: "latest-pre-start-annual-flow-and-balance-facts",
    sparse_facts: true,
  },
  data_through_session: "2026-08-07",
  last_market_refresh_at: null,
  last_financial_refresh_at: "2026-08-07T03:00:00Z",
  market_research_readiness: true,
  financial_research_readiness: true,
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
    expect(markup).toContain("Financial coverage start");
    expect(markup).toContain("2010-01-04");
    expect(markup).toContain("Observed through");
    expect(markup).toContain("2026-08-06");
    expect(markup).toContain("Reconciliation");
    expect(markup).toContain("complete");
    expect(markup).toContain("Last financial refresh");
    expect(markup).toContain("Finance ready");
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
        data_through_session: null,
        last_market_refresh_at: null,
        last_financial_refresh_at: null,
        market_research_readiness: false,
        financial_research_readiness: false,
      },
      onRefresh: vi.fn(),
    }));

    expect(markup).toContain("Market not ready");
    expect(markup).toContain("Finance not ready");
    expect(markup.match(/<dd>Not available<\/dd>/g)).toHaveLength(8);
    expect(markup).toContain("No fields are currently available for research.");
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
