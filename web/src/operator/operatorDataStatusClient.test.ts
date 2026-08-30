import { describe, expect, it } from "vitest";

import { decodeDatasetOperationalStatus } from "./operatorDataStatusClient";

const operation = {
  idempotency_key: "financial-20260830",
  kind: "financial",
  status: "succeeded",
  outcome: "degraded",
  as_of: null,
  observation_through_session: "2026-08-29",
  phase: "financial",
  attempt_count: 2,
  last_heartbeat_at: "2026-08-30T08:01:00Z",
  data_through_session: "2026-08-29",
  last_refresh_at: "2026-08-30T08:02:00Z",
  financial_complete_through_session: "2026-08-28",
  matched_trigger_count: 9,
  checked_no_structured_change_count: 4,
  accepted_instrument_count: 3,
  failed_instrument_count: 1,
  pending_instrument_count: 2,
  discovery_gap_count: 1,
  failure_code: null,
  last_failure_code: null,
  created_at: "2026-08-30T08:00:00Z",
  started_at: "2026-08-30T08:00:01Z",
  finished_at: "2026-08-30T08:02:00Z",
  updated_at: "2026-08-30T08:02:00Z",
} as const;

const response = {
  head: {
    data_identity: "d".repeat(64),
    prepared_at: "2026-08-29T23:00:00Z",
    data_through_session: "2026-08-29",
    market_research_readiness: true,
    benchmark_research_readiness: true,
    financial_research_readiness: "ready_with_pending",
    industry_research_readiness: true,
  },
  latest_by_kind: [operation],
  operations: [operation],
  next_cursor: "opaque-page",
} as const;

describe("Operator Dataset operational status decoder", () => {
  it("maps the exact bounded safe response", () => {
    expect(decodeDatasetOperationalStatus(response)).toEqual({
      head: {
        dataIdentity: "d".repeat(64),
        preparedAt: "2026-08-29T23:00:00Z",
        dataThroughSession: "2026-08-29",
        marketResearchReadiness: true,
        benchmarkResearchReadiness: true,
        financialResearchReadiness: "ready_with_pending",
        industryResearchReadiness: true,
      },
      latestByKind: [{
        idempotencyKey: "financial-20260830",
        kind: "financial",
        status: "succeeded",
        outcome: "degraded",
        asOf: null,
        observationThroughSession: "2026-08-29",
        phase: "financial",
        attemptCount: 2,
        lastHeartbeatAt: "2026-08-30T08:01:00Z",
        dataThroughSession: "2026-08-29",
        lastRefreshAt: "2026-08-30T08:02:00Z",
        financialCompleteThroughSession: "2026-08-28",
        matchedTriggerCount: 9,
        checkedNoStructuredChangeCount: 4,
        acceptedInstrumentCount: 3,
        failedInstrumentCount: 1,
        pendingInstrumentCount: 2,
        discoveryGapCount: 1,
        failureCode: null,
        lastFailureCode: null,
        createdAt: "2026-08-30T08:00:00Z",
        startedAt: "2026-08-30T08:00:01Z",
        finishedAt: "2026-08-30T08:02:00Z",
        updatedAt: "2026-08-30T08:02:00Z",
      }],
      operations: [expect.objectContaining({ idempotencyKey: "financial-20260830" })],
      nextCursor: "opaque-page",
    });
  });

  it("rejects internal fields, invalid state relationships, and oversized pages", () => {
    expect(() => decodeDatasetOperationalStatus({
      ...response,
      head: { ...response.head, data_identity: "not-a-dataset-identity" },
    })).toThrow("Dataset operational status response is invalid");
    expect(() => decodeDatasetOperationalStatus({
      ...response,
      operations: [{ ...operation, owner_token: "secret-worker" }],
    })).toThrow("Dataset operational status response is invalid");
    expect(() => decodeDatasetOperationalStatus({
      ...response,
      operations: [{ ...operation, status: "running", outcome: "degraded" }],
    })).toThrow("Dataset operational status response is invalid");
    expect(() => decodeDatasetOperationalStatus({
      ...response,
      operations: Array.from({ length: 51 }, () => operation),
    })).toThrow("Dataset operational status response is invalid");
  });

  it("accepts an explicit cancelled terminal state without a mutation control", () => {
    const cancelled = {
      ...operation,
      status: "cancelled",
      outcome: null,
      failure_code: null,
      financial_complete_through_session: null,
      matched_trigger_count: null,
      checked_no_structured_change_count: null,
      accepted_instrument_count: null,
      failed_instrument_count: null,
      pending_instrument_count: null,
      discovery_gap_count: null,
    } as const;

    const decoded = decodeDatasetOperationalStatus({
      ...response,
      latest_by_kind: [cancelled],
      operations: [cancelled],
    });

    expect(decoded.operations[0]?.status).toBe("cancelled");
  });
});
