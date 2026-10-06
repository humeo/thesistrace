import "../../src/styles.css";
import { createRoot } from "react-dom/client";
import { OperatorDataPage } from "../../src/operator/OperatorDataPage";
import { WorkspaceQueryProvider } from "../../src/shell/WorkspaceQueryProvider";
import type { DataRefreshOperationalStatus, DatasetOperationalStatus } from "../../src/operator/operatorDataStatusClient";

const key = `market-${"long".repeat(35)}`;
const operation: DataRefreshOperationalStatus = {
  idempotencyKey: key, kind: "dataset", status: "accepted", outcome: null,
  asOf: "2026-08-14T18:00:00+08:00", observationThroughSession: null, phase: null,
  attemptCount: 0, lastHeartbeatAt: null, dataThroughSession: null, lastRefreshAt: null,
  financialCompleteThroughSession: null, matchedTriggerCount: null,
  checkedNoStructuredChangeCount: null, financialProgress: null,
  acceptedInstrumentCount: null, failedInstrumentCount: null,
  pendingInstrumentCount: null, discoveryGapCount: null, failureCode: null,
  lastFailureCode: null, createdAt: "2026-08-30T08:00:00Z", startedAt: null,
  finishedAt: null, updatedAt: "2026-08-30T08:00:00Z",
};
const data: DatasetOperationalStatus = {
  head: {
    dataIdentity: "d".repeat(64), preparedAt: "2026-08-29T23:00:00Z",
    dataThroughSession: "2026-08-29", marketResearchReadiness: true,
    benchmarkResearchReadiness: true, financialResearchReadiness: "ready_with_pending",
    industryResearchReadiness: true, marketCoverageStart: "2015-01-05",
    marketLastRefreshAt: "2026-08-29T08:00:00Z",
    benchmarkCoverageStart: "2010-01-04", benchmarkCoverageEnd: "2026-08-31",
    benchmarkLastPublishedAt: "2026-08-30T08:02:00Z",
    financialCoverageStart: "2015-01-01", financialAttemptedThroughSession: "2026-08-29",
    financialCompleteThroughSession: "2026-08-28", financialLastRefreshAt: "2026-08-29T08:03:00Z",
    financialPendingInstrumentCount: 2, financialIndicatorPendingInstrumentCount: 0,
    financialIndicatorCheckedThroughSession: "2026-08-31",
    financialIndicatorCompleteThroughSession: "2026-08-31",
    financialDiscoveryGapCount: 1, financialEarliestUnresolvedDate: "2026-08-26",
    industryCoverageStart: "2015-01-05", industryObservationThroughSession: "2026-08-29",
    industryLastRefreshAt: "2026-08-29T08:04:00Z",
  },
  worker: { available: true, lastHeartbeatAt: "2026-08-30T08:01:00Z" },
  latestByKind: [operation], operations: [operation], nextCursor: null,
};

// Deterministic browser fixture: the real page drives the current HTTP contract.
const toWire = (value: unknown): unknown => Array.isArray(value) ? value.map(toWire)
  : value !== null && typeof value === "object" ? Object.fromEntries(Object.entries(value).map(([name, item]) =>
    [name.replace(/[A-Z]/g, char => `_${char.toLowerCase()}`), toWire(item)])) : value;
let rows: DataRefreshOperationalStatus[] = [];
let completed = false;
const fixtureFetch: typeof fetch = async (input, options) => {
  const url = new URL(String(input), window.location.origin);
  const command = options?.body ? JSON.parse(String(options.body)) : {};
  if (url.pathname === "/api/auth/operator/proofs") return Response.json({
    proof: "00000000-0000-4000-8000-000000000041." + "a".repeat(43), expires_at: "2099-01-01T00:00:00Z",
  });
  if (url.pathname === "/api/operator/data/status") return Response.json(toWire({
    ...data, latestByKind: rows.slice(0, 1), operations: rows,
    head: { ...data.head,
      dataIdentity: completed ? "e".repeat(64) : data.head!.dataIdentity,
      dataThroughSession: completed ? "2026-08-14" : "2026-08-13",
      benchmarkCoverageEnd: completed ? "2026-08-14" : "2026-08-13",
      financialResearchReadiness: completed ? "ready" : "ready_with_pending",
      financialAttemptedThroughSession: completed ? "2026-08-14" : "2026-08-13",
      financialCompleteThroughSession: completed ? "2026-08-14" : "2026-08-12",
      financialIndicatorCheckedThroughSession: completed ? "2026-08-14" : "2026-08-13",
      financialIndicatorCompleteThroughSession: completed ? "2026-08-14" : "2026-08-13",
      financialPendingInstrumentCount: completed ? 0 : 2,
      financialDiscoveryGapCount: completed ? 0 : 1,
      financialEarliestUnresolvedDate: completed ? null : "2026-08-13",
      industryObservationThroughSession: completed ? "2026-08-14" : "2026-08-13",
    },
  }));
  if (url.pathname === "/api/operator/data/refreshes/retry") {
    const previous = rows.find(item => item.idempotencyKey === command.source_idempotency_key)!;
    completed = true;
    rows.unshift({ ...previous, idempotencyKey: command.new_idempotency_key, status: "succeeded",
      outcome: "published", phase: "publication", dataThroughSession: "2026-08-14",
      lastRefreshAt: "2026-08-14T10:01:00Z", failureCode: null, lastFailureCode: null });
    return Response.json({ kind: "dataset", idempotency_key: command.new_idempotency_key,
      as_of: previous.asOf, observation_through_session: null, status: "accepted" }, { status: 202 });
  }
  if (url.pathname === "/api/operator/data/refreshes/dataset") {
    if (options?.method === "POST") {
      rows.unshift({ ...operation, idempotencyKey: command.idempotency_key, asOf: command.as_of,
        status: "failed", phase: "financial", attemptCount: 1,
        startedAt: "2026-08-14T10:00:00Z", lastHeartbeatAt: "2026-08-14T10:00:10Z",
        finishedAt: "2026-08-14T10:00:10Z", failureCode: "FINANCIAL_PREPARATION_INCOMPLETE" });
    }
    const item = options?.method === "POST" ? rows[0]! : rows.find(item => item.idempotencyKey === url.searchParams.get("idempotency_key"))!;
    return Response.json({ idempotency_key: item.idempotencyKey, kind: "dataset", as_of: item.asOf,
      attempt_count: item.attemptCount, status: item.status, outcome: item.outcome,
      data_through_session: item.dataThroughSession, last_refresh_at: item.lastRefreshAt,
      failure_code: item.failureCode, last_failure_code: item.lastFailureCode, phase: item.phase,
      completed_stages: item.status === "succeeded" ? ["market", "financial", "industry"] : ["market"],
    }, { status: options?.method === "POST" ? 202 : 200 });
  }
  throw new Error(`Unexpected browser fixture request: ${url.pathname}`);
};
window.fetch = fixtureFetch;
createRoot(document.getElementById("root")!).render(<WorkspaceQueryProvider researcherId="operator-fixture"><main className="console-workspace mx-auto max-w-[1280px] p-8"><OperatorDataPage /></main></WorkspaceQueryProvider>);
