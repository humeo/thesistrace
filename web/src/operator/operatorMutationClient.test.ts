import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmOperatorProof,
  confirmSessionRevocationProof,
  OperatorMutationError,
  submitInvitationMutation,
  submitSessionRevocation,
} from "./operatorMutationClient";

const proof = "00000000-0000-4000-8000-000000000001." + "a".repeat(43);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Operator mutation client", () => {
  it("sends the password only to confirmation and forwards only the opaque proof", async () => {
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
    const password = "correct-horse-battery-staple";

    const confirmation = await confirmOperatorProof(
      "issue",
      "researcher@example.com",
      password,
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
          password,
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
    expect(JSON.stringify(fetchMock.mock.calls[1])).not.toContain(password);
  });

  it("rejects malformed success and maps sanitized proof errors", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(
      Response.json({ proof, expires_at: "not-a-time" }),
    ));
    await expect(
      confirmOperatorProof(
        "reissue",
        "researcher@example.com",
        "correct-horse-battery-staple",
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

  it("binds Session revocation to one Researcher and excludes the password from mutation", async () => {
    const researcherId = "00000000-0000-4000-8000-000000000002";
    const password = "correct-horse-battery-staple";
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
      password,
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
          password,
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
    expect(JSON.stringify(fetchMock.mock.calls[1])).not.toContain(password);
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
});
