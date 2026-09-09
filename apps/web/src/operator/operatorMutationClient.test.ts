import { afterEach, describe, expect, it, vi } from "vitest";
import { decodeFinancialRefreshProgress } from "./financialRefreshProgress";

import {
  confirmFinancialRefreshProof,
  confirmDataRefreshActionProof,
  confirmIndustryRefreshProof,
  confirmOperatorProof,
  confirmMarketRefreshProof,
  confirmSessionRevocationProof,
  isIsoResearchSession,
  isMarketRefreshIdempotencyKey,
  loadFinancialRefresh,
  loadIndustryRefresh,
  loadMarketRefresh,
  OperatorMutationError,
  submitInvitationMutation,
  submitFinancialRefresh,
  submitDataRefreshAction,
  submitIndustryRefresh,
  submitMarketRefresh,
  submitSessionRevocation,
} from "./operatorMutationClient";

const proof = "00000000-0000-4000-8000-000000000001." + "a".repeat(43);

const progress = {
  phase: "collection", elapsed_seconds: 12, last_progress_at: "2026-08-17T08:00:12Z",
  discovered_announcement_count: 15, processed_company_count: 3,
  updated_company_count: 1, unchanged_company_count: 1, failed_company_count: 1,
  discovery_gaps: [{category: "半年报", start_date: "2026-08-08", end_date: "2026-08-17",
    failure_code: "CNINFO_DISCOVERY_UNAVAILABLE"}],
};

it("strictly decodes bounded company progress and rejects impossible or private fields", () => {
  expect(decodeFinancialRefreshProgress(progress)).toMatchObject({
    processedCompanyCount: 3, updatedCompanyCount: 1, unchangedCompanyCount: 1,
    failedCompanyCount: 1, discoveredAnnouncementCount: 15,
  });
  for (const invalid of [
    undefined,
    {...progress, owner_token: "private"},
    {...progress, processed_company_count: 4},
    {...progress, failed_company_count: -1},
    {...progress, elapsed_seconds: 0.5},
    {...progress, discovery_gaps: Array(6).fill(progress.discovery_gaps[0])},
    {...progress, discovery_gaps: [{...progress.discovery_gaps[0], source_url: "private"}]},
    {...progress, discovery_gaps: [{...progress.discovery_gaps[0], end_date: "2026-02-30"}]},
  ]) expect(() => decodeFinancialRefreshProgress(invalid)).toThrow();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Operator mutation client", () => {
  it("matches the Python ISO Research Session year boundary", () => {
    expect(isIsoResearchSession("0001-01-01")).toBe(true);
    expect(isIsoResearchSession("9999-12-31")).toBe(true);
    expect(isIsoResearchSession("0000-01-01")).toBe(false);
    expect(isIsoResearchSession("2026-02-30")).toBe(false);
  });

  it("sends the otp only to confirmation and forwards only the opaque proof", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({
        expires_at: "2026-08-29T06:01:00.000Z",
        proof,
      }))
      .mockResolvedValueOnce(Response.json({
        email: "researcher@example.com",
        invitation_id: "00000000-0000-4000-8000-000000000041",
        status: "delivered",
      }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const otp = "123456";

    const confirmation = await confirmOperatorProof(
      "issue",
      "researcher@example.com",
      otp,
      controller.signal,
    );
    await submitInvitationMutation(
      "issue",
      "researcher@example.com",
      confirmation.proof,
      controller.signal,
    );

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/auth/operator/proofs",
      expect.objectContaining({
        body: JSON.stringify({
          email: "researcher@example.com",
          operation: "invitation.issue",
          otp,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/auth/operator/invitations/issue",
      expect.objectContaining({
        body: JSON.stringify({ email: "researcher@example.com", proof }),
      }),
    );
    expect(JSON.stringify(fetchMock.mock.calls[1])).not.toContain(otp);
  });

  it("rejects malformed success and maps sanitized proof errors", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(
      Response.json({ proof, expires_at: "not-a-time" }),
    ));
    await expect(
      confirmOperatorProof(
        "reissue",
        "researcher@example.com",
        "123456",
        new AbortController().signal,
      ),
    ).rejects.toEqual(new OperatorMutationError("unavailable"));

    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(
      Response.json({ code: "OPERATOR_PROOF_INVALID" }, { status: 400 }),
    ));
    await expect(
      submitInvitationMutation(
        "reissue",
        "researcher@example.com",
        proof,
        new AbortController().signal,
      ),
    ).rejects.toEqual(new OperatorMutationError("invalid-proof"));
  });

  it("binds Session revocation to one Researcher and excludes the otp from mutation", async () => {
    const researcherId = "00000000-0000-4000-8000-000000000002";
    const otp = "123456";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({
        expires_at: "2026-08-29T06:01:00.000Z",
        proof,
      }))
      .mockResolvedValueOnce(Response.json({
        researcher_id: researcherId,
        revoked_session_count: 2,
        status: "updated",
      }));
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;

    const confirmation = await confirmSessionRevocationProof(
      researcherId,
      otp,
      signal,
    );
    await expect(
      submitSessionRevocation(researcherId, confirmation.proof, signal),
    ).resolves.toEqual({ researcherId, revokedSessionCount: 2 });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/auth/operator/proofs",
      expect.objectContaining({
        body: JSON.stringify({
          operation: "researcher.sessions.revoke",
          otp,
          researcher_id: researcherId,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/auth/operator/researchers/sessions/revoke",
      expect.objectContaining({
        body: JSON.stringify({ proof, researcher_id: researcherId }),
      }),
    );
    expect(JSON.stringify(fetchMock.mock.calls[1])).not.toContain(otp);
  });

  it("rejects malformed Session results and maps protected and stale targets", async () => {
    const researcherId = "00000000-0000-4000-8000-000000000002";
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(
      Response.json({
        researcher_id: researcherId,
        revoked_session_count: -1,
        status: "updated",
      }),
    ));
    await expect(
      submitSessionRevocation(researcherId, proof, new AbortController().signal),
    ).rejects.toEqual(new OperatorMutationError("unavailable"));

    for (const [serverCode, clientCode] of [
      ["OPERATOR_SESSION_TARGET_PROTECTED", "protected-target"],
      ["OPERATOR_SESSION_TARGET_INVALID", "invalid-target"],
    ] as const) {
      vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(
        Response.json({ code: serverCode }, { status: 409 }),
      ));
      await expect(
        submitSessionRevocation(
          researcherId,
          proof,
          new AbortController().signal,
        ),
      ).rejects.toEqual(new OperatorMutationError(clientCode));
    }
  });

  it("binds a Market proof to the exact free-form target and key without forwarding otp", async () => {
    const request = {
      asOf: "2026-08-11T18:00:00+08:00",
      idempotencyKey: "market-20260811T180000+0800",
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({
        expires_at: "2026-08-29T06:01:00.000Z",
        proof,
      }))
      .mockResolvedValueOnce(Response.json({
        as_of: "2026-08-11T10:00:00Z",
        attempt_count: 0,
        data_through_session: null,
        failure_code: null,
        idempotency_key: request.idempotencyKey,
        kind: "market",
        last_failure_code: null,
        last_refresh_at: null,
        outcome: null,
        status: "accepted",
      }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;

    const confirmation = await confirmMarketRefreshProof(
      request,
      signal,
    );
    const operation = await submitMarketRefresh(
      request,
      confirmation.proof,
      signal,
    );

    expect(operation).toMatchObject({
      asOf: "2026-08-11T10:00:00Z",
      idempotencyKey: request.idempotencyKey,
      status: "accepted",
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/auth/operator/proofs",
      expect.objectContaining({
        body: JSON.stringify({
          as_of: request.asOf,
          idempotency_key: request.idempotencyKey,
          operation: "data.refresh.market.submit",
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/operator/data/refreshes/market",
      expect.objectContaining({
        body: JSON.stringify({
          as_of: request.asOf,
          idempotency_key: request.idempotencyKey,
          proof,
        }),
      }),
    );
    expect(JSON.parse(fetchMock.mock.calls[0]![1]!.body as string)).not.toHaveProperty("otp");
  });

  it("binds a Financial proof and parses the safe degraded receipt", async () => {
    const request = {
      idempotencyKey: "financial-20260814-custom",
      observationThroughSession: "2026-08-14",
    };
    const degradedReceipt = {
      progress: null,
      accepted_instrument_count: 1,
      attempt_count: 1,
      checked_no_structured_change_count: 2,
      data_through_session: "2026-08-14",
      discovery_gap_count: 1,
      failed_instrument_count: 1,
      failure_code: null,
      financial_complete_through_session: "2026-08-13",
      idempotency_key: request.idempotencyKey,
      kind: "financial",
      last_failure_code: null,
      last_refresh_at: "2026-08-14T10:00:00Z",
      matched_trigger_count: 3,
      observation_through_session: request.observationThroughSession,
      outcome: "degraded",
      pending_instrument_count: 1,
      status: "succeeded",
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({
        expires_at: "2026-08-29T06:01:00.000Z",
        proof,
      }))
      .mockResolvedValueOnce(Response.json(degradedReceipt, { status: 202 }))
      .mockResolvedValueOnce(Response.json(degradedReceipt));
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;

    const confirmation = await confirmFinancialRefreshProof(
      request,
      signal,
    );
    const submitted = await submitFinancialRefresh(
      request,
      confirmation.proof,
      signal,
    );
    const loaded = await loadFinancialRefresh(request, signal);

    expect(submitted).toMatchObject({
      discoveryGapCount: 1,
      financialCompleteThroughSession: "2026-08-13",
      outcome: "degraded",
    });
    expect(loaded).toEqual(submitted);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/auth/operator/proofs",
      expect.objectContaining({
        body: JSON.stringify({
          idempotency_key: request.idempotencyKey,
          observation_through_session: request.observationThroughSession,
          operation: "data.refresh.financial.submit",
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/operator/data/refreshes/financial",
      expect.objectContaining({
        body: JSON.stringify({
          idempotency_key: request.idempotencyKey,
          observation_through_session: request.observationThroughSession,
          proof,
        }),
      }),
    );
    expect(JSON.parse(fetchMock.mock.calls[0]![1]!.body as string)).not.toHaveProperty("otp");
  });

  it("binds an Industry proof and parses the safe no-change receipt", async () => {
    const request = {
      idempotencyKey: "industry-20260814-custom",
      observationThroughSession: "2026-08-14",
    };
    const receipt = {
      attempt_count: 1,
      data_through_session: "2026-08-14",
      failure_code: null,
      idempotency_key: request.idempotencyKey,
      kind: "industry",
      last_failure_code: null,
      last_refresh_at: "2026-08-14T10:00:00Z",
      observation_through_session: request.observationThroughSession,
      outcome: "no_change",
      status: "succeeded",
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({
        expires_at: "2026-08-29T06:01:00.000Z",
        proof,
      }))
      .mockResolvedValueOnce(Response.json(receipt, { status: 202 }))
      .mockResolvedValueOnce(Response.json(receipt));
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;

    const confirmation = await confirmIndustryRefreshProof(
      request,
      signal,
    );
    const submitted = await submitIndustryRefresh(
      request,
      confirmation.proof,
      signal,
    );
    const loaded = await loadIndustryRefresh(request, signal);

    expect(submitted).toMatchObject({
      dataThroughSession: "2026-08-14",
      kind: "industry",
      outcome: "no_change",
    });
    expect(loaded).toEqual(submitted);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/auth/operator/proofs",
      expect.objectContaining({
        body: JSON.stringify({
          idempotency_key: request.idempotencyKey,
          observation_through_session: request.observationThroughSession,
          operation: "data.refresh.industry.submit",
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/operator/data/refreshes/industry",
      expect.objectContaining({
        body: JSON.stringify({
          idempotency_key: request.idempotencyKey,
          observation_through_session: request.observationThroughSession,
          proof,
        }),
      }),
    );
    expect(JSON.parse(fetchMock.mock.calls[0]![1]!.body as string)).not.toHaveProperty("otp");
  });

  it("round-trips a Python-valid boundary FEFF Market key", async () => {
    const idempotencyKey = "\uFEFFmarket-key";
    expect(isMarketRefreshIdempotencyKey(idempotencyKey)).toBe(true);
    expect(isMarketRefreshIdempotencyKey("\u0085market-key")).toBe(false);
    expect(isMarketRefreshIdempotencyKey(`market-${"😀".repeat(253)}`)).toBe(true);
    expect(isMarketRefreshIdempotencyKey(`market-${"😀".repeat(506)}`)).toBe(false);
    expect(isMarketRefreshIdempotencyKey("market-\0-key")).toBe(false);

    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({
      as_of: "2026-08-11T10:00:00Z",
      attempt_count: 0,
      data_through_session: null,
      failure_code: null,
      idempotency_key: idempotencyKey,
      kind: "market",
      last_failure_code: null,
      last_refresh_at: null,
      outcome: null,
      status: "accepted",
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      loadMarketRefresh(
        { asOf: "2026-08-11T18:00:00+08:00", idempotencyKey },
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ idempotencyKey, status: "accepted" });
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/operator/data/refreshes/market?as_of=2026-08-11T18%3A00%3A00%2B08%3A00&idempotency_key=${encodeURIComponent(idempotencyKey)}`,
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("binds Cancel and Retry proofs to exact immutable receipt actions", async () => {
    const otp = "123456";
    const cancel = {
      action: "cancel" as const,
      kind: "market" as const,
      sourceIdempotencyKey: "market-cancel-source",
      target: "2026-08-11T10:00:00Z",
    };
    const retry = {
      action: "retry" as const,
      kind: "industry" as const,
      newIdempotencyKey: "industry-retry-new",
      sourceIdempotencyKey: "industry-failed-source",
      target: "2026-08-14",
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({
        expires_at: "2026-08-29T06:01:00.000Z",
        proof,
      }))
      .mockResolvedValueOnce(Response.json({
        as_of: cancel.target,
        idempotency_key: cancel.sourceIdempotencyKey,
        kind: cancel.kind,
        observation_through_session: null,
        status: "cancelled",
      }))
      .mockResolvedValueOnce(Response.json({
        expires_at: "2026-08-29T06:01:00.000Z",
        proof,
      }))
      .mockResolvedValueOnce(Response.json({
        as_of: null,
        idempotency_key: retry.newIdempotencyKey,
        kind: retry.kind,
        observation_through_session: retry.target,
        status: "accepted",
      }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;

    const cancelProof = await confirmDataRefreshActionProof(
      cancel,
      otp,
      signal,
    );
    await expect(
      submitDataRefreshAction(cancel, cancelProof.proof, signal),
    ).resolves.toMatchObject({
      idempotencyKey: cancel.sourceIdempotencyKey,
      status: "cancelled",
    });
    const retryProof = await confirmDataRefreshActionProof(retry, otp, signal);
    await expect(
      submitDataRefreshAction(retry, retryProof.proof, signal),
    ).resolves.toMatchObject({
      idempotencyKey: retry.newIdempotencyKey,
      status: "accepted",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/auth/operator/proofs",
      expect.objectContaining({
        body: JSON.stringify({
          kind: cancel.kind,
          operation: "data.refresh.cancel",
          otp,
          source_idempotency_key: cancel.sourceIdempotencyKey,
          target: cancel.target,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/operator/data/refreshes/cancel",
      expect.objectContaining({
        body: JSON.stringify({
          kind: cancel.kind,
          proof,
          source_idempotency_key: cancel.sourceIdempotencyKey,
          target: cancel.target,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/auth/operator/proofs",
      expect.objectContaining({
        body: JSON.stringify({
          kind: retry.kind,
          new_idempotency_key: retry.newIdempotencyKey,
          operation: "data.refresh.retry",
          otp,
          source_idempotency_key: retry.sourceIdempotencyKey,
          target: retry.target,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/operator/data/refreshes/retry",
      expect.objectContaining({
        body: JSON.stringify({
          kind: retry.kind,
          new_idempotency_key: retry.newIdempotencyKey,
          proof,
          source_idempotency_key: retry.sourceIdempotencyKey,
          target: retry.target,
        }),
      }),
    );
    expect(JSON.stringify(fetchMock.mock.calls[1])).not.toContain(otp);
    expect(JSON.stringify(fetchMock.mock.calls[3])).not.toContain(otp);
  });

  it.each([
    ["REFRESH_NOT_CANCELLABLE", "not-cancellable"],
    ["REFRESH_NOT_RETRYABLE", "not-retryable"],
    ["REFRESH_NOT_FOUND", "invalid-target"],
    ["REFRESH_TARGET_CONFLICT", "invalid-target"],
  ] as const)("maps %s to %s without inventing success", async (serverCode, clientCode) => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(
      Response.json({ code: serverCode }, { status: 409 }),
    ));
    await expect(
      submitDataRefreshAction(
        {
          action: "cancel",
          kind: "market",
          sourceIdempotencyKey: "market-cancel-source",
          target: "2026-08-11T10:00:00Z",
        },
        proof,
        new AbortController().signal,
      ),
    ).rejects.toEqual(new OperatorMutationError(clientCode));
  });
});
