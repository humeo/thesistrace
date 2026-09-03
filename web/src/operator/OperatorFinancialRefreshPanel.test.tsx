import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import {
  FinancialRefreshReconciliation,
  FinancialRefreshReceipt,
  OperatorFinancialRefreshPanel,
  suggestFinancialRefreshKey,
} from "./OperatorFinancialRefreshPanel";
import type { FinancialRefreshOperation } from "./operatorMutationClient";

test("renders focused Financial target and key fields", () => {
  const markup = renderToStaticMarkup(
    <OperatorFinancialRefreshPanel onAccessNotFound={() => undefined} />,
  );

  expect(markup).toContain("Financial Refresh");
  expect(markup).toContain("Observation-through Research Session");
  expect(markup).toContain('type="text"');
  expect(markup).not.toContain('type="date"');
  expect(markup).toContain("Idempotency key");
  expect(markup).toContain("exactly as accepted by the CLI");
  expect(markup).not.toContain(
    "Choose the exact Research Session through which disclosures are observed.",
  );
  expect(markup).not.toContain("Accepted is queued, not published.");
});

test("suggests an editable Financial key without selecting a target", () => {
  expect(
    suggestFinancialRefreshKey(new Date("2026-08-30T05:06:07.000Z")),
  ).toBe("financial-20260830T050607Z");
  expect(
    suggestFinancialRefreshKey(new Date("2026-08-30T05:06:07.996Z")),
  ).toBe("financial-20260830T050607Z");
});

test("shows discovery gaps and their complete-through consequence", () => {
  const markup = renderToStaticMarkup(
    <FinancialRefreshReceipt
      operation={financialOperation({
        discoveryGapCount: 1,
        financialCompleteThroughSession: "2026-08-13",
        outcome: "degraded",
        pendingInstrumentCount: 0,
      })}
      pollError={false}
    />,
  );

  expect(markup).toContain("Degraded success");
  expect(markup).toContain("discovery gaps remain");
  expect(markup).toContain("complete-through may lag");
  expect(markup).toContain("<dt>Discovery gaps</dt><dd>1</dd>");
  expect(markup).toContain("<dt>Complete through</dt><dd>2026-08-13</dd>");
});

test("shows pending instruments separately from discovery gaps", () => {
  const markup = renderToStaticMarkup(
    <FinancialRefreshReceipt
      operation={financialOperation({
        discoveryGapCount: 0,
        outcome: "degraded",
        pendingInstrumentCount: 2,
      })}
      pollError={false}
    />,
  );

  expect(markup).toContain("some instruments remain pending");
  expect(markup).toContain("<dt>Pending instruments</dt><dd>2</dd>");
  expect(markup).toContain("<dt>Discovery gaps</dt><dd>0</dd>");
});

test("offers explicit retry and stop controls for an uncertain submission", () => {
  const markup = renderToStaticMarkup(
    <FinancialRefreshReconciliation
      onRetry={() => undefined}
      onStop={() => undefined}
      pollError
      request={{
        idempotencyKey: "financial-uncertain",
        observationThroughSession: "2026-08-14",
      }}
    />,
  );

  expect(markup).toContain("Retry exact request");
  expect(markup).toContain("Stop checking");
  expect(markup).toContain("Receipt unavailable; retrying while visible.");
});

test("labels unavailable terminal failure diagnostics without calling them pending", () => {
  const markup = renderToStaticMarkup(
    <FinancialRefreshReceipt
      operation={financialOperation({
        acceptedInstrumentCount: null,
        checkedNoStructuredChangeCount: null,
        dataThroughSession: null,
        discoveryGapCount: null,
        failedInstrumentCount: null,
        failureCode: "FINANCIAL_TARGET_EXCEEDS_MARKET",
        financialCompleteThroughSession: null,
        lastRefreshAt: null,
        matchedTriggerCount: null,
        outcome: "business_rejected",
        pendingInstrumentCount: null,
        status: "failed",
      })}
      pollError={false}
    />,
  );

  expect(markup).toContain("<dt>Matched triggers</dt><dd>Unavailable</dd>");
  expect(markup).not.toContain("<dd>Pending</dd>");
});

test("does not claim retries were exhausted for a nonretryable internal failure", () => {
  const markup = renderToStaticMarkup(
    <FinancialRefreshReceipt
      operation={financialOperation({
        failureCode: "FINANCIAL_REFRESH_CLOCK_INVALID",
        outcome: "infrastructure_failed",
        status: "failed",
      })}
      pollError={false}
    />,
  );

  expect(markup).toContain("An internal or infrastructure failure stopped");
  expect(markup).toContain("will not retry automatically");
  expect(markup).not.toContain("retries were exhausted");
});

function financialOperation(
  overrides: Partial<FinancialRefreshOperation>,
): FinancialRefreshOperation {
  return {
    acceptedInstrumentCount: 0,
    attemptCount: 1,
    checkedNoStructuredChangeCount: 0,
    dataThroughSession: "2026-08-14",
    discoveryGapCount: 0,
    failedInstrumentCount: 0,
    failureCode: null,
    financialCompleteThroughSession: "2026-08-14",
    idempotencyKey: "financial-20260814-custom",
    kind: "financial",
    lastFailureCode: null,
    lastRefreshAt: "2026-08-14T10:00:00Z",
    matchedTriggerCount: 0,
    observationThroughSession: "2026-08-14",
    outcome: "no_change",
    pendingInstrumentCount: 0,
    status: "succeeded",
    ...overrides,
  };
}
