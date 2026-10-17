import { test, expect, type Page } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";
let script: string, styles: string;
test.beforeAll(async () => {
  test.setTimeout(120_000);
  ({ script, styles } = await buildProductFixture(
    new URL("./fixtures/billing.tsx", import.meta.url),
    "Billing",
  ));
});
const plans = {
  free: {
    monthly_price_usd: 0,
    daily_run_limit: 10,
    active_daily_track_limit: 1,
    daily_model_budget_usd: 1,
  },
  pro: {
    monthly_price_usd: 20,
    daily_run_limit: 100,
    active_daily_track_limit: 10,
    daily_model_budget_usd: 1,
  },
  max: {
    monthly_price_usd: 100,
    daily_run_limit: 500,
    active_daily_track_limit: 50,
    daily_model_budget_usd: 2,
  },
};
async function mount(page: Page, initial: "free" | "pro" | "max" = "free") {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const summary = {
    plan: initial,
    paid_until: initial === "free" ? null : "2026-11-01T00:00:00Z",
    renewal_plan: initial === "free" ? null : initial,
    subscription_status: initial === "free" ? null : "active",
    checkout_available: true,
    pending_checkout_url: null,
    pending_operation: false,
    plans,
  };
  const commands: Array<{ kind: string; body: Record<string, unknown> }> = [];
  await page.route("https://billing.test/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/billing")
      return route.fulfill({
        contentType: "text/html",
        body: '<div id="root"></div>',
      });
    if (path === "/api/auth/billing") return route.fulfill({ json: summary });
    if (path === "/api/billing/usage")
      return route.fulfill({
        json: {
          timezone: "Asia/Shanghai",
          resets_at: "2026-10-18T00:00:00+08:00",
          research: { actual: 9, reserved: 1, remaining: 0, limit: 10 },
          tracking: {
            limit: plans[summary.plan].active_daily_track_limit,
            selected_track_ids: ["track_selected"],
            selection_required: false,
            retained_count: 3,
          },
        },
      });
    if (path === "/api/agent/billing/usage")
      return route.fulfill({
        json: {
          timezone: "Asia/Shanghai",
          resets_at: "2026-10-18T00:00:00+08:00",
          actual_nanodollars: 200000000,
          reserved_nanodollars: 300000000,
          remaining_nanodollars: 500000000,
          limit_nanodollars: 1000000000,
        },
      });
    commands.push({
      kind: path.split("/").at(-1)!,
      body: route.request().postDataJSON(),
    });
    if (path.endsWith("/cancel"))
      summary.subscription_status = "scheduled_cancel";
    if (path.endsWith("/change"))
      summary.renewal_plan = String(commands.at(-1)!.body.plan) as
        | "pro"
        | "max";
    if (path.endsWith("/checkout")) summary.pending_operation = true;
    return route.fulfill({
      json: { status: path.endsWith("/checkout") ? "processing" : "completed" },
    });
  });
  await page.goto("https://billing.test/billing?payment_return=1");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  return { summary, commands };
}
test("return URL alone never grants a plan; verified server rights and separate usage are shown", async ({
  page,
}, info) => {
  const { summary, commands } = await mount(page);
  await expect(
    page.getByRole("heading", { name: "Plan and billing" }),
  ).toBeVisible();
  await expect(page.getByLabel("Current plan")).toContainText("Free");
  await page.getByRole("button", { name: "Choose Pro", exact: true }).click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("being confirmed");
  await expect(page.getByLabel("Current plan")).toContainText("Free");
  expect(commands[0].kind).toBe("checkout");
  expect(commands[0].body).toEqual({
    plan: "pro",
    request_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
  });
  summary.plan = "pro";
  summary.paid_until = "2026-11-01T00:00:00Z";
  summary.renewal_plan = "pro";
  summary.subscription_status = "active";
  summary.pending_operation = false;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByLabel("Current plan")).toContainText("Pro");
  await expect(page.getByLabel("Today's usage")).toContainText("$0.20");
  await expect(page.getByLabel("Today's usage")).toContainText("$0.30");
  await expect(page.getByLabel("Today's usage")).toContainText("$0.50");
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("heading", { name: "套餐与账单" })).toBeVisible();
  await page.screenshot({
    path: info.outputPath("billing-desktop.png"),
    fullPage: true,
  });
});
test("downgrade sets renewal plan and cancellation preserves current paid rights", async ({
  page,
}) => {
  const { commands } = await mount(page, "max");
  await page.getByRole("button", { name: "Choose Pro", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toContainText("no refund");
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm", exact: true })
    .click();
  await expect(page.getByLabel("Current plan")).toContainText("Max");
  await expect(page.getByLabel("Current plan")).toContainText(
    "Renewal plan: Pro",
  );
  await page
    .getByRole("button", { name: "Cancel renewal", exact: true })
    .click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm", exact: true })
    .click();
  await expect(page.getByLabel("Current plan")).toContainText("Max");
  await expect(page.getByLabel("Current plan")).toContainText(
    "Renewal canceled",
  );
  expect(commands.map((item) => item.kind)).toEqual(["change", "cancel"]);
});

test("a refunded plan refresh replaces older usage and does not promise paid rights", async ({
  page,
}) => {
  const { summary } = await mount(page, "max");
  await expect(page.getByLabel("Today's usage")).toContainText("50 slots");
  let releaseBilling!: () => void;
  let releaseUsage!: () => void;
  let startedBilling!: () => void;
  let startedUsage!: () => void;
  const billingGate = new Promise<void>((resolve) => {
    releaseBilling = resolve;
  });
  const usageGate = new Promise<void>((resolve) => {
    releaseUsage = resolve;
  });
  const billingStarted = new Promise<void>((resolve) => {
    startedBilling = resolve;
  });
  const usageStarted = new Promise<void>((resolve) => {
    startedUsage = resolve;
  });
  let heldUsage = false;
  await page.route("https://billing.test/api/billing/usage", async (route) => {
    if (heldUsage) return route.fallback();
    heldUsage = true;
    startedUsage();
    await usageGate;
    await route.fulfill({
      json: {
        timezone: "Asia/Shanghai",
        resets_at: "2026-10-18T00:00:00+08:00",
        research: { actual: 9, reserved: 1, remaining: 490, limit: 500 },
        tracking: {
          limit: 50,
          selected_track_ids: ["track_selected"],
          selection_required: false,
          retained_count: 3,
        },
      },
    });
  });
  await page.route("https://billing.test/api/auth/billing", async (route) => {
    startedBilling();
    await billingGate;
    summary.plan = "free";
    summary.paid_until = null;
    summary.subscription_status = "scheduled_cancel";
    await route.fulfill({ json: summary });
  });
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await Promise.all([billingStarted, usageStarted]);
  releaseBilling();
  await expect(page.getByLabel("Current plan")).toContainText("Free");
  releaseUsage();
  await expect(page.getByLabel("Today's usage")).toContainText("1 slots");
  await expect(page.getByLabel("Today's usage")).not.toContainText("50 slots");
  await expect(page.getByLabel("Current plan")).toContainText(
    "Free limits apply",
  );
  await expect(page.getByLabel("Current plan")).not.toContainText(
    "paid plan remains available",
  );
});

test("canceling renewal after a full refund does not promise paid limits", async ({
  page,
}) => {
  const { summary } = await mount(page);
  await expect(page.getByLabel("Current plan")).toContainText("Free");
  summary.subscription_status = "active";
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page
    .getByRole("button", { name: "Cancel renewal", exact: true })
    .click();
  const confirmation = page.getByRole("alertdialog");
  await expect(confirmation).toContainText("Free limits apply");
  await expect(confirmation).not.toContainText("paid limits remain");
  await confirmation
    .getByRole("button", { name: "Go back", exact: true })
    .click();
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await page.getByRole("button", { name: "取消续费", exact: true }).click();
  await expect(confirmation).toContainText("当前使用 Free 额度");
  await expect(confirmation).not.toContainText("本期已付额度保留");
});
