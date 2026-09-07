// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test, vi } from "vitest";
import * as refreshClient from "./operatorMutationClient";

import {
  FinancialRefreshReconciliation,
  FinancialRefreshReceipt,
  OperatorFinancialRefreshPanel,
  suggestFinancialRefreshKey,
} from "./OperatorFinancialRefreshPanel";
import type { FinancialRefreshOperation } from "./operatorMutationClient";
import { FinancialRefreshTelemetry } from "./FinancialRefreshTelemetry";

test("polls company checkpoints, preserves stale counts, and stops at a terminal receipt", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.useFakeTimers({toFake: ["setTimeout", "clearTimeout"]});
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  const running = financialOperation({
    status: "running", outcome: null,
    progress: {phase: "collection", elapsedSeconds: 5, lastProgressAt: null,
      discoveredAnnouncementCount: 10, processedCompanyCount: 1, updatedCompanyCount: 1,
      unchangedCompanyCount: 0, failedCompanyCount: 0, discoveryGaps: []},
  });
  const publishing = {...running, progress: {...running.progress!, phase: "publication" as const,
    processedCompanyCount: 2, updatedCompanyCount: 2}};
  vi.spyOn(refreshClient, "confirmFinancialRefreshProof").mockResolvedValue({expiresAt: "2026-08-14T08:00:00Z", proof: "test-only"});
  vi.spyOn(refreshClient, "submitFinancialRefresh").mockResolvedValue(running);
  const load = vi.spyOn(refreshClient, "loadFinancialRefresh")
    .mockResolvedValueOnce(publishing)
    .mockRejectedValueOnce(new Error("temporary test outage"))
    .mockResolvedValueOnce({...publishing, status: "succeeded", outcome: "published",
      progress: {...publishing.progress, phase: "finished"}})
    .mockRejectedValue(new Error("must stop polling after terminal"));
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const fill = async (selector: string, value: string, event: string) => {
    await act(async () => {
      const input = host.querySelector<HTMLInputElement>(selector)!;
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
      input.dispatchEvent(new Event(event, {bubbles: true}));
    });
  };
  const tick = () => act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
  try {
    await act(async () => {root.render(<OperatorFinancialRefreshPanel onAccessNotFound={() => undefined} />);});
    await fill("#operator-financial-target", "2026-08-14", "change");
    await act(async () => {host.querySelector("form")!.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));});
    await fill('input[type="password"]', "test-only-password", "input");
    await act(async () => {host.querySelector("dialog form")!.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));});
    expect(host.textContent).toContain("Collecting company statements");
    await tick();
    expect(host.textContent).toContain("Companies processed2");
    expect(host.textContent).toContain("Preparing Dataset publication");
    expect(host.textContent).toContain("not published yet");
    await tick();
    expect(host.textContent).toContain("Companies processed2");
    expect(host.textContent).toContain("Status is temporarily unavailable");
    await tick();
    expect(host.textContent).toContain("Financial data published");
    expect(host.textContent).not.toContain("not published yet");
    await tick();
    expect(host.textContent).not.toContain("Status is temporarily unavailable");
    expect(load).toHaveBeenCalledWith(expect.objectContaining({idempotencyKey: running.idempotencyKey}), expect.any(AbortSignal));
  } finally {
    await act(async () => {root.unmount();});
    host.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});

test("renders focused Financial target without a key field", () => {
  const markup = renderToStaticMarkup(
    <OperatorFinancialRefreshPanel onAccessNotFound={() => undefined} />,
  );

  expect(markup).toContain("Financial Refresh");
  expect(markup).toContain("Observation-through Research Session");
  expect(markup).toContain('for="operator-financial-target"');
  expect(markup).toContain('id="operator-financial-target"');
  expect(markup).toContain('type="date"');
  expect(markup).not.toContain("Idempotency key");
  expect(markup).toContain("Select the observation-through Research Session.");
  expect(markup).not.toContain("exactly as accepted by the CLI");
  expect(markup).not.toContain(
    "Choose the exact Research Session through which disclosures are observed.",
  );
  expect(markup).not.toContain("Accepted is queued, not published.");
});

test("automatically generates a unique Financial key without selecting a target", () => {
  expect(
    suggestFinancialRefreshKey(new Date("2026-08-30T05:06:07.000Z")),
  ).toEqual(expect.stringMatching(/^financial-20260830T050607Z-[0-9a-f-]{36}$/));
  expect(
    suggestFinancialRefreshKey(new Date("2026-08-30T05:06:07.996Z")),
  ).toEqual(expect.stringMatching(/^financial-20260830T050607Z-[0-9a-f-]{36}$/));
});

test("shows checkpoint telemetry while collection is running, without claiming publication", () => {
  const markup = renderToStaticMarkup(
    <FinancialRefreshReceipt
      operation={financialOperation({
        status: "running",
        outcome: null,
        progress: {
          phase: "collection",
          elapsedSeconds: 12,
          lastProgressAt: "2026-08-17T08:00:12Z",
          discoveredAnnouncementCount: 10,
          processedCompanyCount: 3,
          updatedCompanyCount: 1,
          unchangedCompanyCount: 1,
          failedCompanyCount: 1,
          discoveryGaps: [{
            category: "半年报", startDate: "2026-08-08", endDate: "2026-08-17",
            failureCode: "CNINFO_DISCOVERY_UNAVAILABLE",
          }],
        },
      })}
      pollError={false}
    />,
  );

  expect(markup).toContain("Collecting company statements");
  expect(markup).toContain("<dt>Companies processed</dt><dd>3</dd>");
  expect(markup).toContain("<dt>With data changes</dt><dd>1</dd>");
  expect(markup).toContain("<dt>Without data changes</dt><dd>1</dd>");
  expect(markup).toContain("<dt>Companies failed</dt><dd>1</dd>");
  expect(markup).toContain("12s");
  expect(markup).toContain("半年报");
  expect(markup).toContain("CNINFO_DISCOVERY_UNAVAILABLE");
  expect(markup).toContain("not published yet");
  expect(markup).not.toContain("100%");
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

test("keeps unknown discovery distinct from zero and publication distinct from finished", () => {
  const base = {
    elapsedSeconds: 30, lastProgressAt: null, discoveredAnnouncementCount: null,
    processedCompanyCount: 0, updatedCompanyCount: 0, unchangedCompanyCount: 0,
    failedCompanyCount: 0, discoveryGaps: null,
  };
  const discovery = renderToStaticMarkup(<FinancialRefreshTelemetry progress={{...base, phase: "discovery"}} />);
  expect(discovery).toContain("<dt>Announcements discovered</dt><dd>Unknown</dd>");
  expect(discovery).toContain("<dt>Companies processed</dt><dd>0</dd>");
  const publication = renderToStaticMarkup(<FinancialRefreshTelemetry progress={{...base, phase: "publication"}} />);
  expect(publication).toContain("Preparing Dataset publication");
  expect(publication).toContain("not published yet");
  const finished = renderToStaticMarkup(<FinancialRefreshTelemetry progress={{...base, phase: "finished"}} />);
  expect(finished).not.toContain("not published yet");
  expect(finished).not.toContain("Updates every");
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
    progress: null,
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

test("automatically keeps a submission key across confirmation retries and changes it for new work", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const proof = vi.spyOn(refreshClient, "confirmFinancialRefreshProof")
    .mockRejectedValueOnce(new Error("temporary outage"))
    .mockResolvedValue({expiresAt: "2026-08-14T08:00:00Z", proof: "test-only"});
  const submit = vi.spyOn(refreshClient, "submitFinancialRefresh")
    .mockResolvedValue(financialOperation({status: "succeeded", outcome: "published"}));
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const send = async (selector: string) => act(async () => {
    host.querySelector(selector)!.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
  });
  const fill = async (selector: string, value: string, event: string) => act(async () => {
    const input = host.querySelector<HTMLInputElement>(selector)!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event(event, {bubbles: true}));
  });
  try {
    await act(async () => root.render(<OperatorFinancialRefreshPanel onAccessNotFound={() => undefined} />));
    expect(host.querySelector('input[type="text"]')).toBeNull();
    await fill('input[type="date"]', "2026-08-14", "change");
    await send("form");
    await fill('input[type="password"]', "test-only-password", "input");
    await send("dialog form");
    await send("dialog form");
    expect(proof.mock.calls[0]![0].idempotencyKey).toBe(proof.mock.calls[1]![0].idempotencyKey);
    const firstKey = submit.mock.calls[0]![0].idempotencyKey;
    await send("form");
    await fill('input[type="password"]', "test-only-password", "input");
    await send("dialog form");
    expect(submit.mock.calls[1]![0].idempotencyKey).not.toBe(firstKey);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  }
});
