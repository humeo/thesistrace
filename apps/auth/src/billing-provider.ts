import { Creem } from "creem";
import type { ProductEntity } from "creem/models/components/productentity.js";
import { BillingError, type PaidPlan } from "./billing-contract.js";
import type {
  BillingSettings,
  EnabledBillingSettings,
} from "./billing-config.js";
import { planConfiguration } from "./quota-policy.js";

/** The official SDK owns protocol and signature handling; this adapter checks our product contract. */
export class BillingProvider {
  private readonly client: Creem | null;
  constructor(
    readonly settings: BillingSettings,
    client?: Creem,
  ) {
    this.client =
      settings.mode === "disabled"
        ? null
        : (client ??
          new Creem({
            apiKey: settings.apiKey,
            serverURL: settings.apiOrigin,
            timeoutMs: 15_000,
            retryConfig: { strategy: "none" },
          }));
  }
  get enabled() {
    return this.settings.mode !== "disabled";
  }
  get sdk(): Creem {
    if (!this.client) throw new BillingError("BILLING_NOT_CONFIGURED", 503);
    return this.client;
  }
  get configuration(): EnabledBillingSettings {
    if (this.settings.mode === "disabled")
      throw new BillingError("BILLING_NOT_CONFIGURED", 503);
    return this.settings;
  }
  checkMode(mode: string) {
    if (mode !== (this.configuration.mode === "live" ? "prod" : "test"))
      throw new BillingError("BILLING_MODE_MISMATCH", 400);
  }
  productId(plan: PaidPlan) {
    return this.configuration.products[plan];
  }
  planForProduct(id: string): PaidPlan {
    if (id === this.configuration.products.pro) return "pro";
    if (id === this.configuration.products.max) return "max";
    throw new BillingError("BILLING_PRODUCT_UNKNOWN", 503);
  }
  validateProduct(product: ProductEntity): PaidPlan {
    this.checkMode(product.mode);
    const plan = this.planForProduct(product.id);
    if (
      product.currency !== "USD" ||
      product.price !== planConfiguration.plans[plan].monthly_price_usd * 100 ||
      product.billingType !== "recurring" ||
      product.billingPeriod !== "every-month" ||
      product.taxMode !== "exclusive" ||
      (product.trialPeriodDays ?? 0) > 0 ||
      product.businessNetPricing === true
    )
      throw new BillingError("BILLING_PRODUCT_INVALID", 503);
    return plan;
  }
  async product(plan: PaidPlan) {
    const product = await this.sdk.products.get(this.productId(plan));
    if (this.validateProduct(product) !== plan || product.status !== "active")
      throw new BillingError("BILLING_PRODUCT_INVALID", 503);
    return product;
  }
}
export function paymentUrl(value: string | undefined): string {
  if (value === undefined)
    throw new BillingError("BILLING_PROVIDER_RESPONSE_INVALID", 503);
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    !(url.hostname === "creem.io" || url.hostname.endsWith(".creem.io"))
  )
    throw new BillingError("BILLING_PROVIDER_RESPONSE_INVALID", 503);
  return url.href;
}
export function entityId(value: string | { id: string } | undefined): string {
  if (value === undefined)
    throw new BillingError("BILLING_PROVIDER_RESPONSE_INVALID", 503);
  return typeof value === "string" ? value : value.id;
}
