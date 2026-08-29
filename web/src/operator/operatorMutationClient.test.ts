import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmOperatorProof,
  OperatorMutationError,
  submitInvitationMutation,
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
});
