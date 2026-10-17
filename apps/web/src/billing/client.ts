import { z } from "zod";
import { coreFetch } from "../auth/coreFetch";
const plan = z.enum(["free", "pro", "max"]);
const count = z.number().int().nonnegative();
const limits = z
  .object({
    monthly_price_usd: count,
    daily_model_budget_usd: z.number().nonnegative(),
    daily_run_limit: count,
    active_daily_track_limit: count,
  })
  .strict();
export const billingSchema = z
  .object({
    plan,
    paid_until: z.string().nullable(),
    renewal_plan: z.enum(["pro", "max"]).nullable(),
    subscription_status: z.string().nullable(),
    checkout_available: z.boolean(),
    pending_checkout_url: z.string().nullable(),
    pending_operation: z.boolean(),
    plans: z.object({ free: limits, pro: limits, max: limits }).strict(),
  })
  .strict();
export type BillingSummary = z.infer<typeof billingSchema>;
export type Plan = z.infer<typeof plan>;
export type BillingCommand = {
  kind: "checkout" | "change" | "cancel";
  plan?: Exclude<Plan, "free">;
  request_id: string;
};
export const coreUsageSchema = z
  .object({
    timezone: z.string(),
    resets_at: z.string(),
    research: z
      .object({
        actual: count,
        reserved: count,
        remaining: count.nullable(),
        limit: count.nullable(),
      })
      .strict(),
    tracking: z
      .object({
        limit: count.nullable(),
        selected_track_ids: z.array(z.string()),
        selection_required: z.boolean(),
        retained_count: count,
      })
      .strict(),
  })
  .strict();
export const modelUsageSchema = z
  .object({
    timezone: z.string(),
    resets_at: z.string(),
    actual_nanodollars: count,
    reserved_nanodollars: count,
    remaining_nanodollars: count.nullable(),
    limit_nanodollars: count.nullable(),
  })
  .strict();
export class BillingRequestError extends Error {
  constructor(readonly code: string) {
    super(code);
  }
}
async function json(path: string, init?: RequestInit) {
  const response = await coreFetch(path, init);
  const body: unknown = await response.json();
  if (!response.ok)
    throw new BillingRequestError(
      z.object({ code: z.string() }).safeParse(body).data?.code ??
        "BILLING_UNAVAILABLE",
    );
  return body;
}
export const readBilling = (signal?: AbortSignal) =>
  json("/api/auth/billing", { signal }).then((data) =>
    billingSchema.parse(data),
  );
export const readCoreUsage = (signal?: AbortSignal) =>
  json("/api/billing/usage", { signal }).then((data) =>
    coreUsageSchema.parse(data),
  );
export const readModelUsage = (signal?: AbortSignal) =>
  json("/api/agent/billing/usage", { signal }).then((data) =>
    modelUsageSchema.parse(data),
  );
export function hostedPaymentUrl(value: string) {
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    !(url.hostname === "creem.io" || url.hostname.endsWith(".creem.io"))
  )
    throw new BillingRequestError("BILLING_UNAVAILABLE");
  return url.href;
}
export async function submitBilling(command: BillingCommand) {
  const { kind, ...body } = command;
  const result = z
    .object({
      status: z.enum(["completed", "processing", "failed"]),
      url: z.string().optional(),
      code: z.string().optional(),
    })
    .strict()
    .parse(
      await json(`/api/auth/billing/${kind}`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    );
  if (result.status === "failed")
    throw new BillingRequestError(result.code ?? "BILLING_UNAVAILABLE");
  return {
    ...result,
    url: result.url === undefined ? undefined : hostedPaymentUrl(result.url),
  };
}
export async function billingPortal() {
  return hostedPaymentUrl(
    z
      .object({ url: z.string() })
      .strict()
      .parse(await json("/api/auth/billing/portal", { method: "POST" })).url,
  );
}
