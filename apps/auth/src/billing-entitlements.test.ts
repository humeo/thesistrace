import { expect, it } from "vitest";
import { effectivePlan, type PaidEntitlement } from "./billing-entitlements.js";

it("keeps the paid higher plan until expiry and revokes only the payment being refunded or disputed", () => {
  const pro: PaidEntitlement = {
    plan: "pro",
    startsAt: new Date("2026-10-01Z"),
    endsAt: new Date("2026-11-01Z"),
    amount: 2000,
    refunded: 0,
    disputed: false,
  };
  const max: PaidEntitlement = { ...pro, plan: "max", amount: 8000 };
  const now = new Date("2026-10-17Z");
  expect(effectivePlan([pro, max], now)).toBe("max");
  expect(effectivePlan([pro, { ...max, refunded: 8000 }], now)).toBe("pro");
  expect(effectivePlan([pro, { ...max, disputed: true }], now)).toBe("pro");
  expect(effectivePlan([{ ...max, refunded: 100 }], now)).toBe("max");
  expect(effectivePlan([pro, max], new Date("2026-11-01Z"))).toBe("free");
  expect(
    effectivePlan([{ ...max, startsAt: new Date("2026-10-18Z") }], now),
  ).toBe("free");
});
