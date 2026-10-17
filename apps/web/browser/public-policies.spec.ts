import { expect, test } from "./workbench-fixture";

for (const language of ["en", "zh"] as const) {
  test(`public policy pages are accessible without Auth in ${language}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const requests: string[] = [];
    await page.route("**/api/**", async route => {
      requests.push(route.request().url());
      await route.fulfill({ status: 503, body: "Auth unavailable" });
    });
    const titles = language === "en"
      ? ["Terms of service", "Privacy notice", "Refunds and cancellation", "Plans and usage"]
      : ["服务条款", "隐私说明", "退款与取消", "套餐与额度"];
    const paths = ["/terms", "/privacy", "/refunds", "/pricing"];
    for (const [index, path] of paths.entries()) {
      await page.goto(`${path}?lang=${language}`);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(titles[index]);
      await expect(page).toHaveTitle(`${titles[index]} · QAgentis`);
      await expect(page.locator("html")).toHaveAttribute("lang", language === "en" ? "en" : "zh-CN");
      await expect(page.locator(".policy-notice")).toContainText(language === "en" ? "Pre-launch preview" : "上线前预览");
      await expect(page.getByRole("main")).not.toContainText("[支持及隐私联系邮箱]");
      await expect(page.locator('a[aria-current="page"]')).toHaveCount(2);
      await expect(page.getByRole("link", { name: "koltenluca433@gmail.com", exact: true })).toHaveAttribute("href", "mailto:koltenluca433@gmail.com");
    }
    await expect(page.getByRole("table")).toContainText("$20");
    await expect(page.getByRole("table")).toContainText("$100");
    await page.getByRole("button", { name: language === "en" ? "中文" : "English", exact: true }).click();
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(language === "en" ? "套餐与额度" : "Plans and usage");
    expect(requests).toEqual([]);
  });
}

test("homepage exposes public policies and pricing", async ({ page }) => {
  await page.goto("/?lang=en");
  const policies = page.getByRole("navigation", { name: "Policies and pricing" });
  await expect(policies.getByRole("link", { name: "Terms", exact: true })).toHaveAttribute("href", "/terms?lang=en");
  await policies.getByRole("link", { name: "Pricing", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Plans and usage");
});
