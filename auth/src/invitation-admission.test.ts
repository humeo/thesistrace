import { describe, expect, it } from "vitest";

import { InvitationAdmission } from "./invitation-admission.js";

describe("Invitation admission scope", () => {
  it("admits only the exact canonical email inside one async scope", async () => {
    const admission = new InvitationAdmission();

    expect(admission.allows("researcher@example.com")).toBe(false);
    expect(admission.isActive()).toBe(false);
    await admission.run("researcher@example.com", async () => {
      expect(admission.isActive()).toBe(true);
      expect(admission.allows("researcher@example.com")).toBe(true);
      expect(admission.allows("other@example.com")).toBe(false);
      await Promise.resolve();
      expect(admission.allows("researcher@example.com")).toBe(true);
    });
    expect(admission.allows("researcher@example.com")).toBe(false);
    expect(admission.isActive()).toBe(false);
  });
});
