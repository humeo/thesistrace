import { expect, type Locator, type Page, test } from "@playwright/test";

test.setTimeout(120_000);

const viewport =
  process.env.THESISTRACE_E2E_VIEWPORT === "desktop"
    ? { width: 1440, height: 1000 }
    : { width: 390, height: 844 };

async function inspectResource(page: Page, link: Locator) {
  await expect(link).toBeVisible();
  const [resource] = await Promise.all([
    page.waitForEvent("popup"),
    link.click(),
  ]);
  await resource.waitForLoadState();
  expect(resource.url()).toContain("/api/v1/");
  await expect(resource.locator("body")).not.toBeEmpty();
  await resource.close();
}

test(`completes the ${viewport.width === 390 ? "narrow" : "desktop"} workspace chain`, async ({
  page,
}) => {
  await page.setViewportSize(viewport);
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "研究工作台" })).toBeVisible();
  await expect(page.getByText("尚未发布数据版本")).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Dataset Releases" }).getByText("0", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Research Runs" }).getByText("0", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("API / Metadata")).toBeVisible();
  await expect(page.getByText("Object Store")).toBeVisible();
  await expect(page.getByText("Worker")).toBeVisible();
  await expect(page.getByText("没有伪造示例资源")).toBeVisible();

  await page.getByRole("button", { name: "发布 Live Tushare Bootstrap" }).click();
  await expect(page.getByRole("alert")).toContainText("TOKEN_MISSING");

  await page.getByRole("button", { name: "发布 Fixture Bootstrap" }).click();

  const dataPanel = page.locator("#data");
  await expect(page.getByRole("heading", { name: "Fixture Bootstrap 已发布" })).toBeVisible();
  await expect(dataPanel.getByText("756 sessions")).toBeVisible();
  await expect(dataPanel.getByText("ROOT", { exact: true })).toBeVisible();
  await expect(dataPanel.getByText("11 immutable objects")).toBeVisible();
  await expect(page.getByRole("heading", { name: "标准研究数据契约" })).toBeVisible();
  await expect(page.getByText("open_adj", { exact: true })).toBeVisible();
  await expect(page.getByText("TOP 300 · TOP 1000 · TOP 2000 · TOP 3000")).toBeVisible();
  await expect(page.getByText("SW2021 L1 · L2 · L3")).toBeVisible();
  await expect(page.getByText("FULL SESSION SUSPENSION · 1")).toBeVisible();

  await expect(page.getByRole("heading", { name: "Research Definition" })).toBeVisible();
  const definitionPanel = page.locator("#definitions");
  await page.getByLabel("研究假设").fill("过去 20 日上涨的股票，未来收益更高。");
  await page.getByRole("button", { name: "保存 Draft" }).click();
  await expect(definitionPanel.getByText("DRAFT SAVED")).toBeVisible();
  await page.getByLabel("研究假设").fill("运行时必须冻结当前页面里的最新假设。");
  const updatedDraftRequest = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().includes("/api/v1/research-definitions/"),
  );
  await page.getByRole("button", { name: "运行研究" }).click();
  expect((await updatedDraftRequest).postDataJSON().hypothesis).toBe(
    "运行时必须冻结当前页面里的最新假设。",
  );
  await expect(definitionPanel.getByText("RUN QUEUED")).toBeVisible();
  await expect(page.getByText("FROZEN VERSION 1")).toBeVisible();
  await expect(page.getByRole("button", { name: "Freeze" })).toHaveCount(0);
  await expect(definitionPanel.getByText("SUCCEEDED")).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByRole("heading", { name: "因子结论" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "策略结论" })).toBeVisible();
  await expect(page.getByText("RESULT BUNDLE", { exact: true })).toBeVisible();
  await expect(page.getByText("DATASET RELEASE", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: "1 日因子 Rank IC 日序列" })).toHaveCount(0);
  await expect(page.getByRole("img", { name: "基准 NAV 日序列" })).toBeVisible();
  await expect(page.getByRole("img", { name: "现金比例日序列" })).toBeVisible();
  await expect(page.getByText("RECENT COST EVENTS")).toHaveCount(0);
  await expect(page.getByText("RECENT MARKET REJECTIONS")).toHaveCount(0);
  await expect(page.getByText("AUTHORITATIVE ARTIFACTS")).toHaveCount(0);
  await expect(page.locator(".artifact-links a")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "运行与追踪记录" })).toBeVisible();
  await expect(page.getByText("DATASET RELEASES", { exact: true })).toBeVisible();
  await expect(page.getByText("DEFINITIONS", { exact: true })).toBeVisible();
  await expect(page.getByText("RESEARCH RUNS", { exact: true })).toBeVisible();
  await expect(page.getByText("NOT ACTIVATED")).toBeVisible();
  await page.getByRole("button", { name: "开始每日追踪" }).click();
  await expect(page.getByText("ACTIVE", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "停止追踪" })).toBeVisible();

  await page.getByRole("button", { name: "发布下一 Fixture Session" }).click();
  await expect(page.getByRole("heading", { name: "Dataset Release 已发布" })).toBeVisible();
  await expect(dataPanel.getByText("757 sessions")).toBeVisible();
  await expect(page.getByText(/[1-9]\d* LABEL EVENTS/)).toBeVisible({
    timeout: 60_000,
  });
  await expect(
    page.getByRole("group", { name: "Dataset Releases" }).getByText("2", {
      exact: true,
    }),
  ).toBeVisible();

  await expect(page.getByText(/^Checkpoint checkpoint_/).first()).toBeVisible({
    timeout: 20_000,
  });
  await inspectResource(
    page,
    page.locator('a[href^="/api/v1/dataset-releases/"]').first(),
  );
  await inspectResource(page, page.getByText("查看 Draft").first());
  await inspectResource(page, page.getByText("查看 Frozen Version").first());
  await inspectResource(
    page,
    page.locator('a[href^="/api/v1/research-runs/"]').first(),
  );
  await inspectResource(page, page.locator('a[href$="/result"]').first());
  await inspectResource(page, page.locator('a[href*="/attempts/"]').first());
  await inspectResource(
    page,
    page.locator('a[href^="/api/v1/daily-tracks/"]').first(),
  );
  await inspectResource(page, page.locator('a[href*="/generations/"]').first());
  await inspectResource(page, page.locator('a[href*="/advances/"]').first());
  await inspectResource(page, page.locator('a[href*="/checkpoints/"]').first());

  await page.getByRole("button", { name: "停止追踪" }).click();
  await expect(page.getByText("STOPPED", { exact: true })).toBeVisible();
});
