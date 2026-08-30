import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  datasetStatusNeedsPolling,
  OperatorDataStatusDrawer,
  OperatorDatasetStatusView,
} from "./OperatorDatasetStatus";
import type {
  DataRefreshOperationalStatus,
  DatasetOperationalStatus,
} from "./operatorDataStatusClient";

describe("Operator Dataset status", () => {
  it("leads with Head readiness and renders every lifecycle meaning as text", () => {
    const operations = [
      operation({ idempotencyKey: "market-accepted", kind: "market", status: "accepted" }),
      operation({ idempotencyKey: "financial-running", kind: "financial", status: "running", phase: "financial" }),
      operation({ idempotencyKey: "industry-published", kind: "industry", outcome: "published", status: "succeeded" }),
      operation({ idempotencyKey: "market-unchanged", kind: "market", outcome: "no_change", status: "succeeded" }),
      operation({ idempotencyKey: "financial-degraded", kind: "financial", outcome: "degraded", status: "succeeded" }),
      operation({ idempotencyKey: "market-failed", failureCode: "RETRY_EXHAUSTED", kind: "market", status: "failed" }),
      operation({ idempotencyKey: "industry-cancelled", kind: "industry", status: "cancelled" }),
    ];
    const markup = renderToStaticMarkup(
      <OperatorDatasetStatusView
        cursorDepth={0}
        data={{ ...statusPage(), latestByKind: operations.slice(0, 3), operations }}
        error={false}
        loading={false}
        onDetails={() => undefined}
        onNext={() => undefined}
        onPrevious={() => undefined}
        onReload={() => undefined}
      />,
    );

    expect(markup.indexOf("Dataset Head")).toBeLessThan(markup.indexOf("Operation history"));
    expect(markup).toContain("d".repeat(64));
    expect(markup).toContain("Market ready");
    expect(markup).toContain("Benchmark ready");
    expect(markup).toContain("Financial ready with pending");
    expect(markup).toContain("Industry ready");
    expect(markup).toContain("Accepted · queued");
    expect(markup).toContain("Running · Financial pipeline");
    expect(markup).toContain("Published");
    expect(markup).toContain("No change");
    expect(markup).toContain("Degraded success");
    expect(markup).toContain("Failed");
    expect(markup).toContain("Cancelled");
    expect(markup).toContain(">Reload<");
    expect(markup).toContain("Market Refresh");
    expect(markup).toContain("Financial Refresh");
    expect(markup).toContain("Industry Refresh");
    expect(markup).not.toMatch(/Cancel operation|Retry operation/);
  });

  it("renders only bounded safe receipt facts in the labelled detail drawer", () => {
    const markup = renderToStaticMarkup(
      <OperatorDataStatusDrawer
        onDismiss={() => undefined}
        operation={operation({
          acceptedInstrumentCount: 3,
          checkedNoStructuredChangeCount: 4,
          discoveryGapCount: 1,
          failedInstrumentCount: 1,
          financialCompleteThroughSession: "2026-08-28",
          idempotencyKey: "financial-degraded",
          kind: "financial",
          matchedTriggerCount: 9,
          outcome: "degraded",
          pendingInstrumentCount: 2,
          status: "succeeded",
        })}
      />,
    );

    expect(markup).toContain('aria-labelledby="operator-data-operation-drawer-title"');
    expect(markup).toContain("Operation details");
    expect(markup).toContain("financial-degraded");
    expect(markup).toContain("Last heartbeat");
    expect(markup).toContain("Matched triggers");
    expect(markup).toContain("Discovery gaps");
    expect(markup).toContain(">Close<");
    expect(markup).not.toMatch(/manifest|owner token|lease|object path|raw response/i);
  });

  it("polls only while latest or visible history contains non-terminal work", () => {
    expect(datasetStatusNeedsPolling(statusPage({
      latestByKind: [operation({ status: "accepted" })],
      operations: [],
    }))).toBe(true);
    expect(datasetStatusNeedsPolling(statusPage({
      latestByKind: [],
      operations: [operation({ status: "running" })],
    }))).toBe(true);
    expect(datasetStatusNeedsPolling(statusPage())).toBe(false);
  });
});

function statusPage(
  overrides: Partial<DatasetOperationalStatus> = {},
): DatasetOperationalStatus {
  return {
    head: {
      dataIdentity: "d".repeat(64),
      preparedAt: "2026-08-29T23:00:00Z",
      dataThroughSession: "2026-08-29",
      marketResearchReadiness: true,
      benchmarkResearchReadiness: true,
      financialResearchReadiness: "ready_with_pending",
      industryResearchReadiness: true,
    },
    latestByKind: [operation({ outcome: "published", status: "succeeded" })],
    operations: [operation({ outcome: "published", status: "succeeded" })],
    nextCursor: null,
    ...overrides,
  };
}

function operation(
  overrides: Partial<DataRefreshOperationalStatus> = {},
): DataRefreshOperationalStatus {
  const status = overrides.status ?? "succeeded";
  const kind = overrides.kind ?? "market";
  const terminal = status === "succeeded" || status === "failed" || status === "cancelled";
  const running = status === "running";
  const financial = kind === "financial";
  return {
    idempotencyKey: "market-published",
    kind,
    status,
    outcome: status === "succeeded" ? "published" : null,
    asOf: kind === "market" ? "2026-08-30T08:00:00Z" : null,
    observationThroughSession: kind === "market" ? null : "2026-08-29",
    phase: status === "accepted" ? null : kind === "market" ? "publication" : kind,
    attemptCount: status === "accepted" ? 0 : 1,
    lastHeartbeatAt: status === "accepted" ? null : "2026-08-30T08:01:00Z",
    dataThroughSession: status === "succeeded" ? "2026-08-29" : null,
    lastRefreshAt: status === "succeeded" ? "2026-08-30T08:02:00Z" : null,
    financialCompleteThroughSession: financial && status === "succeeded" ? "2026-08-29" : null,
    matchedTriggerCount: financial && status === "succeeded" ? 0 : null,
    checkedNoStructuredChangeCount: financial && status === "succeeded" ? 0 : null,
    acceptedInstrumentCount: financial && status === "succeeded" ? 0 : null,
    failedInstrumentCount: financial && status === "succeeded" ? 0 : null,
    pendingInstrumentCount: financial && status === "succeeded" ? 0 : null,
    discoveryGapCount: financial && status === "succeeded" ? 0 : null,
    failureCode: status === "failed" ? "RETRY_EXHAUSTED" : null,
    lastFailureCode: null,
    createdAt: "2026-08-30T08:00:00Z",
    startedAt: status === "accepted" ? null : "2026-08-30T08:00:01Z",
    finishedAt: terminal ? "2026-08-30T08:02:00Z" : null,
    updatedAt: running ? "2026-08-30T08:01:00Z" : "2026-08-30T08:02:00Z",
    ...overrides,
  };
}
