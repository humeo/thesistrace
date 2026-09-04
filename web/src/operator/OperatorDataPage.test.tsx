import { expect, test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import {
  MarketRefreshReceipt,
  OperatorDataPage,
  marketRefreshAsOfForDate,
  marketRefreshPollGenerationIsCurrent,
  suggestMarketRefreshKey,
} from "./OperatorDataPage";

test("renders the focused forms without redundant Operator copy", () => {
  const markup = renderToStaticMarkup(<OperatorDataPage />);

  expect(markup).toContain('href="/operator/researchers"');
  expect(markup).toContain('aria-current="page" href="/operator/data"');
  expect(markup).toContain("Market Refresh");
  expect(markup).toContain("Financial Refresh");
  expect(markup).toContain("Industry Refresh");
  expect(markup).toContain(">As-of<");
  expect(markup).toContain("Observation-through Research Session");
  expect(markup).toContain('type="text"');
  expect(markup).toContain('type="date"');
  expect(markup).not.toContain('type="datetime-local"');
  expect(markup).toContain('id="operator-market-as-of"');
  expect(markup).toContain("Submitted at 18:00 Asia/Shanghai (+08:00)");
  expect(markup).toContain(">Idempotency key<");
  expect(markup).not.toContain('<p class="eyebrow">Operator Console</p>');
  expect(markup).not.toContain(
    "Queue private refresh work and follow the exact operation through publication.",
  );
  expect(markup).not.toContain("Use the same free-form, timezone-aware inputs as the CLI.");
  expect(markup).not.toContain(
    "Choose the exact Research Session through which disclosures are observed.",
  );
  expect(markup).not.toContain(
    "Choose the exact Research Session through which Industry data is observed.",
  );
  expect(markup).not.toContain("Accepted is queued, not published.");
});

test("maps a calendar date to an explicit post-close Shanghai timestamp", () => {
  expect(marketRefreshAsOfForDate("2026-08-14")).toBe(
    "2026-08-14T18:00:00+08:00",
  );
  expect(marketRefreshAsOfForDate("2026-02-30")).toBe("");
  expect(marketRefreshAsOfForDate("")).toBe("");
});

test("suggests a stable kind-and-time key without selecting an as-of target", () => {
  expect(
    suggestMarketRefreshKey(new Date("2026-08-30T05:06:07.000Z")),
  ).toBe("market-20260830T050607Z");
  expect(
    suggestMarketRefreshKey(new Date("2026-08-30T05:06:07.996Z")),
  ).toBe("market-20260830T050607Z");
});

test("keeps the last known running state honest when status polling fails", () => {
  const markup = renderToStaticMarkup(
    <MarketRefreshReceipt
      operation={{
        asOf: "2026-08-11T10:00:00+00:00",
        attemptCount: 1,
        dataThroughSession: null,
        failureCode: null,
        idempotencyKey: "market-running",
        kind: "market",
        lastFailureCode: null,
        lastRefreshAt: null,
        outcome: null,
        status: "running",
      }}
      pollError
    />,
  );

  expect(markup).toContain("Refresh running");
  expect(markup).toContain('aria-live="polite"');
  expect(markup).toContain('role="status"');
  expect(markup).toContain("Showing the last known state");
  expect(markup).not.toContain("remains queued");
});

test("fences stale operation polls and reconciled submissions independently", () => {
  expect(marketRefreshPollGenerationIsCurrent("operation", 4, 9, 4)).toBe(true);
  expect(marketRefreshPollGenerationIsCurrent("operation", 4, 9, 5)).toBe(false);
  expect(marketRefreshPollGenerationIsCurrent("pending", 9, 9, 4)).toBe(true);
  expect(marketRefreshPollGenerationIsCurrent("pending", 9, 10, 4)).toBe(false);
});
