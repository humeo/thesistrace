import { test, expect, sameOriginHeaders } from "./auth-fixture";

test(
  "Creem monthly subscription activates paid limits and preserves rights on downgrade and cancel",
  { tag: "@isolated" },
  async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/billing");
    await expect(page.getByLabel("Current plan")).toContainText("Free");
    const firstUsage = await (
      await page.request.get("/api/billing/usage")
    ).json();
    await page.route("https://test.creem.io/**", (route) =>
      route.fulfill({
        contentType: "text/html",
        body: "<h1>Creem Test Checkout</h1>",
      }),
    );
    await page.getByRole("button", { name: "Choose Pro", exact: true }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Confirm", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Creem Test Checkout" }),
    ).toBeVisible();
    const checkoutId = new URL(page.url()).pathname.split("/").at(-1)!;
    const fake = process.env.THESISTRACE_TEST_RESEND_ORIGIN;
    if (!fake) throw new Error("Isolated provider fixture required");
    const complete = await page.request.post(`${fake}/__test/creem/complete`, {
      data: { checkout_id: checkoutId },
    });
    expect(complete.status()).toBe(200);
    await page.goto((await complete.json()).return_url);
    await expect(page.getByLabel("Current plan")).toContainText("Pro");
    await expect(page.getByLabel("Today's usage")).toContainText("$1.00");
    const paid = await (await page.request.get("/api/billing/usage")).json();
    expect(paid.research).toMatchObject({
      limit: 100,
      actual: firstUsage.research.actual,
      reserved: firstUsage.research.reserved,
    });
    expect(paid.tracking.limit).toBe(10);
    expect(
      await (
        await page.request.get("/api/agent/billing/usage", {
          headers: sameOriginHeaders(),
        })
      ).json(),
    ).toMatchObject({ limit_nanodollars: 1_000_000_000 });
    await page.getByRole("button", { name: "Choose Max", exact: true }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Confirm", exact: true })
      .click();
    await expect
      .poll(async () => {
        await page
          .getByRole("button", { name: "Refresh", exact: true })
          .click();
        return (await (await page.request.get("/api/auth/billing")).json())
          .plan;
      })
      .toBe("max");
    await expect(page.getByLabel("Current plan")).toContainText("Max");
    expect(
      await (await page.request.get("/api/billing/usage")).json(),
    ).toMatchObject({ research: { limit: 500 }, tracking: { limit: 50 } });
    await page.getByRole("button", { name: "Choose Pro", exact: true }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Confirm", exact: true })
      .click();
    await expect(page.getByLabel("Current plan")).toContainText(
      "Renewal plan: Pro",
    );
    await expect(page.getByLabel("Current plan")).toContainText("Max");
    await page
      .getByRole("button", { name: "Cancel renewal", exact: true })
      .click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Confirm", exact: true })
      .click();
    await expect(page.getByLabel("Current plan")).toContainText(
      "Renewal canceled",
    );
    expect(
      await (await page.request.get("/api/billing/usage")).json(),
    ).toMatchObject({ research: { limit: 500 }, tracking: { limit: 50 } });
    await info.attach("billing-summary", {
      body: JSON.stringify(
        await (await page.request.get("/api/auth/billing")).json(),
      ),
      contentType: "application/json",
    });
    await page.screenshot({
      path: info.outputPath("billing-subscription-desktop.png"),
      fullPage: true,
    });
    // Same-origin mutation guard is still active at the public billing boundary.
    const rejected = await page.request.post("/api/auth/billing/checkout", {
      headers: { ...sameOriginHeaders(), origin: "https://untrusted.test" },
      data: { request_id: crypto.randomUUID(), plan: "pro" },
    });
    expect(rejected.status()).toBe(403);
  },
);
