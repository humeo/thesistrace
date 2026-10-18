import type { PlanKey } from "./quota-policy.js";

export type PaidEntitlement = Readonly<{
  plan: Exclude<PlanKey, "free">;
  startsAt: Date;
  endsAt: Date;
  amount: number;
  refunded: number;
  fullyRefunded: boolean;
  disputed: boolean;
}>;

/** Billing product changes never overwrite the rights supported by a paid transaction. */
export function effectivePlan(
  payments: readonly PaidEntitlement[],
  now: Date,
): PlanKey {
  let plan: PlanKey = "free";
  for (const payment of payments) {
    if (
      payment.startsAt > now ||
      payment.endsAt <= now ||
      payment.disputed ||
      payment.amount < 0 ||
      payment.fullyRefunded ||
      (payment.amount > 0 && payment.refunded >= payment.amount)
    )
      continue;
    if (payment.plan === "max") return "max";
    plan = "pro";
  }
  return plan;
}
