/** Deterministic provider boundary used only by isolated product acceptance. */
import { createHmac, randomUUID } from "node:crypto";
const secret = "fixture-creem-webhook-secret";
const customers = new Map(),
  checkouts = new Map(),
  subscriptions = new Map(),
  transactions = new Map();
const product = (max) => ({
  id: max ? "prod_max" : "prod_pro",
  mode: "test",
  object: "product",
  name: max ? "Max" : "Pro",
  description: "Monthly subscription",
  price: max ? 10000 : 2000,
  currency: "USD",
  billing_type: "recurring",
  billing_period: "every-month",
  status: "active",
  tax_mode: "exclusive",
  tax_category: "saas",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
});
const identifier = (prefix) => prefix + "_" + randomUUID().replaceAll("-", "");
const json = (res, status, body) => {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
};
async function read(req) {
  let value = "";
  for await (const chunk of req) value += chunk;
  if (value.length > 32768) throw new Error("Large fixture input");
  return JSON.parse(value || "{}");
}
async function deliver(type, object) {
  const raw = JSON.stringify({
    id: identifier("evt"),
    eventType: type,
    created_at: Date.now(),
    object,
  });
  const response = await fetch("http://auth:8200/api/auth/billing/webhook", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "creem-signature": createHmac("sha256", secret).update(raw).digest("hex"),
    },
    body: raw,
  });
  if (!response.ok) throw new Error("Fixture callback was not accepted");
}
function later(type, object) {
  const snapshot = structuredClone(object);
  void deliver(type, snapshot).catch(() =>
    process.stderr.write("Creem fixture callback failed\n"),
  );
}
function payment(subscription, amount) {
  const transaction = {
    id: identifier("txn"),
    mode: "test",
    object: "transaction",
    amount,
    amount_paid: amount,
    currency: "USD",
    type: "invoice",
    status: "paid",
    refunded_amount: 0,
    subscription: subscription.id,
    customer: subscription.customer.id,
    period_start: Date.parse(subscription.current_period_start_date),
    period_end: Date.parse(subscription.current_period_end_date),
    created_at: Date.now(),
  };
  transactions.set(transaction.id, transaction);
  subscription.last_transaction_id = transaction.id;
  subscription.last_transaction = transaction;
  return transaction;
}
export async function handleCreemFake(req, res) {
  const url = new URL(req.url ?? "/", "http://creem-fake");
  if (
    !url.pathname.startsWith("/v1/") &&
    !url.pathname.startsWith("/__test/creem/")
  )
    return false;
  try {
    const body = req.method === "GET" ? {} : await read(req);
    if (req.method === "GET" && url.pathname.startsWith("/v1/products/")) {
      json(res, 200, product(url.pathname.endsWith("prod_max")));
      return true;
    }
    if (url.pathname === "/v1/checkouts" && req.method === "POST") {
      let customer = body.customer?.id
        ? customers.get(body.customer.id)
        : undefined;
      if (!customer) {
        customer = {
          id: identifier("cust"),
          mode: "test",
          object: "customer",
          email: body.customer.email,
          country: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        customers.set(customer.id, customer);
      }
      const id = identifier("ch");
      const checkout = {
        id,
        mode: "test",
        object: "checkout",
        status: "pending",
        request_id: body.request_id,
        product: product(body.product_id === "prod_max"),
        customer,
        units: 1,
        metadata: body.metadata,
        checkout_url: `https://test.creem.io/checkout/${id}`,
        success_url: body.success_url,
      };
      checkouts.set(id, checkout);
      json(res, 200, checkout);
      return true;
    }
    if (url.pathname === "/v1/checkouts" && req.method === "GET") {
      json(res, 200, checkouts.get(url.searchParams.get("checkout_id")));
      return true;
    }
    if (url.pathname === "/v1/subscriptions" && req.method === "GET") {
      json(
        res,
        200,
        subscriptions.get(url.searchParams.get("subscription_id")),
      );
      return true;
    }
    if (url.pathname === "/v1/transactions" && req.method === "GET") {
      json(res, 200, transactions.get(url.searchParams.get("transaction_id")));
      return true;
    }
    if (url.pathname === "/v1/customers/billing") {
      json(res, 200, {
        customer_portal_link: `https://test.creem.io/portal/${body.customer_id}`,
      });
      return true;
    }
    const mutation = url.pathname.match(
      /^\/v1\/subscriptions\/([^/]+)\/(upgrade|cancel)$/,
    );
    if (mutation && req.method === "POST") {
      const subscription = subscriptions.get(mutation[1]);
      if (!subscription) throw new Error("Unknown subscription");
      let paid = false;
      if (mutation[2] === "cancel") subscription.status = "scheduled_cancel";
      else {
        const previous = subscription.product.price;
        subscription.product = product(body.product_id === "prod_max");
        if (body.update_behavior === "proration-charge-immediately") {
          payment(subscription, subscription.product.price - previous);
          paid = true;
        }
      }
      json(res, 200, subscription);
      later(
        paid
          ? "subscription.paid"
          : mutation[2] === "cancel"
            ? "subscription.scheduled_cancel"
            : "subscription.update",
        subscription,
      );
      return true;
    }
    if (url.pathname === "/__test/creem/complete" && req.method === "POST") {
      const checkout = checkouts.get(body.checkout_id);
      if (!checkout) throw new Error("Unknown checkout");
      if (checkout.status !== "completed") {
        const start = new Date(),
          end = new Date(start);
        end.setUTCMonth(end.getUTCMonth() + 1);
        const subscription = {
          id: identifier("sub"),
          mode: "test",
          object: "subscription",
          product: checkout.product,
          customer: checkout.customer,
          collection_method: "charge_automatically",
          status: "active",
          current_period_start_date: start.toISOString(),
          current_period_end_date: end.toISOString(),
          created_at: start.toISOString(),
          updated_at: start.toISOString(),
        };
        subscriptions.set(subscription.id, subscription);
        // Private test control models the provider's settled amount, including a fully discounted invoice.
        const amount = body.amount_paid ?? subscription.product.price;
        if (!Number.isSafeInteger(amount) || amount < 0 || amount > subscription.product.price)
          throw new Error("Invalid fixture payment amount");
        payment(subscription, amount);
        checkout.subscription = subscription;
        checkout.status = "completed";
        await deliver("checkout.completed", checkout);
        await deliver("subscription.paid", subscription);
      }
      json(res, 200, { return_url: checkout.success_url });
      return true;
    }
    json(res, 404, { message: "Unknown Creem fixture operation" });
  } catch {
    json(res, 500, { message: "Creem fixture operation failed" });
  }
  return true;
}
