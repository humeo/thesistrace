import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { DataOverviewView } from "./DataPage";

describe("DataOverviewView", () => {
  it("renders only the read-only current-data projection", () => {
    const markup = renderToStaticMarkup(createElement(DataOverviewView, {
      overview: {
        dataset_coverage: { start: "2025-08-08", end: "2026-08-07" },
        data_through_session: "2026-08-07",
        last_refresh_at: null,
        readiness: true,
      },
      onRefresh: vi.fn(),
    }));

    expect(markup).toContain("Coverage start");
    expect(markup).toContain("2025-08-08");
    expect(markup).toContain("Coverage end");
    expect(markup).toContain("Data through");
    expect(markup).toContain("Last successful refresh");
    expect(markup).toContain("Ready for research");
    expect(markup).toContain("Refresh");
    expect(markup).not.toMatch(/Update data|Release|Generation|history|operator/i);
  });

  it("does not fabricate values while the mounted store is empty", () => {
    const markup = renderToStaticMarkup(createElement(DataOverviewView, {
      overview: {
        dataset_coverage: null,
        data_through_session: null,
        last_refresh_at: null,
        readiness: false,
      },
      onRefresh: vi.fn(),
    }));

    expect(markup).toContain("Data not ready");
    expect(markup.match(/<dd>—<\/dd>/g)).toHaveLength(4);
  });
});
