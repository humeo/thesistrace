import { expect, test } from "./workbench-fixture";

test("Research modes keep one focused editor and expose help by hover and keyboard", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/research?new");
  await expect(page.getByRole("textbox", { name: "Alpha formula", exact: true })).toBeVisible();

  await page.getByRole("radio", { name: "Strategy Backtest", exact: true }).check();
  const tabs = page.getByRole("tablist", { name: "Strategy modules" });
  await expect(tabs.getByRole("tab")).toHaveCount(4);
  const portfolio = tabs.getByRole("tab", { name: /Portfolio/ });
  await expect(portfolio).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Holdings count", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Alpha formula", exact: true })).not.toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("rules.png") });

  const help = page.getByRole("button", { name: "About Stock allocation (%)" });
  await help.hover();
  const info = page.getByRole("dialog", { name: "Stock allocation (%)" });
  await expect(info).toContainText("remaining capital stays in cash");
  await help.click();
  await expect(info).toBeVisible();
  await help.press("Escape");
  await expect(info).toHaveCount(0);
  await expect(help).toBeFocused();
  await help.press("Enter");
  await expect(info).toBeVisible();
  await help.press("Escape");
  await expect(info).toHaveCount(0);

  await portfolio.focus();
  await portfolio.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: /Risk/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Risk settings" })).toBeVisible();
  await expect(page.getByLabel("Holdings count", { exact: true })).not.toBeVisible();

  await page.getByRole("radio", { name: "Complete Python strategy", exact: true }).check();
  await expect(page.getByRole("textbox", { name: "Python source", exact: true })).toBeVisible();
  await expect(tabs).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Run backtest", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("python.png") });

  await page.getByRole("radio", { name: "Factor Evaluation", exact: true }).check();
  await expect(page.getByRole("textbox", { name: "Alpha formula", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run evaluation", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("factor.png") });
});

test("Chinese rules layout keeps labels and actions readable", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.addInitScript(() => localStorage.setItem("quantgrove.interface-language", "zh-CN"));
  await page.goto("/research?new");
  await page.getByRole("radio", { name: "策略回测", exact: true }).check();
  await expect(page.getByRole("tab", { name: /组合构建/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("button", { name: "运行回测", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("rules-zh.png") });
});
