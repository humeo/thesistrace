import { describe, expect, it } from "vitest";

import { verificationCodeEmail } from "./email-code.js";

describe("verification code email", () => {
  it("embeds its brand icon without a loopback image URL", async () => {
    const email = await verificationCodeEmail("researcher@example.com", "123456", "sign in to Quantgrove");

    expect(email.html).toContain('src="cid:quantgrove-icon"');
    expect(email.html).not.toMatch(/(?:127\.0\.0\.1|localhost)/);
    expect(email.attachments).toHaveLength(1);
    expect(email.attachments?.[0]).toMatchObject({
      content_id: "quantgrove-icon",
      content_type: "image/png",
      filename: "quantgrove-icon.png",
    });
    expect(Buffer.from(email.attachments![0]!.content, "base64").subarray(0, 8))
      .toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  });
});
