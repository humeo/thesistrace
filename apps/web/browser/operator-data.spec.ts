import { expect, test } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";

let fixture: Awaited<ReturnType<typeof buildProductFixture>>;
test.beforeAll(async () => { fixture = await buildProductFixture(new URL("./fixtures/operator-data.tsx", import.meta.url), "OperatorDataFixture"); });
for (const width of [1280, 1440]) {
  test(`Dataset tables, date and Sheet remain readable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("http://operator-data.test/**", route => route.fulfill({ contentType: "text/html; charset=utf-8", body: '<div id="root"></div>' }));
    await page.goto("http://operator-data.test/");
    await page.addStyleTag({ content: fixture.styles });
    await page.addScriptTag({ content: fixture.script });
    const date = page.getByLabel("As-of", { exact: true });
    await expect(date).toHaveValue("2026-08-14");
    await date.fill("2026-08-15");
    await expect(date).toHaveValue("2026-08-15");
    const history = page.getByRole("table", { name: "Data Refresh operation history" });
    await expect(history.getByRole("row")).toHaveCount(2);
    await expect(page.getByText("Financial ready with pending")).toHaveAttribute("data-slot", "badge");
    const identityAlignment = await page.getByText("Data identity", { exact: true }).locator("..").evaluate(element => {
      const term = element.querySelector("dt")!;
      const description = element.querySelector("dd")!;
      return Math.abs(term.getBoundingClientRect().left - description.getBoundingClientRect().left);
    });
    expect(identityAlignment).toBeLessThan(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (width < 1280) {
      const region = page.getByRole("region", { name: "Data Refresh operation history" });
      expect(await region.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
    }
    const details = history.getByRole("button", { name: /View details for market-/ });
    await details.click();
    const sheet = page.getByRole("dialog", { name: "Operation details" });
    await expect(sheet.getByRole("button", { name: "Close operation details" })).toBeFocused();
    await expect(sheet).toContainText("Not published");
    await expect(sheet).toContainText("market-");
    await page.keyboard.press("Control+Shift+L");
    await expect(page.getByRole("dialog", { name: "操作详情" })).toBeVisible();
    await page.keyboard.press("Control+Shift+L");
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(details).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("calendar, loading/error feedback and confirmation survive a language switch", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.route("http://operator-data.test/**", route => route.fulfill({ contentType: "text/html; charset=utf-8", body: '<div id="root"></div>' }));
  await page.goto("http://operator-data.test/");
  await page.addStyleTag({ content: fixture.styles });
  await page.addScriptTag({ content: fixture.script });

  await page.getByRole("button", { name: "Open As-of calendar" }).click();
  const calendar = page.getByRole("grid");
  await expect(calendar).toBeVisible();
  await calendar.getByRole("button", { name: "Saturday, August 15th, 2026" }).click();
  await expect(page.getByRole("textbox", { name: "As-of" })).toHaveValue("2026-08-15");

  await page.getByRole("button", { name: "Toggle loading" }).click();
  await expect(page.getByRole("region", { name: "Current research Dataset" })).toHaveAttribute("aria-busy", "true");
  await page.getByRole("button", { name: "Toggle loading" }).click();
  await expect(page.getByRole("region", { name: "Current research Dataset" })).not.toHaveAttribute("aria-busy", "true");
  await page.getByRole("button", { name: "Toggle error" }).click();
  await expect(page.getByRole("region", { name: "Current research Dataset" }).getByRole("alert")).toBeVisible();

  await page.getByRole("button", { name: "Review market confirmation" }).click();
  const english = page.getByRole("dialog", { name: "Refresh all data?" });
  await expect(english).toContainText("market-fixture-confirmation");
  await page.keyboard.press("Control+Shift+L");
  const chinese = page.getByRole("dialog", { name: "刷新全部数据？" });
  await expect(chinese).toContainText("market-fixture-confirmation");
  await expect(chinese).toContainText("2026-08-14T18:00:00+08:00");
  await page.keyboard.press("Escape");
  await expect(chinese).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Review market confirmation" })).toBeFocused();
});
