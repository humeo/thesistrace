import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { DataOverviewView, loadDataOverview } from "./DataPage";

describe("DataOverviewView", () => {
  it("renders the independent read-only market and financial projections", () => {
    const markup = renderToStaticMarkup(createElement(DataOverviewView, {
      overview: {
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
      },
      onRefresh: vi.fn(),
    }));

    expect(markup).toContain("Market coverage start");
    expect(markup).toContain("2025-08-08");
    expect(markup).toContain("Market coverage end");
    expect(markup).toContain("Data through");
    expect(markup).toContain("Last market refresh");
    expect(markup).toContain("Market ready");
    expect(markup).toContain("Financial coverage start");
    expect(markup).toContain("2010-01-04");
    expect(markup).toContain("Observed through");
    expect(markup).toContain("2026-08-06");
    expect(markup).toContain("Reconciliation");
    expect(markup).toContain("complete");
    expect(markup).toContain("Last financial refresh");
    expect(markup).toContain("Finance ready");
    expect(markup).toContain("Refresh");
    expect(markup).not.toMatch(/Update data|Release|Generation|history|operator/i);
  });

  it("does not fabricate values while the mounted store is empty", () => {
    const markup = renderToStaticMarkup(createElement(DataOverviewView, {
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
    expect(markup.match(/<dd>—<\/dd>/g)).toHaveLength(8);
  });

  it("turns refresh failures into visible state and can recover", async () => {
    const unavailable = vi.fn<typeof fetch>().mockRejectedValue(new Error("network detail"));
    await expect(loadDataOverview(unavailable)).resolves.toEqual({
      overview: null,
      error: "Data overview unavailable",
    });

    const overview = {
      market_coverage: { start: "2025-08-08", end: "2026-08-07" },
      financial_coverage: null,
      data_through_session: "2026-08-07",
      last_market_refresh_at: null,
      last_financial_refresh_at: null,
      market_research_readiness: true,
      financial_research_readiness: false,
    };
    const recovered = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(overview), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(loadDataOverview(recovered)).resolves.toEqual({
      overview,
      error: null,
    });
  });
});
