import { expect, test } from "./workbench-fixture";
import { completedStrategyRun } from "./fixtures/strategy-result";

test.use({ viewport: { width: 1440, height: 960 } });

const runs = [
  { ...completedStrategyRun, created_at: "2026-10-15T10:20:24.987654Z" },
  { ...completedStrategyRun, id: "run_winter", created_at: "2026-01-15T00:20:24Z" },
  { ...completedStrategyRun, id: "run_summer", created_at: "2026-07-15T08:20:24+08:00" },
];

const cases = [
  { timeZone: "Asia/Seoul", en: ["10/15/2026, 19:20:24", "01/15/2026, 09:20:24", "07/15/2026, 09:20:24"], zh: ["2026/10/15 19:20:24", "2026/01/15 09:20:24", "2026/07/15 09:20:24"] },
  { timeZone: "Asia/Shanghai", en: ["10/15/2026, 18:20:24", "01/15/2026, 08:20:24", "07/15/2026, 08:20:24"], zh: ["2026/10/15 18:20:24", "2026/01/15 08:20:24", "2026/07/15 08:20:24"] },
  { timeZone: "UTC", en: ["10/15/2026, 10:20:24", "01/15/2026, 00:20:24", "07/15/2026, 00:20:24"], zh: ["2026/10/15 10:20:24", "2026/01/15 00:20:24", "2026/07/15 00:20:24"] },
  { timeZone: "America/Los_Angeles", en: ["10/15/2026, 03:20:24", "01/14/2026, 16:20:24", "07/14/2026, 17:20:24"], zh: ["2026/10/15 03:20:24", "2026/01/14 16:20:24", "2026/07/14 17:20:24"] },
  { timeZone: "Australia/Darwin", en: ["10/15/2026, 19:50:24", "01/15/2026, 09:50:24", "07/15/2026, 09:50:24"], zh: ["2026/10/15 19:50:24", "2026/01/15 09:50:24", "2026/07/15 09:50:24"] },
];

for (const { timeZone, en, zh } of cases) {
  test.describe(timeZone, () => {
    test.use({ timezoneId: timeZone });

    for (const language of ["en", "zh-CN"]) {
      test(`creation times and the column heading use the browser timezone in ${language}`, async ({ page }, testInfo) => {
        await page.addInitScript(locale => localStorage.setItem("quantgrove.interface-language", locale), language);
        await page.route("**/api/research-runs?*", route => route.fulfill({ json: { items: runs, total_count: runs.length } }));
        await page.goto("/research-runs");

        const heading = language === "en" ? `Created (${timeZone})` : `创建时间（${timeZone}）`;
        await expect(page.getByRole("columnheader", { name: heading })).toBeVisible();
        const created = page.locator("tbody time");
        await expect(created).toHaveText(language === "en" ? en : zh);
        for (const [index, run] of runs.entries()) {
          await expect(created.nth(index)).toHaveAttribute("datetime", run.created_at);
        }
        if (timeZone === "Asia/Shanghai" && language === "zh-CN") {
          await page.screenshot({ path: testInfo.outputPath("browser-local-time.png"), fullPage: true });
        }
      });
    }
  });
}
