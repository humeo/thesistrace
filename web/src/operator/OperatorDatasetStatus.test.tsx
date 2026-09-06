import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  datasetStatusNeedsPolling,
  OperatorDataStatusDrawer,
  OperatorDatasetStatusView,
} from "./OperatorDatasetStatus";
import {
  OperatorDataRefreshActionDialog,
  suggestDataRefreshRetryKey,
} from "./OperatorDataRefreshActionDialog";
import type {
  DataRefreshOperationalStatus,
  DatasetOperationalStatus,
} from "./operatorDataStatusClient";

describe("Operator Dataset status", () => {
  it("shows each published dataset's own coverage and freshness without requiring receipts", () => {
    const markup = renderStatus(statusPage({ latestByKind: [], operations: [] }));

    expect(markup).toContain('aria-label="Current data coverage"');
    expect(markup).toContain("CSI 300 Benchmark");
    expect(markup).toContain("Updates with Market Refresh");
    expect(markup).toContain("2010-01-04");
    expect(markup).toContain("2026-08-31");
    expect(markup).toContain("Discovery attempted through");
    expect(markup).toContain("Discovery complete through");
    expect(markup).toContain("2026-08-28");
    expect(markup).toContain("Pending instruments");
    expect(markup).toContain("Discovery gaps");
    expect(markup).toContain("Earliest unresolved");
    expect(markup).toContain("2026-08-26");
    expect(markup).toContain("2026-08-30 08:02:00 UTC");
    expect(markup).toContain("2026-08-29 08:03:00 UTC");
    expect(markup).toContain("No Data Refresh operations have been accepted.");
  });

  it("keeps absent coverage and zero unresolved counts distinct", () => {
    const page = statusPage();
    const markup = renderStatus({
      ...page,
      head: {
        ...page.head,
        benchmarkCoverageStart: null,
        benchmarkCoverageEnd: null,
        benchmarkLastPublishedAt: null,
        benchmarkResearchReadiness: false,
        financialPendingInstrumentCount: 0,
        financialDiscoveryGapCount: 0,
        financialEarliestUnresolvedDate: null,
        industryCoverageStart: null,
        industryObservationThroughSession: null,
        industryLastRefreshAt: null,
        industryResearchReadiness: false,
      },
    });

    expect(markup).toContain("Benchmark not ready");
    expect(markup).toContain("Industry not ready");
    expect(markup).toContain("Not available");
    expect(markup).toContain("<dt>Pending instruments</dt><dd>0</dd>");
    expect(markup).toContain("<dt>Discovery gaps</dt><dd>0</dd>");
    expect(markup).not.toContain("undefined");
  });

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
        onAction={() => undefined}
      />,
    );

    expect(markup.indexOf("Current research Dataset")).toBeLessThan(
      markup.indexOf("Operation history"),
    );
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
    expect(markup).not.toContain('<p class="eyebrow">Dataset Head</p>');
    expect(markup).not.toContain(
      "One Head, one global Refresh queue, and bounded operational receipts.",
    );
    expect(markup).not.toContain("Newest durable receipt for each queue kind");
    expect(markup).not.toContain("terminal receipts retained 180 days");
    expect(markup).not.toContain(
      "Accepted work can be claimed by the single Refresh Worker.",
    );
    expect(markup).toContain('aria-label="Cancel operation market-accepted"');
    expect(markup).toContain('aria-label="Retry operation market-failed"');
    expect(markup).toContain('aria-label="Retry operation industry-cancelled"');
    expect(markup).not.toContain('aria-label="Cancel operation financial-running"');
    expect(markup).not.toContain('aria-label="Retry operation industry-published"');
  });

  it("distinguishes an older page emptied by retention from unused history", () => {
    const markup = renderToStaticMarkup(
      <OperatorDatasetStatusView
        cursorDepth={2}
        data={statusPage({ operations: [], nextCursor: null })}
        error={false}
        loading={false}
        onDetails={() => undefined}
        onNext={() => undefined}
        onPrevious={() => undefined}
        onReload={() => undefined}
        onAction={() => undefined}
      />,
    );

    expect(markup).toContain(
      "This older page no longer contains retained receipts. Return to a newer page.",
    );
    expect(markup).not.toContain("No Data Refresh operations have been accepted.");
    expect(markup).toContain(">Newer</button>");
    expect(markup).not.toContain('<button disabled="" type="button">Newer</button>');
    expect(markup).toContain("Page 3");
  });

  it("renders only bounded safe receipt facts in the labelled detail drawer", () => {
    const markup = renderToStaticMarkup(
      <OperatorDataStatusDrawer
        onDismiss={() => undefined}
        onAction={() => undefined}
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

  it("warns explicitly when durable queued work has no available Worker", () => {
    const markup = renderToStaticMarkup(
      <OperatorDatasetStatusView
        cursorDepth={0}
        data={statusPage({
          latestByKind: [operation({ status: "accepted" })],
          operations: [operation({ status: "accepted" })],
          worker: {
            available: false,
            lastHeartbeatAt: "2026-08-30T07:59:00Z",
          },
        })}
        error={false}
        loading={false}
        onDetails={() => undefined}
        onNext={() => undefined}
        onPrevious={() => undefined}
        onReload={() => undefined}
        onAction={() => undefined}
      />,
    );

    expect(markup).toContain('role="alert"');
    expect(markup).toContain("Data Operator Worker unavailable");
    expect(markup).toContain(
      "Accepted work is durably queued but cannot start until the Worker recovers.",
    );
    expect(markup).toContain("2026-08-30T07:59:00Z");
    expect(markup).not.toMatch(/owner token|lease expires|tushare/i);
  });

  it("describes interrupted running work as recoverable rather than not started", () => {
    const markup = renderToStaticMarkup(
      <OperatorDatasetStatusView
        cursorDepth={0}
        data={statusPage({
          latestByKind: [operation({ status: "running" })],
          operations: [operation({ status: "running" })],
          worker: { available: false, lastHeartbeatAt: null },
        })}
        error={false}
        loading={false}
        onDetails={() => undefined}
        onNext={() => undefined}
        onPrevious={() => undefined}
        onReload={() => undefined}
        onAction={() => undefined}
      />,
    );

    expect(markup).toContain(
      "Running work will be recovered from its durable claim when the Worker recovers.",
    );
    expect(markup).not.toContain("cannot start");
  });

  it("shows exact Cancel facts and effect before asking for the password", () => {
    const target = operation({
      idempotencyKey: "market-cancel-source",
      kind: "market",
      status: "accepted",
    });
    const markup = renderToStaticMarkup(
      <OperatorDataRefreshActionDialog
        action={{ action: "cancel", operation: target }}
        onAccessNotFound={() => undefined}
        onDismiss={() => undefined}
        onStateChanged={() => undefined}
        onSucceeded={() => undefined}
      />,
    );

    expect(markup).toContain("Cancel queued Refresh?");
    expect(markup).toContain("Market Refresh");
    expect(markup).toContain("2026-08-30T08:00:00Z");
    expect(markup).toContain("market-cancel-source");
    expect(markup).toContain("The Worker will never claim this queued receipt");
    expect(markup.indexOf("Effect")).toBeLessThan(markup.indexOf("Current password"));
    expect(markup).not.toContain("New idempotency key");
  });

  it("makes Retry generate a new key automatically and preserves immutable source copy", () => {
    const source = operation({
      idempotencyKey: "industry-failed-source",
      kind: "industry",
      status: "failed",
    });
    const now = new Date("2026-08-30T05:06:07.000Z");
    expect(suggestDataRefreshRetryKey(source.kind, now)).toEqual(expect.stringMatching(/^industry-retry-20260830T050607Z-[0-9a-f-]{36}$/));
    expect(
      suggestDataRefreshRetryKey(source.kind, new Date("2026-08-30T05:06:07.987Z")),
    ).toEqual(expect.stringMatching(/^industry-retry-20260830T050607Z-[0-9a-f-]{36}$/));
    const markup = renderToStaticMarkup(
      <OperatorDataRefreshActionDialog
        action={{ action: "retry", operation: source }}
        now={() => now}
        onAccessNotFound={() => undefined}
        onDismiss={() => undefined}
        onStateChanged={() => undefined}
        onSucceeded={() => undefined}
      />,
    );

    expect(markup).toContain("Retry failed Refresh?");
    expect(markup).toContain("industry-failed-source");
    expect(markup).not.toContain("New idempotency key");
    expect(markup).toContain("The original failed receipt remains unchanged and inspectable");
    expect(markup).toContain("accepted into the FIFO as new queued work");
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
      marketCoverageStart: "2015-01-05",
      marketLastRefreshAt: "2026-08-29T08:00:00Z",
      benchmarkCoverageStart: "2010-01-04",
      benchmarkCoverageEnd: "2026-08-31",
      benchmarkLastPublishedAt: "2026-08-30T08:02:00Z",
      financialCoverageStart: "2015-01-01",
      financialAttemptedThroughSession: "2026-08-29",
      financialCompleteThroughSession: "2026-08-28",
      financialLastRefreshAt: "2026-08-29T08:03:00Z",
      financialPendingInstrumentCount: 2,
      financialDiscoveryGapCount: 1,
      financialEarliestUnresolvedDate: "2026-08-26",
      industryCoverageStart: "2015-01-05",
      industryObservationThroughSession: "2026-08-29",
      industryLastRefreshAt: "2026-08-29T08:04:00Z",
    },
    worker: { available: true, lastHeartbeatAt: "2026-08-30T08:01:00Z" },
    latestByKind: [operation({ outcome: "published", status: "succeeded" })],
    operations: [operation({ outcome: "published", status: "succeeded" })],
    nextCursor: null,
    ...overrides,
  };
}

function renderStatus(data: DatasetOperationalStatus): string {
  return renderToStaticMarkup(
    <OperatorDatasetStatusView
      cursorDepth={0}
      data={data}
      error={false}
      loading={false}
      onDetails={() => undefined}
      onNext={() => undefined}
      onPrevious={() => undefined}
      onReload={() => undefined}
      onAction={() => undefined}
    />,
  );
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
    financialProgress: null,
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
