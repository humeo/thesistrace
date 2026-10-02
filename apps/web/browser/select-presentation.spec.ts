import { expect, test } from "./workbench-fixture";

test("Research selects open below their trigger and distinguish pointer and keyboard focus", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.addInitScript(() => localStorage.setItem("quantgrove.interface-language", "zh-CN"));
  await page.goto("/research?new");
  await page.getByRole("button", { name: "因子评估", exact: true }).click();
  const universe = page.getByRole("combobox", { name: "股票池", exact: true });
  await universe.click();
  const list = page.getByRole("listbox");
  const popup = page.locator('[data-slot="select-content"]').filter({ has: list });
  await expect(list.getByRole("option")).toHaveText(["前 300 只", "前 1000 只", "前 2000 只", "前 3000 只"]);
  await expect.poll(async () => {
    const triggerBounds = await universe.boundingBox();
    const popupBounds = await popup.boundingBox();
    if (triggerBounds === null || popupBounds === null) return Infinity;
    return Math.max(Math.abs(popupBounds.x - triggerBounds.x), Math.abs(popupBounds.width - triggerBounds.width),
      Math.abs(popupBounds.y - triggerBounds.y - triggerBounds.height - 4));
  }).toBeLessThan(2);

  const background = await popup.evaluate(element => getComputedStyle(element).backgroundColor);
  const top300 = list.getByRole("option", { name: "前 300 只", exact: true });
  const top1000 = list.getByRole("option", { name: "前 1000 只", exact: true });
  await top1000.hover();
  await expect(top1000).not.toHaveCSS("background-color", background);
  await top300.focus();
  await page.keyboard.press("ArrowDown");
  await expect(top1000).toBeFocused();
  await expect(top1000).not.toHaveCSS("background-color", background);
  await page.screenshot({ path: testInfo.outputPath("universe-dropdown.png") });
  await page.keyboard.press("Enter");
  await expect(list).toHaveCount(0);
  await expect(universe).toContainText("前 1000 只");
  await expect(universe).toBeFocused();
  await universe.click();
  await expect(top1000).toHaveAttribute("aria-selected", "true");
  await expect(top1000.locator("svg")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(universe).toBeFocused();
  await expect(universe).toContainText("前 1000 只");

  const neutralization = page.getByRole("combobox", { name: "中性化", exact: true });
  await neutralization.click();
  await expect.poll(async () => {
    const triggerBounds = await neutralization.boundingBox();
    const popupBounds = await popup.boundingBox();
    if (triggerBounds === null || popupBounds === null) return Infinity;
    return Math.abs(popupBounds.y - triggerBounds.y - triggerBounds.height - 4);
  }).toBeLessThan(2);
  await list.getByRole("option", { name: "行业", exact: true }).click();
  await expect(neutralization).toContainText("行业");
  await page.reload();
  await expect(universe).toContainText("前 1000 只");
  await expect(neutralization).toContainText("行业");
});
