import { expect, test } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";

let fixture: Awaited<ReturnType<typeof buildProductFixture>>;
test.beforeAll(async () => { fixture = await buildProductFixture(new URL("./fixtures/operator-financial-industry.tsx", import.meta.url), "OperatorFinancialIndustryFixture"); });

for (const width of [1280, 1440]) {
  test(`Financial and Industry forms, receipts and progress fit ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("http://127.0.0.1:19876/**", route => route.fulfill({ contentType: "text/html; charset=utf-8", body: '<div id="root"></div>' }));
    await page.goto("http://127.0.0.1:19876/");
    await page.addStyleTag({ content: fixture.styles });
    await page.addScriptTag({ content: fixture.script });
    await expect(page.getByRole("heading", { name: "Financial Refresh", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Industry Refresh", exact: true })).toBeVisible();
    await expect(page.getByText("Unknown", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("0", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("UPSTREAM_UNAVAILABLE")).toBeVisible();
    await expect(page.getByText("Indicator coverage could not reach a publishable date. The previous version was retained.")).toBeVisible();

    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("both confirmation targets and keys survive locale changes and Escape restores focus", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.route("http://127.0.0.1:19876/**", route => route.fulfill({ contentType: "text/html; charset=utf-8", body: '<div id="root"></div>' }));
  await page.goto("http://127.0.0.1:19876/");
  await page.addStyleTag({ content: fixture.styles });
  await page.addScriptTag({ content: fixture.script });
  for (const kind of ["Financial", "Industry"] as const) {
    const section = page.locator(`section[aria-labelledby="operator-${kind.toLowerCase()}-refresh-heading"]`);
    await section.getByRole("textbox", { name: "Observation-through Research Session" }).fill("2026-08-14");
    const trigger = section.getByRole("button", { name: "Review Refresh" });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: `Submit ${kind} Refresh?` });
    await expect(dialog).toBeVisible();
    const key = await dialog.locator("dl dd").last().innerText();
    expect(key).toMatch(new RegExp(`^${kind.toLowerCase()}-\\d{8}T\\d{6}Z-[a-f0-9-]{36}$`));
    await expect(dialog).toContainText("2026-08-14");
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
    await page.keyboard.press("Control+Shift+L");
    const translated = page.getByRole("dialog", { name: kind === "Financial" ? "提交财务数据刷新？" : "提交行业数据刷新？" });
    await expect(translated).toContainText(key);
    await expect(translated).toContainText("2026-08-14");
    await page.keyboard.press("Escape");
    await expect(translated).toHaveCount(0);
    await page.keyboard.press("Control+Shift+L");
    await expect(trigger).toBeFocused();
  }
});
