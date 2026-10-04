import { expect, test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import {
  DatasetRefreshReceipt,
  OperatorDataPage,
  datasetRefreshAsOfForDate,
  suggestDatasetRefreshKey,
} from "./OperatorDataPage";

test("renders the focused forms without redundant Operator copy", () => {
  const markup = renderToStaticMarkup(<OperatorDataPage />);

  expect(markup).toContain('href="/operator/researchers"');
  expect(markup).toContain('aria-current="page" href="/operator/data"');
  expect(markup).toContain("Data Refresh");
  expect(markup.match(/<form /g)).toHaveLength(1);
  expect(markup).not.toContain("Financial Refresh</h2>");
  expect(markup).not.toContain("Industry Refresh</h2>");
  expect(markup).toContain(">As-of<");
  expect(markup).not.toContain("Observation-through Research Session");
  expect(markup).toContain('id="operator-market-as-of"');
  expect(markup).toContain('aria-label="Open As-of calendar"');
  expect(markup).not.toContain('type="datetime-local"');
  expect(markup).toContain('id="operator-market-as-of"');
  expect(markup).toContain("Uses 18:00 Asia/Shanghai");
  expect(markup).not.toContain(">Idempotency key<");
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
  expect(datasetRefreshAsOfForDate("2026-08-14")).toBe(
    "2026-08-14T18:00:00+08:00",
  );
  expect(datasetRefreshAsOfForDate("2026-02-30")).toBe("");
  expect(datasetRefreshAsOfForDate("")).toBe("");
});

test("generates a unique kind-and-time key without selecting an as-of target", () => {
  expect(
    suggestDatasetRefreshKey(new Date("2026-08-30T05:06:07.000Z")),
  ).toEqual(expect.stringMatching(/^dataset-20260830T050607Z-[0-9a-f-]{36}$/));
  expect(
    suggestDatasetRefreshKey(new Date("2026-08-30T05:06:07.996Z")),
  ).toEqual(expect.stringMatching(/^dataset-20260830T050607Z-[0-9a-f-]{36}$/));
});

test("keeps the last known running state honest when status polling fails", () => {
  const markup = renderToStaticMarkup(
    <DatasetRefreshReceipt
      operation={{
        asOf: "2026-08-11T10:00:00+00:00",
        attemptCount: 1,
        dataThroughSession: null,
        failureCode: null,
        idempotencyKey: "market-running",
        kind: "dataset", phase: null, completedStages: [],
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
