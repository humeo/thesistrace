import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, expect, it } from "vitest";
import { initializeAuthSchema } from "./schema-initialize.js";
import { researcherPlan } from "./billing-store.js";
import { BillingService } from "./billing.js";
import {
  billingNow,
  billingSettings,
  makeCreemFixture,
} from "../test-fixtures/billing.js";

const connectionString = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (!connectionString) throw new Error("isolated Auth test database required");
const databaseUrl = new URL(connectionString);
if (
  databaseUrl.hostname !== "127.0.0.1" ||
  databaseUrl.username !== "thesistrace_owner" ||
  databaseUrl.password !== "owner-test-password"
)
  throw new Error("isolated Auth test database required");
const pool = new Pool({ connectionString });
const id = "b50a37be-7865-4c6a-bd8f-e48dc08f82af";
beforeAll(async () => {
  await pool.query("DROP SCHEMA IF EXISTS auth CASCADE");
  await initializeAuthSchema(pool);
  await pool.query(
    `INSERT INTO auth."user" (id,name,email,"emailVerified",active)
    VALUES ($1,'Billing Researcher','billing@fixture.test',true,true)`,
    [id],
  );
});
beforeEach(async () => {
  await pool.query(
    "TRUNCATE auth.billing_event,auth.billing_command,auth.billing_account,auth.billing_payment,auth.billing_adjustment",
  );
});

it("creates one hosted checkout and grants a plan only after verified payment evidence", async () => {
  await pool.query("DELETE FROM auth.billing_payment WHERE researcher_id=$1", [
    id,
  ]);
  const fixture = makeCreemFixture();
  const service = new BillingService({
    pool,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => billingNow,
  });
  const input = {
    request_id: "64cd74b7-6657-4f6a-83e2-a22984accf15",
    plan: "pro" as const,
  };
  const principal = { id, email: "billing@fixture.test" };
  const first = await service.command(principal, "checkout", input);
  expect(first).toEqual({
    status: "completed",
    url: "https://www.creem.io/test/payment/owned",
  });
  expect(await service.command(principal, "checkout", input)).toEqual(first);
  expect(
    fixture.requests.filter(
      (r) => r.method === "POST" && r.path === "/v1/checkouts",
    ),
  ).toHaveLength(1);
  expect((await service.summary(id)).plan).toBe("free");
  const completed = fixture.checkoutCompleted();
  await service.receiveWebhook(completed.raw, completed.headers);
  expect((await service.summary(id)).plan).toBe("free");
  const paid = fixture.event(
    "evt_paid",
    "subscription.paid",
    fixture.subscription,
  );
  await expect(
    service.receiveWebhook(
      paid.raw,
      new Headers({ "creem-signature": "invalid" }),
    ),
  ).rejects.toThrow();
  expect((await service.summary(id)).plan).toBe("free");
  await service.receiveWebhook(paid.raw, paid.headers);
  await service.receiveWebhook(paid.raw, paid.headers);
  expect((await service.summary(id)).plan).toBe("pro");
  expect(
    (
      await pool.query(
        "SELECT count(*)::int AS n FROM auth.billing_payment WHERE researcher_id=$1",
        [id],
      )
    ).rows,
  ).toEqual([{ n: 1 }]);
});
afterAll(async () => {
  await pool.end();
});

it("activates a verified zero-value paid period and preserves cancellation, expiry and refund semantics", async () => {
  const fixture = makeCreemFixture();
  fixture.transaction.amount = 0;
  fixture.transaction.amount_paid = 0;
  let now = billingNow;
  const service = new BillingService({ pool, settings: billingSettings, publicOrigin: "http://auth.test", client: fixture.client, clock: () => now });
  await service.command({ id, email: "billing@fixture.test" }, "checkout", { request_id: randomUUID(), plan: "pro" });
  const completed = fixture.checkoutCompleted();
  await service.receiveWebhook(completed.raw, completed.headers);
  expect((await service.summary(id)).plan).toBe("free");
  const paid = fixture.event("evt_zero_paid", "subscription.paid", fixture.subscription);
  await service.receiveWebhook(paid.raw, paid.headers);
  await service.receiveWebhook(paid.raw, paid.headers);
  expect((await service.summary(id)).plan).toBe("pro");
  fixture.transaction.status = "chargedBack";
  const dispute = fixture.event("evt_zero_disputed", "subscription.paid", fixture.subscription);
  await service.receiveWebhook(dispute.raw, dispute.headers);
  expect((await service.summary(id)).plan).toBe("free");
  fixture.transaction.status = "paid";
  await service.resolveDispute(fixture.transaction.id, "merchant-review:zero-period");
  expect((await service.summary(id)).plan).toBe("pro");
  await service.command({ id, email: "billing@fixture.test" }, "cancel", { request_id: randomUUID() });
  expect(await service.summary(id)).toMatchObject({ plan: "pro", subscription_status: "scheduled_cancel" });
  now = new Date("2026-11-01Z");
  expect((await service.summary(id)).plan).toBe("free");
  now = billingNow;
  fixture.transaction.status = "refunded";
  const refunded = fixture.event("evt_zero_refunded", "subscription.paid", fixture.subscription);
  await service.receiveWebhook(refunded.raw, refunded.headers);
  expect((await service.summary(id)).plan).toBe("free");
  fixture.transaction.status = "paid";
  const stalePaid = fixture.event("evt_zero_stale_paid", "subscription.paid", fixture.subscription);
  await service.receiveWebhook(stalePaid.raw, stalePaid.headers);
  expect((await service.summary(id)).plan).toBe("free");
});

it.each([{ amount: 0, status: "pending" }, { amount: -1, status: "paid" }])("never grants an invalid zero-value period: %j", async ({ amount, status }) => {
  const fixture = makeCreemFixture();
  fixture.transaction.amount = amount;
  fixture.transaction.amount_paid = amount;
  fixture.transaction.status = status;
  const service = new BillingService({ pool, settings: billingSettings, publicOrigin: "http://auth.test", client: fixture.client, clock: () => billingNow });
  await service.command({ id, email: "billing@fixture.test" }, "checkout", { request_id: randomUUID(), plan: "pro" });
  const completed = fixture.checkoutCompleted();
  await service.receiveWebhook(completed.raw, completed.headers);
  const paid = fixture.event("evt_invalid_zero_paid", "subscription.paid", fixture.subscription);
  await expect(service.receiveWebhook(paid.raw, paid.headers)).rejects.toThrow();
  expect((await service.summary(id)).plan).toBe("free");
});

it("resolves Free until a currently paid transaction supports a higher entitlement", async () => {
  const now = new Date("2026-10-17T12:00:00Z");
  expect(await researcherPlan(pool, id, now)).toBe("free");
  await pool.query(
    `INSERT INTO auth.billing_payment
    (transaction_id,researcher_id,subscription_id,plan_key,starts_at,ends_at,amount)
    VALUES ('txn_current',$1,'sub_owned','pro','2026-10-01Z','2026-11-01Z',2000)`,
    [id],
  );
  expect(await researcherPlan(pool, id, now)).toBe("pro");
  expect(await researcherPlan(pool, id, new Date("2026-11-01T00:00:00Z"))).toBe(
    "free",
  );
});

it("requires the upgrade payment, keeps paid Max rights through a downgrade and cancels only renewal", async () => {
  const fixture = makeCreemFixture();
  let now = billingNow;
  const service = new BillingService({
    pool,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => now,
  });
  const principal = { id, email: "billing@fixture.test" };
  await service.command(principal, "checkout", {
    request_id: "6ae851a9-90eb-4057-bd11-1e75e4590220",
    plan: "pro",
  });
  const completed = fixture.checkoutCompleted();
  await service.receiveWebhook(completed.raw, completed.headers);
  const paid = fixture.event(
    "evt_pro",
    "subscription.paid",
    fixture.subscription,
  );
  await service.receiveWebhook(paid.raw, paid.headers);
  expect(
    await service.command(principal, "change", {
      request_id: "6ae851a9-90eb-4057-bd11-1e75e4590221",
      plan: "max",
    }),
  ).toEqual({ status: "processing" });
  expect(await service.summary(id)).toMatchObject({
    plan: "pro",
    pending_operation: true,
  });
  expect(fixture.requests.at(-1)?.body).toMatchObject({
    product_id: "prod_max",
    update_behavior: "proration-charge-immediately",
  });
  fixture.transaction.id = "txn_upgrade";
  fixture.transaction.amount = 8000;
  fixture.transaction.amount_paid = 8000;
  fixture.subscription.last_transaction_id = "txn_upgrade";
  const upgrade = fixture.event(
    "evt_max",
    "subscription.paid",
    fixture.subscription,
  );
  await service.receiveWebhook(upgrade.raw, upgrade.headers);
  expect(await service.summary(id)).toMatchObject({
    plan: "max",
    pending_operation: false,
  });
  await service.command(principal, "change", {
    request_id: "6ae851a9-90eb-4057-bd11-1e75e4590222",
    plan: "pro",
  });
  expect(fixture.requests.at(-1)?.body).toMatchObject({
    product_id: "prod_pro",
    update_behavior: "proration-none",
  });
  expect(await service.summary(id)).toMatchObject({
    plan: "max",
    renewal_plan: "pro",
    paid_until: "2026-11-01T00:00:00.000Z",
  });
  await service.command(principal, "cancel", {
    request_id: "6ae851a9-90eb-4057-bd11-1e75e4590223",
  });
  expect(await service.summary(id)).toMatchObject({
    plan: "max",
    subscription_status: "scheduled_cancel",
  });
  now = new Date("2026-11-01T00:00:00Z");
  expect((await service.summary(id)).plan).toBe("free");
});

it("reconciles an ambiguous plan change without sending a second charge request", async () => {
  const fixture = makeCreemFixture();
  const service = new BillingService({
    pool,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => billingNow,
  });
  const principal = { id, email: "billing@fixture.test" };
  await service.command(principal, "checkout", {
    request_id: "5d605db6-5eba-4dc4-968c-734a73146470",
    plan: "pro",
  });
  const completed = fixture.checkoutCompleted();
  await service.receiveWebhook(completed.raw, completed.headers);
  const paid = fixture.event(
    "evt_pro",
    "subscription.paid",
    fixture.subscription,
  );
  await service.receiveWebhook(paid.raw, paid.headers);
  const request = {
    request_id: "5d605db6-5eba-4dc4-968c-734a73146471",
    plan: "max" as const,
  };
  fixture.failNextUpgrade();
  expect(await service.command(principal, "change", request)).toEqual({
    status: "processing",
  });
  expect(await service.command(principal, "change", request)).toEqual({
    status: "processing",
  });
  expect(
    fixture.requests.filter((r) => r.path.endsWith("/upgrade")),
  ).toHaveLength(1);
  await service.reconcile();
  expect((await service.summary(id)).plan).toBe("pro");
  expect(
    await service.command(principal, "cancel", {
      request_id: "5d605db6-5eba-4dc4-968c-734a73146472",
    }),
  ).toEqual({ status: "completed" });
  expect(
    fixture.requests.filter((r) => r.path.endsWith("/upgrade")),
  ).toHaveLength(1);
});

it("allows cancellation to retry when preflight fails before any mutation", async () => {
  const fixture = makeCreemFixture();
  const service = new BillingService({
    pool,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => billingNow,
  });
  const principal = { id, email: "billing@fixture.test" };
  await service.command(principal, "checkout", {
    request_id: "924f19f6-f097-46d3-abf8-f2718e1b14e1",
    plan: "pro",
  });
  const completed = fixture.checkoutCompleted();
  await service.receiveWebhook(completed.raw, completed.headers);
  fixture.failNextSubscriptionRead();
  const input = { request_id: "924f19f6-f097-46d3-abf8-f2718e1b14e2" };
  await expect(service.command(principal, "cancel", input)).rejects.toThrow();
  expect(await service.command(principal, "cancel", input)).toEqual({
    status: "completed",
  });
  expect(
    fixture.requests.filter((r) => r.path.endsWith("/cancel")),
  ).toHaveLength(1);
});

it("restores only a manually verified resolved dispute and ignores its delayed event", async () => {
  const fixture = makeCreemFixture();
  let now = billingNow;
  const service = new BillingService({
    pool,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => now,
  });
  await service.command({ id, email: "billing@fixture.test" }, "checkout", {
    request_id: "a51186bf-f892-4075-bfac-e994107bc07e",
    plan: "pro",
  });
  const completed = fixture.checkoutCompleted();
  await service.receiveWebhook(completed.raw, completed.headers);
  const paid = fixture.event(
    "evt_paid",
    "subscription.paid",
    fixture.subscription,
  );
  await service.receiveWebhook(paid.raw, paid.headers);
  const dispute = fixture.event("evt_dispute", "dispute.created", {
    id: "disp_owned",
    object: "dispute",
    mode: "test",
    amount: 2000,
    currency: "USD",
    transaction: fixture.transaction,
    created_at: billingNow.getTime(),
  });
  await service.receiveWebhook(dispute.raw, dispute.headers);
  expect(await service.summary(id)).toMatchObject({
    plan: "free",
    pending_operation: false,
  });
  now = new Date(billingNow.getTime() + 60000);
  await service.resolveDispute("txn_paid", "merchant-reviewed-123");
  expect((await service.summary(id)).plan).toBe("pro");
  const delayed = fixture.event(
    "evt_delayed_dispute",
    "dispute.created",
    JSON.parse(dispute.raw).object,
  );
  await service.receiveWebhook(delayed.raw, delayed.headers);
  expect((await service.summary(id)).plan).toBe("pro");
  fixture.transaction.status = "chargedBack";
  await expect(
    service.resolveDispute("txn_paid", "not-yet-valid"),
  ).rejects.toThrow();
});

it("replays payment before account binding and confirms pending refunds by reconciliation", async () => {
  const fixture = makeCreemFixture();
  const service = new BillingService({
    pool,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => billingNow,
  });
  await service.command({ id, email: "billing@fixture.test" }, "checkout", {
    request_id: "75cb8168-e957-40fc-a3b8-dc043aa81dc7",
    plan: "pro",
  });
  const paid = fixture.event(
    "evt_out_of_order_paid",
    "subscription.paid",
    fixture.subscription,
  );
  await expect(service.receiveWebhook(paid.raw, paid.headers)).rejects.toThrow(
    "BILLING_OWNER_PENDING",
  );
  const completed = fixture.checkoutCompleted();
  await service.receiveWebhook(completed.raw, completed.headers);
  await service.reconcile();
  expect((await service.summary(id)).plan).toBe("pro");
  const refund = fixture.event("evt_pending_refund", "refund.created", {
    id: "ref_owned",
    mode: "test",
    object: "refund",
    status: "pending",
    refund_amount: 2000,
    refund_currency: "USD",
    reason: "requested_by_customer",
    transaction: fixture.transaction,
    created_at: billingNow.getTime(),
  });
  await service.receiveWebhook(refund.raw, refund.headers);
  expect((await service.summary(id)).plan).toBe("pro");
  fixture.transaction.status = "partialRefund";
  fixture.transaction.refunded_amount = 500;
  await service.reconcile();
  expect((await service.summary(id)).plan).toBe("pro");
  fixture.transaction.status = "refunded";
  fixture.transaction.refunded_amount = 2000;
  await service.reconcile();
  await service.reconcile();
  expect((await service.summary(id)).plan).toBe("free");
  expect(await service.summary(id)).toMatchObject({
    subscription_status: "active",
    pending_operation: false,
  });
  await expect(
    service.command({ id, email: "billing@fixture.test" }, "change", {
      request_id: randomUUID(),
      plan: "pro",
    }),
  ).rejects.toThrow("BILLING_PAYMENT_REQUIRED");
  // A refund never cancels renewal or deletes independent valid entitlements.
  await pool.query(
    "INSERT INTO auth.billing_payment(transaction_id,researcher_id,subscription_id,plan_key,starts_at,ends_at,amount) VALUES('txn_separate',$1,'sub_previous','max','2026-10-01Z','2026-11-01Z',10000)",
    [id],
  );
  await service.receiveWebhook(refund.raw, refund.headers);
  expect((await service.summary(id)).plan).toBe("max");
});

it("retains an uncertain mutation until merchant review confirms no effect", async () => {
  const fixture = makeCreemFixture();
  const service = new BillingService({
    pool,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => billingNow,
  });
  const principal = { id, email: "billing@fixture.test" };
  const input = {
    request_id: "5707fb1e-ff60-4dfe-9926-68d7068d8cab",
    plan: "pro" as const,
  };
  fixture.failNextCheckout();
  expect(await service.command(principal, "checkout", input)).toEqual({
    status: "processing",
  });
  await expect(
    service.rejectUnappliedCommand(input.request_id, ""),
  ).rejects.toThrow();
  await service.rejectUnappliedCommand(
    input.request_id,
    "merchant-reviewed-no-checkout-123",
  );
  expect(await service.command(principal, "checkout", input)).toMatchObject({
    status: "failed",
  });
  expect(
    await service.command(principal, "checkout", {
      ...input,
      request_id: "5707fb1e-ff60-4dfe-9926-68d7068d8cac",
    }),
  ).toMatchObject({ status: "completed" });
});

it("records failed event attempts without exhausting a one-connection pool", async () => {
  const limited = new Pool({
    connectionString,
    max: 1,
    connectionTimeoutMillis: 200,
  });
  const fixture = makeCreemFixture();
  const service = new BillingService({
    pool: limited,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => billingNow,
  });
  try {
    const outcomes = await Promise.allSettled(
      [1, 2].map(async (n) => {
        const event = fixture.event(
          `evt_unbound_${n}`,
          "subscription.update",
          fixture.subscription,
        );
        await service.receiveWebhook(event.raw, event.headers);
      }),
    );
    expect(outcomes.every((result) => result.status === "rejected")).toBe(true);
    expect(
      (
        await limited.query(
          "SELECT attempts FROM auth.billing_event ORDER BY id",
        )
      ).rows,
    ).toEqual([{ attempts: 1 }, { attempts: 1 }]);
  } finally {
    await limited.end();
  }
});
it("gives later uncertain commands a reconciliation turn despite ten unresolved checkouts", async () => {
  const fixture = makeCreemFixture();
  const service = new BillingService({
    pool,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => billingNow,
  });
  const commands: string[] = [];
  for (let n = 1; n <= 11; n++) {
    const researcher = randomUUID(),
      command = randomUUID();
    commands.push(command);
    await pool.query(
      `INSERT INTO auth."user"(id,name,email,"emailVerified",active) VALUES($1,'Review',$2,true,true)`,
      [researcher, `${researcher}@fixture.test`],
    );
    await pool.query(
      "INSERT INTO auth.billing_account(researcher_id,customer_id,subscription_id) VALUES($1,$2,$3)",
      [
        researcher,
        n === 11 ? "cust_owned" : null,
        n === 11 ? "sub_owned" : null,
      ],
    );
    await pool.query(
      "INSERT INTO auth.billing_command(id,researcher_id,kind,plan_key,status,updated_at) VALUES($1,$2,$3,$5,'uncertain',$4)",
      [
        command,
        researcher,
        n === 11 ? "cancel" : "checkout",
        new Date(Date.UTC(2020, 0, n)),
        n === 11 ? null : "pro",
      ],
    );
  }
  fixture.subscription.status = "scheduled_cancel";
  await service.reconcile();
  await service.reconcile();
  expect(
    (
      await pool.query(
        "SELECT status,result FROM auth.billing_command WHERE id=$1",
        [commands[10]],
      )
    ).rows,
  ).toEqual([{ status: "completed", result: { status: "completed" } }]);
});

it("ends an unpaid upgrade when its subscription is finally canceled and permits a new checkout", async () => {
  const fixture = makeCreemFixture();
  let now = billingNow;
  const service = new BillingService({
    pool,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => now,
  });
  const principal = { id, email: "billing@fixture.test" };
  await service.command(principal, "checkout", {
    request_id: randomUUID(),
    plan: "pro",
  });
  const completed = fixture.checkoutCompleted();
  await service.receiveWebhook(completed.raw, completed.headers);
  const paid = fixture.event(
    "evt_initial_paid",
    "subscription.paid",
    fixture.subscription,
  );
  await service.receiveWebhook(paid.raw, paid.headers);
  await service.command(principal, "change", {
    request_id: randomUUID(),
    plan: "max",
  });
  expect(await service.summary(id)).toMatchObject({
    plan: "pro",
    pending_operation: true,
  });
  await service.command(principal, "cancel", { request_id: randomUUID() });
  fixture.subscription.status = "canceled";
  now = new Date("2026-11-02T00:00:00Z");
  await service.reconcile();
  expect(await service.summary(id)).toMatchObject({
    plan: "free",
    pending_operation: false,
    subscription_status: "canceled",
  });
  expect(
    await service.command(principal, "checkout", {
      request_id: randomUUID(),
      plan: "pro",
    }),
  ).toMatchObject({ status: "completed", url: expect.any(String) });
});

it("requires the renewal product as evidence for an uncertain downgrade", async () => {
  const fixture = makeCreemFixture();
  fixture.subscription.product = fixture.products.max;
  const service = new BillingService({
    pool,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => billingNow,
  });
  await pool.query(
    "INSERT INTO auth.billing_account(researcher_id,customer_id,subscription_id,provider_status,renewal_plan) VALUES($1,'cust_owned','sub_owned','active','max')",
    [id],
  );
  await pool.query(
    "INSERT INTO auth.billing_payment(transaction_id,researcher_id,subscription_id,plan_key,starts_at,ends_at,amount) VALUES('txn_max',$1,'sub_owned','max','2026-10-01Z','2026-11-01Z',10000)",
    [id],
  );
  const request_id = randomUUID();
  fixture.failNextUpgrade();
  await service.command({ id, email: "billing@fixture.test" }, "change", {
    request_id,
    plan: "pro",
  });
  // A lost response alone cannot establish that the requested product was set.
  fixture.subscription.product = fixture.products.max;
  await service.reconcile();
  expect(await service.summary(id)).toMatchObject({
    plan: "max",
    renewal_plan: "max",
    pending_operation: true,
  });
  await service.rejectUnappliedCommand(request_id, "merchant-no-effect-124");
  expect(await service.summary(id)).toMatchObject({
    plan: "max",
    pending_operation: false,
  });
});

it("keeps provider reads outside database transactions across payment lifecycle processing", async () => {
  const applicationName = "billing-provider-transaction-boundary";
  const isolated = new Pool({
    connectionString,
    application_name: applicationName,
    max: 1,
  });
  const observedTransactions: Array<Date | null> = [];
  const fixture = makeCreemFixture({
    beforeRequest: async (request) => {
      if (request.method !== "GET") return;
      const activity = await pool.query<{ xact_start: Date | null }>(
        "SELECT xact_start FROM pg_stat_activity WHERE application_name=$1",
        [applicationName],
      );
      expect(activity.rows).toHaveLength(1);
      observedTransactions.push(activity.rows[0]!.xact_start);
    },
  });
  const service = new BillingService({
    pool: isolated,
    settings: billingSettings,
    publicOrigin: "http://auth.test",
    client: fixture.client,
    clock: () => billingNow,
  });
  try {
    await service.command({ id, email: "billing@fixture.test" }, "checkout", {
      request_id: randomUUID(),
      plan: "pro",
    });
    const completed = fixture.checkoutCompleted();
    await service.receiveWebhook(completed.raw, completed.headers);
    const paid = fixture.event(
      "evt_transaction_boundary_paid",
      "subscription.paid",
      fixture.subscription,
    );
    await service.receiveWebhook(paid.raw, paid.headers);
    await service.reconcile();
    fixture.transaction.status = "chargedBack";
    const dispute = fixture.event(
      "evt_transaction_boundary_dispute",
      "dispute.created",
      {
        id: "dsp_boundary",
        mode: "test",
        object: "dispute",
        transaction: fixture.transaction,
        amount: 2000,
        currency: "USD",
        created_at: billingNow.getTime(),
      },
    );
    await service.receiveWebhook(dispute.raw, dispute.headers);
    fixture.transaction.status = "paid";
    await service.resolveDispute(
      fixture.transaction.id,
      "merchant-reviewed-boundary",
    );
    const pendingRequest = randomUUID();
    fixture.failNextUpgrade();
    expect(
      await service.command({ id, email: "billing@fixture.test" }, "change", {
        request_id: pendingRequest,
        plan: "max",
      }),
    ).toEqual({ status: "processing" });
    fixture.subscription.product = fixture.products.pro;
    await service.reconcile();
    await service.rejectUnappliedCommand(
      pendingRequest,
      "merchant-reviewed-not-applied",
    );
    expect((await service.summary(id)).plan).toBe("pro");
    expect(observedTransactions.length).toBeGreaterThan(0);
    expect(
      observedTransactions.every((transaction) => transaction === null),
    ).toBe(true);
  } finally {
    await isolated.end();
  }
});
