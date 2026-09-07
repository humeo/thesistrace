import { describe, expect, it, vi } from "vitest";

import { ResendDeliveryError, sendResendEmail } from "./resend.js";

const settings = {
  apiKey: "resend-test-key",
  apiUrl: "http://127.0.0.1:8300",
  fromEmail: "ThesisTrace <noreply@thesistrace.test>",
};

describe("direct Resend delivery", () => {
  it("posts one bounded transaction email to the configured Resend API", async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      Response.json({ id: "email-id" }),
    );

    await sendResendEmail(
      settings,
      {
        html: '<a href="https://thesistrace.test/reset-password#token=secret">Reset</a>',
        subject: "Reset your ThesisTrace password",
        text: "Reset from the link in this email.",
        to: "researcher@example.com",
      },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledOnce();
    const [url, init] = fetcher.mock.calls[0] ?? [];
    expect(url).toBe("http://127.0.0.1:8300/emails");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("authorization")).toBe(
      "Bearer resend-test-key",
    );
    expect(JSON.parse(String(init?.body))).toEqual({
      from: settings.fromEmail,
      html: expect.stringContaining("#token=secret"),
      subject: "Reset your ThesisTrace password",
      text: "Reset from the link in this email.",
      to: ["researcher@example.com"],
    });
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it.each([
    [
      "provider rejection",
      vi.fn<typeof fetch>(async () => new Response("token-canary", { status: 422 })),
    ],
    [
      "transport failure",
      vi.fn<typeof fetch>(async () => {
        throw new Error("token-canary private-provider-body");
      }),
    ],
  ])("returns one sanitized error for %s", async (_case, fetcher) => {
    await expect(
      sendResendEmail(
        settings,
        {
          html: "token-canary",
          subject: "Invitation",
          text: "token-canary",
          to: "researcher@example.com",
        },
        fetcher,
      ),
    ).rejects.toEqual(new ResendDeliveryError());
  });
});
