import { expect, test } from "./workbench-fixture";

test("workspace initialization starts while Operator capability is still pending", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  let release!: () => void;
  const capabilityAvailable = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/auth/operator/capability", async route => {
    await capabilityAvailable;
    await route.fulfill({ status: 404, body: "" });
  });
  try {
    await Promise.all([
      page.waitForRequest("**/api/researcher/bootstrap", { timeout: 3_000 }),
      page.goto("/data"),
    ]);
    await expect(page.locator(".data-field-table")).toHaveCount(0);
  } finally {
    release();
  }
  await expect(page.locator(".data-field-table")).toBeVisible();
});
