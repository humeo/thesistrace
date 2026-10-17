import type { planConfiguration, PlanKey } from "./quota-policy.js";

export type PaidPlan = Exclude<PlanKey, "free">;
export type BillingPrincipal = Readonly<{ id: string; email: string }>;
export type BillingCommandKind = "checkout" | "change" | "cancel";
export type BillingCommandInput = Readonly<{
  request_id: string;
  plan?: PaidPlan;
}>;
export type BillingCommandResult = Readonly<{
  status: "completed" | "processing" | "failed";
  url?: string;
  code?: string;
}>;
export type BillingSummary = Readonly<{
  plan: PlanKey;
  paid_until: string | null;
  renewal_plan: PaidPlan | null;
  subscription_status: string | null;
  checkout_available: boolean;
  pending_checkout_url: string | null;
  pending_operation: boolean;
  plans: typeof planConfiguration.plans;
}>;
export interface BillingOperations {
  summary(researcherId: string): Promise<BillingSummary>;
  command(
    principal: BillingPrincipal,
    kind: BillingCommandKind,
    input: BillingCommandInput,
  ): Promise<BillingCommandResult>;
  portal(researcherId: string): Promise<string>;
  receiveWebhook(raw: string, headers: Headers): Promise<void>;
}
export class BillingError extends Error {
  constructor(
    readonly code: string,
    readonly status: 400 | 401 | 403 | 409 | 503 = 409,
  ) {
    super(code);
  }
}
