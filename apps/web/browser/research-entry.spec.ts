import { expect, test } from "./workbench-fixture";

for (const locale of ["en", "zh-CN"] as const) {
  test(`Research starts with two entries and retains both drafts when returning (${locale})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.addInitScript(language => localStorage.setItem("quantgrove.interface-language", language), locale);
    const zh = locale === "zh-CN";
    const factorName = zh ? "因子评估" : "Factor Evaluation";
    const strategyName = zh ? "策略回测" : "Strategy Backtest";
    const backName = zh ? "返回类型选择" : "Back to research types";
    const factor = page.getByRole("button", { name: factorName, exact: true });
    const strategy = page.getByRole("button", { name: strategyName, exact: true });
    await page.goto("/research?new");
    await expect(page.getByRole("heading", { name: zh ? "选择研究类型" : "Choose a research type", exact: true })).toBeVisible();
    await expect(factor).toHaveAccessibleDescription(zh ? "检验一个评分公式能否识别未来收益。" : "Test whether a scoring formula can identify future returns.");
    await expect(strategy).toHaveAccessibleDescription(zh ? "配置选股与交易规则，检验历史表现。" : "Configure stock selection and trading rules to evaluate historical performance.");
    await expect(page.locator(".research-workbench, .research-action-dock")).toHaveCount(0);
    await expect(page.getByRole("textbox")).toHaveCount(0);
    const factorBox = (await factor.boundingBox())!;
    const strategyBox = (await strategy.boundingBox())!;
    expect(factorBox.y).toBe(strategyBox.y);
    expect(factorBox.width).toBe(strategyBox.width);
    expect(strategyBox.x).toBeGreaterThan(factorBox.x + factorBox.width);
    await page.screenshot({ path: testInfo.outputPath("research-entry.png") });

    await factor.focus();
    await factor.press("Enter");
    await expect(page.getByRole("heading", { name: zh ? "研究" : "Research", exact: true })).toBeFocused();
    const formula = page.getByRole("textbox", { name: zh ? "Alpha 公式" : "Alpha formula", exact: true });
    const notes = page.getByRole("textbox", { name: zh ? "研究备注（可选）" : "Research notes (optional)", exact: true });
    await formula.fill("rank(close)");
    await notes.fill("Preserve this research idea");
    await page.getByRole("button", { name: backName, exact: true }).click();
    await strategy.focus();
    await strategy.press("Enter");
    await page.getByRole("tab", { name: zh ? "组合构建" : "Portfolio", exact: true }).click();
    const cash = page.getByLabel(zh ? "初始资金（CNY）" : "Initial cash (CNY)", { exact: true });
    await expect(cash).toHaveValue("1000000");
    await cash.fill("250000");
    const holdings = page.getByLabel(zh ? "持仓数量" : "Holdings count", { exact: true });
    await holdings.fill("11");
    await expect(page.getByRole("button", { name: zh ? "运行回测" : "Run backtest", exact: true })).toBeVisible();

    await page.getByRole("button", { name: backName, exact: true }).click();
    await factor.click();
    await expect(formula).toHaveText("rank(close)");
    await expect(notes).toHaveValue("Preserve this research idea");
    await expect(page.getByRole("button", { name: zh ? "运行评估" : "Run evaluation", exact: true })).toBeVisible();
    await expect(page.getByRole("radio", { name: factorName, exact: true })).toHaveCount(0);
    await page.reload();
    await expect(formula).toHaveText("rank(close)");
    await expect(factor).toHaveCount(0);

    await page.getByRole("button", { name: backName, exact: true }).click();
    await strategy.click();
    await expect(holdings).toHaveValue("11");
    await expect(cash).toHaveValue("250000");
    await page.reload();
    await expect(holdings).toHaveValue("11");
    await expect(cash).toHaveValue("250000");
    await expect(strategy).toHaveCount(0);
  });
}

test("choosing an otherwise empty strategy persists the selection for reload", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/research");
  await page.getByRole("button", { name: "Strategy Backtest", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("button", { name: "Run backtest", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Choose a research type", exact: true })).toHaveCount(0);
});
