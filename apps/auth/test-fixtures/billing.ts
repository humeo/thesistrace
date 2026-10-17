import { createHmac } from "node:crypto";
import { Creem } from "creem";
import { HTTPClient } from "creem/lib/http.js";
import type { EnabledBillingSettings } from "../src/billing-config.js";

export const billingSettings: EnabledBillingSettings = {
  mode: "test",
  apiOrigin: "https://test-api.creem.io",
  apiKey: "fixture-creem-api-key",
  webhookSecret: "fixture-creem-webhook-secret",
  products: { pro: "prod_pro", max: "prod_max" },
};
export const billingNow = new Date("2026-10-17T12:00:00Z");
export function makeCreemFixture(
  options: { beforeRequest?: (request: Request) => Promise<void> } = {},
) {
  const date = "2026-10-01T00:00:00Z",
    end = "2026-11-01T00:00:00Z";
  const customer = {
    id: "cust_owned",
    mode: "test",
    object: "customer",
    email: "billing@fixture.test",
    country: null,
    created_at: date,
    updated_at: date,
  };
  const products = {
    pro: {
      id: "prod_pro",
      mode: "test",
      object: "product",
      name: "Pro",
      description: "Monthly Pro",
      price: 2000,
      currency: "USD",
      billing_type: "recurring",
      billing_period: "every-month",
      status: "active",
      tax_mode: "exclusive",
      tax_category: "saas",
      created_at: date,
      updated_at: date,
    },
    max: {
      id: "prod_max",
      mode: "test",
      object: "product",
      name: "Max",
      description: "Monthly Max",
      price: 10000,
      currency: "USD",
      billing_type: "recurring",
      billing_period: "every-month",
      status: "active",
      tax_mode: "exclusive",
      tax_category: "saas",
      created_at: date,
      updated_at: date,
    },
  };
  const transaction = {
    id: "txn_paid",
    mode: "test",
    object: "transaction",
    amount: 2000,
    amount_paid: 2000,
    currency: "USD",
    type: "invoice",
    status: "paid",
    refunded_amount: 0,
    subscription: "sub_owned",
    customer: "cust_owned",
    period_start: Date.parse(date),
    period_end: Date.parse(end),
    created_at: Date.parse(date),
  };
  const subscription = {
    id: "sub_owned",
    mode: "test",
    object: "subscription",
    product: products.pro,
    customer,
    collection_method: "charge_automatically",
    status: "active",
    current_period_start_date: date,
    current_period_end_date: end,
    last_transaction_id: transaction.id,
    last_transaction: transaction,
    created_at: date,
    updated_at: date,
  };
  let requestId = "";
  let failUpgrade = false;
  let failCheckout = false;
  let failRead = false;
  const requests: Array<{
    method: string;
    path: string;
    body: Record<string, unknown> | null;
  }> = [];
  const client = new Creem({
    apiKey: billingSettings.apiKey,
    server: "test",
    retryConfig: { strategy: "none" },
    httpClient: new HTTPClient({
      fetcher: async (input) => {
        const req = input instanceof Request ? input : new Request(input);
        const url = new URL(req.url),
          body =
            req.method === "GET"
              ? null
              : ((await req.json()) as Record<string, unknown>);
        requests.push({ method: req.method, path: url.pathname, body });
        await options.beforeRequest?.(req);
        if (url.pathname.startsWith("/v1/products/"))
          return Response.json(
            url.pathname.endsWith("prod_max") ? products.max : products.pro,
          );
        if (url.pathname === "/v1/checkouts" && req.method === "POST") {
          if (failCheckout) {
            failCheckout = false;
            throw new TypeError("Checkout not received");
          }
          requestId = String(body!.request_id);
          return Response.json({
            id: "ch_owned",
            mode: "test",
            object: "checkout",
            status: "pending",
            request_id: requestId,
            product: body!.product_id,
            units: 1,
            checkout_url: "https://www.creem.io/test/payment/owned",
          });
        }
        if (url.pathname === "/v1/subscriptions") {
          if (failRead) {
            failRead = false;
            throw new TypeError("Read unavailable");
          }
          return Response.json(subscription);
        }
        if (url.pathname === "/v1/subscriptions/sub_owned/upgrade") {
          subscription.product =
            body!.product_id === "prod_max" ? products.max : products.pro;
          if (failUpgrade) {
            failUpgrade = false;
            throw new TypeError("Simulated lost provider response");
          }
          return Response.json(subscription);
        }
        if (url.pathname === "/v1/subscriptions/sub_owned/cancel") {
          subscription.status = "scheduled_cancel";
          return Response.json(subscription);
        }
        if (url.pathname === "/v1/transactions")
          return Response.json(transaction);
        if (url.pathname === "/v1/customers/billing")
          return Response.json({
            customer_portal_link: "https://www.creem.io/portal/owned",
          });
        return Response.json(
          { message: "Unexpected fixture operation" },
          { status: 500 },
        );
      },
    }),
  });
  const event = (id: string, eventType: string, object: unknown) => {
    const raw = JSON.stringify({
      id,
      eventType,
      created_at: billingNow.getTime(),
      object,
    });
    const signature = createHmac("sha256", billingSettings.webhookSecret)
      .update(raw)
      .digest("hex");
    return { raw, headers: new Headers({ "creem-signature": signature }) };
  };
  return {
    client,
    requests,
    subscription,
    transaction,
    products,
    event,
    failNextCheckout: () => {
      failCheckout = true;
    },
    failNextSubscriptionRead: () => {
      failRead = true;
    },
    failNextUpgrade: () => {
      failUpgrade = true;
    },
    checkoutCompleted: () =>
      event("evt_checkout", "checkout.completed", {
        id: "ch_owned",
        mode: "test",
        object: "checkout",
        status: "completed",
        request_id: requestId,
        product: products.pro,
        subscription,
        customer,
        units: 1,
        metadata: { billing_request_id: requestId },
      }),
  };
}
