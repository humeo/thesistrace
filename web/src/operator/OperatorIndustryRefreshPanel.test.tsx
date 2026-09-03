import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import {
  IndustryRefreshReconciliation,
  IndustryRefreshReceipt,
  OperatorIndustryRefreshPanel,
  suggestIndustryRefreshKey,
} from "./OperatorIndustryRefreshPanel";
import type { IndustryRefreshOperation } from "./operatorMutationClient";

test("renders focused Industry target and key fields", () => {
  const markup = renderToStaticMarkup(
    <OperatorIndustryRefreshPanel onAccessNotFound={() => undefined} />,
  );

  expect(markup).toContain("Industry Refresh");
  expect(markup).toContain("Observation-through Research Session");
  expect(markup).toContain('type="text"');
  expect(markup).not.toContain('type="date"');
  expect(markup).toContain("Idempotency key");
  expect(markup).toContain("exactly as accepted by the CLI");
  expect(markup).not.toContain(
    "Choose the exact Research Session through which Industry data is observed.",
  );
  expect(markup).not.toContain("Accepted is queued, not published.");
});

test("suggests an editable Industry key without selecting a target", () => {
  expect(
    suggestIndustryRefreshKey(new Date("2026-08-30T05:06:07.000Z")),
  ).toBe("industry-20260830T050607Z");
  expect(
    suggestIndustryRefreshKey(new Date("2026-08-30T05:06:07.996Z")),
  ).toBe("industry-20260830T050607Z");
});

test("shows no-change separately from published", () => {
  const markup = renderToStaticMarkup(
    <IndustryRefreshReceipt
      operation={industryOperation({ outcome: "no_change" })}
      pollError={false}
    />,
  );

  expect(markup).toContain("No change");
  expect(markup).toContain("Industry Canonical data did not change");
  expect(markup).not.toContain("new immutable Dataset Generation was published");
});

test("shows business rejection distinctly from infrastructure failure", () => {
  const rejected = renderToStaticMarkup(
    <IndustryRefreshReceipt
      operation={industryOperation({
        failureCode: "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION",
        outcome: "business_rejected",
        status: "failed",
      })}
      pollError={false}
    />,
  );
  const failed = renderToStaticMarkup(
    <IndustryRefreshReceipt
      operation={industryOperation({
        failureCode: "RETRY_EXHAUSTED",
        outcome: "infrastructure_failed",
        status: "failed",
      })}
      pollError={false}
    />,
  );

  expect(rejected).toContain("Industry Refresh rejected");
  expect(rejected).toContain("will not retry");
  expect(failed).toContain("Industry Refresh failed");
  expect(failed).toContain("Infrastructure retries were exhausted");
});

test("offers exact-request controls for an uncertain submission", () => {
  const markup = renderToStaticMarkup(
    <IndustryRefreshReconciliation
      onRetry={() => undefined}
      onStop={() => undefined}
      pollError
      request={{
        idempotencyKey: "industry-uncertain",
        observationThroughSession: "2026-08-14",
      }}
    />,
  );

  expect(markup).toContain("Retry exact request");
  expect(markup).toContain("Stop checking");
  expect(markup).toContain("Receipt unavailable; retrying while visible.");
});

function industryOperation(
  overrides: Partial<IndustryRefreshOperation>,
): IndustryRefreshOperation {
  return {
    attemptCount: 1,
    dataThroughSession: "2026-08-14",
    failureCode: null,
    idempotencyKey: "industry-20260814-custom",
    kind: "industry",
    lastFailureCode: null,
    lastRefreshAt: "2026-08-14T10:00:00Z",
    observationThroughSession: "2026-08-14",
    outcome: "published",
    status: "succeeded",
    ...overrides,
  };
}
