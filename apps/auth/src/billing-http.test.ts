import { expect, it } from "vitest";
import { createBillingApp } from "./billing-http.js";
import { planConfiguration } from "./quota-policy.js";

it("requires an active owner, same-origin mutation and a server-defined paid plan", async () => {
  let authenticated = true;
  const app = createBillingApp({
    publicOrigin: "http://auth.test",
    requireResearcher: async () =>
      authenticated
        ? { id: "owner", email: "owner@fixture.test" }
        : new Response(null, { status: 401 }),
    billing: {
      summary: async () => ({
        plan: "free",
        paid_until: null,
        renewal_plan: null,
        subscription_status: null,
        checkout_available: true,
        pending_checkout_url: null,
        pending_operation: false,
        plans: planConfiguration.plans,
      }),
      command: async (principal, kind, input) => ({
        status: "completed",
        url: `https://www.creem.io/${principal.id}/${kind}/${input.plan}`,
      }),
      portal: async () => "https://www.creem.io/portal",
      receiveWebhook: async () => {},
    },
  });
  const request = (body: unknown, origin = "http://auth.test") =>
    app.request("http://auth.test/checkout", {
      method: "POST",
      headers: { origin, "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  const body = {
    request_id: "b50a37be-7865-4c6a-bd8f-e48dc08f82af",
    plan: "pro",
  };
  authenticated = false;
  expect((await request(body)).status).toBe(401);
  authenticated = true;
  expect((await request(body, "https://attacker.test")).status).toBe(403);
  expect((await request({ ...body, price: 1 })).status).toBe(400);
  expect((await request({ ...body, plan: "free" })).status).toBe(400);
  const response = await request(body);
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({
    status: "completed",
    url: "https://www.creem.io/owner/checkout/pro",
  });
  expect(response.headers.get("cache-control")).toBe("no-store");
});
