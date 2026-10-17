import { expect, test, type Page } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";
let script: string;
let styles: string;
const batch = {
  id: "batch_running", batch_kind: "factor_evaluation", status: "running", created_at: "2026-09-15T00:00:00Z",
  scope: { start_date: "2026-08-04", end_date: "2026-08-05", universe: "top300", neutralization: "none" },
  progress: { completed_factor_tasks: 1, total_factor_tasks: 2 }, live_progress: null,
  items: [
    { ordinal: 1, item_key: "Completed factor", research_run_id: "run_complete", status: "succeeded", run_availability: "available" },
    { ordinal: 2, item_key: "Running factor", research_run_id: "run_running", status: "running", run_availability: "available" },
  ],
};

test.beforeAll(async () => {
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/research-batches.tsx", import.meta.url), "ResearchBatchesFixture"));
});

test("desktop independent strategy batch shows per-item settings and refreshes results", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  let detail = {
    ...batch, id: "batch_independent", batch_kind: "independent_strategies",
    scope: { ...batch.scope, neutralization: null },
    progress: { completed_strategy_tasks: 1, total_strategy_tasks: 2 },
    items: [
      { ...batch.items[0]!, item_key: "Formula momentum" },
      { ...batch.items[1]!, item_key: "Python reversal" },
    ],
  };
  await page.route("http://127.0.0.1/research-runs/batches", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.route("**/api/research-batches?**", route => route.fulfill({ json: { items: [detail], next_cursor: null } }));
  await page.route("**/api/research-batches/batch_independent", route => route.fulfill({ json: detail }));
  await page.goto("http://127.0.0.1/research-runs/batches");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("link").filter({ hasText: "Independent strategies" }).click();
  await expect(page.getByRole("heading", { name: "Independent strategies" })).toBeVisible();
  await expect(page.getByText("Defined per research item")).toBeVisible();
  await expect(page.getByRole("link", { name: "Python reversal" })).toHaveAttribute("href", "/research-runs/run_running");
  await page.getByRole("button", { name: "Cancel batch", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toContainText("1 unfinished research run");
  await page.getByRole("button", { name: "Keep batch" }).click();
  detail = { ...detail, status: "completed_with_failures", progress: { completed_strategy_tasks: 2, total_strategy_tasks: 2 }, items: [detail.items[0]!, { ...detail.items[1]!, status: "failed" }] };
  await page.getByRole("button", { name: "Reload", exact: true }).click();
  await expect(page.getByText("Completed with failures", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel batch", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("heading", { name: "独立策略批次" })).toBeVisible();
  await expect(page.getByText("按研究项设置")).toBeVisible();
});

async function openBatches(page: Page) {
  await page.route("http://127.0.0.1/research-runs/batches", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.route("**/api/research-batches?**", route => route.fulfill({ json: { items: [batch], next_cursor: null } }));
  await page.goto("http://127.0.0.1/research-runs/batches");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("button", { name: "Cancel batch", exact: true }).click();
}

test("desktop batch cancellation preserves the accepted state while revalidation is pending", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  let detail = structuredClone(batch);
  let holdDetail = false;
  let releaseDetail!: () => void;
  const detailReady = new Promise<void>(resolve => { releaseDetail = resolve; });
  let releaseCancel!: () => void;
  const cancelReady = new Promise<void>(resolve => { releaseCancel = resolve; });
  const requests: string[] = [];
  await page.route("**/api/research-batches/batch_running", async route => {
    if (holdDetail) await detailReady;
    await route.fulfill({ json: detail });
  });
  await page.route("**/api/research-batches/batch_running/cancel", async route => {
    requests.push(route.request().postDataJSON().request_id);
    if (requests.length === 1) return route.abort("failed");
    await cancelReady;
    detail = { ...detail, status: "cancelling" };
    await route.fulfill({ json: detail });
  });
  try {
    await openBatches(page);
    await page.route("**/api/research-batches?**", route => route.fulfill({ json: { items: detail.status === "cancelled" ? [] : [detail], next_cursor: null } }));
    const confirmation = page.getByRole("alertdialog", { name: "Cancel batch?" });
    await expect(confirmation.getByRole("button", { name: "Keep batch" })).toBeFocused();
    await expect(confirmation).toContainText("1 unfinished research run will be cancelled. Completed results will remain.");
    await confirmation.getByRole("button", { name: "Cancel batch", exact: true }).click();
    await expect(confirmation.getByRole("alert")).toContainText("cancellation failed");
    holdDetail = true;
    await confirmation.getByRole("button", { name: "Cancel batch", exact: true }).click();
    await expect.poll(() => requests.length).toBe(2);
    await expect(confirmation.getByRole("button", { name: "Keep batch" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(confirmation).toBeVisible();
    releaseCancel();
    await expect(confirmation).toHaveCount(0);
    await expect(page.getByRole("status")).toContainText("Waiting for the running work to stop");
    await expect(page.getByRole("listitem").filter({ hasText: "Completed factor" })).toContainText("Completed");
    expect(requests[0]).toBeTruthy();
    expect(requests[1]).toBe(requests[0]);
    detail = { ...detail, status: "cancelled", items: [detail.items[0]!, { ...detail.items[1]!, status: "cancelled" }] };
    releaseDetail();
    await expect(page.getByRole("status")).toHaveText("Batch cancelled. Completed results are retained.");
    await page.getByRole("link", { name: "Back to Batches", exact: true }).click();
    await expect(page.getByText("No queued or running batches.", { exact: true })).toBeVisible();
  } finally { releaseCancel(); releaseDetail(); }
});

test("desktop batch pages retain their filter and cursor through detail return and reload", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const requests: URLSearchParams[] = [];
  const detail = { ...batch, id: "batch_history", status: "completed_with_failures", items: [
    batch.items[0], { ...batch.items[1], status: "failed", run_availability: "deleted" },
  ] };
  await page.route("http://127.0.0.1/research-runs/batches", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.route("**/api/research-batches?**", route => {
    const params = new URL(route.request().url()).searchParams;
    requests.push(params);
    return route.fulfill({ json: params.get("cursor") === "page2" ? { items: [detail], next_cursor: null } : { items: [batch], next_cursor: "page2" } });
  });
  await page.route("**/api/research-batches/batch_history", route => route.fulfill({ json: detail }));
  await page.goto("http://127.0.0.1/research-runs/batches");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("button", { name: "All batches", exact: true }).click();
  const pages = page.getByRole("navigation", { name: "Batch pages" });
  await pages.getByRole("button", { name: "Next", exact: true }).click();
  await expect(pages).toContainText("Page 2");
  await page.getByRole("link").filter({ hasText: "batch_history" }).click();
  await expect(page.getByRole("link", { name: "Completed factor", exact: true })).toHaveAttribute("href", "/research-runs/run_complete");
  await expect(page.getByText("Running factor (deleted)", { exact: true })).toBeVisible();
  await expect(page.locator('a[href="/research-runs/run_running"]')).toHaveCount(0);
  await page.getByRole("link", { name: "Back to Batches", exact: true }).click();
  await expect(pages).toContainText("Page 2");
  await expect(page.getByRole("button", { name: "All batches", exact: true })).toHaveAttribute("aria-pressed", "true");
  const refreshed = page.waitForResponse(response => response.url().includes("/api/research-batches?") && response.url().includes("cursor=page2"));
  await page.getByRole("button", { name: "Reload", exact: true }).click();
  await refreshed;
  expect(requests.at(-1)?.get("cursor")).toBe("page2");
  expect(requests.at(-1)?.get("active_only")).toBe("false");
  expect(requests.at(-1)?.get("limit")).toBe("20");
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "批次分页" })).toContainText("2");
  await page.getByRole("button", { name: "English", exact: true }).click();
  await page.getByRole("button", { name: "Active", exact: true }).click();
  await expect(pages).toContainText("Page 1");
  await expect.poll(() => requests.at(-1)?.get("active_only")).toBe("true");
  expect(requests.at(-1)?.get("cursor")).toBeNull();
});

test("batch cancellation retries the same request and follows cancelling through to cancelled", async ({ page }) => {
  let detail = structuredClone(batch);
  const requests: string[] = [];
  await page.route("**/api/research-batches/batch_running", route => route.fulfill({ json: detail }));
  await page.route("**/api/research-batches/batch_running/cancel", async route => {
    requests.push(route.request().postDataJSON().request_id);
    if (requests.length === 1) return route.abort("failed");
    detail = { ...detail, status: "cancelling" };
    await route.fulfill({ json: detail });
  });
  await openBatches(page);
  const confirmation = page.getByRole("alertdialog", { name: "Cancel batch?" });
  await expect(confirmation.getByRole("button", { name: "Keep batch" })).toBeFocused();
  await expect(confirmation).toContainText("1 unfinished research run will be cancelled. Completed results will remain.");
  await expect(confirmation).toContainText("Completed factor");
  for (const width of [1050]) {
    await page.setViewportSize({ width, height: 964 });
    await page.getByText("简体中文", { exact: true }).evaluate(element => (element as HTMLButtonElement).click());
    const translated = page.getByRole("alertdialog", { name: "取消此批次？" });
    await expect(translated.getByRole("button", { name: "保留批次" })).toBeFocused();
    await expect(translated).toContainText("将取消 1 个尚未完成的研究运行");
    await expect(translated).toContainText("Completed factor");
    expect(requests).toHaveLength(0);
    expect(await translated.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.getByText("English", { exact: true }).evaluate(element => (element as HTMLButtonElement).click());
  }
  await confirmation.getByRole("button", { name: "Cancel batch", exact: true }).click();
  await expect(confirmation.getByRole("alert")).toContainText("cancellation failed");
  await confirmation.getByRole("button", { name: "Cancel batch", exact: true }).click();
  await expect(confirmation).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText("Waiting for the running work to stop");
  await expect(page.getByRole("button", { name: "Cancelling…", exact: true })).toBeDisabled();
  expect(requests).toHaveLength(2);
  expect(requests[0]).toBeTruthy();
  expect(requests[0]).toBe(requests[1]);
  detail = { ...detail, status: "cancelled", items: [detail.items[0]!, { ...detail.items[1]!, status: "cancelled" }] };
  await expect(page.getByRole("status")).toHaveText("Batch cancelled. Completed results are retained.");
  await expect(page.getByRole("listitem").filter({ hasText: "Completed factor" })).toContainText("Completed");
  await expect(page.getByRole("button", { name: "Cancel batch", exact: true })).toHaveCount(0);
});

test("failed inspection blocks cancellation and reload rejects a batch that already completed", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  let unavailable = true;
  let posts = 0;
  await page.route("**/api/research-batches/batch_running", route => route.fulfill(unavailable
    ? { status: 503, json: { detail: "unavailable" } }
    : { json: { ...batch, status: "succeeded", items: batch.items.map(item => ({ ...item, status: "succeeded" })) } }));
  await page.route("**/api/research-batches/batch_running/cancel", route => { posts += 1; return route.fulfill({ status: 409 }); });
  await openBatches(page);
  const confirmation = page.getByRole("alertdialog", { name: "Cancel batch?" });
  await expect(confirmation.getByRole("alert")).toContainText("Batch unavailable");
  await expect(confirmation.getByRole("button", { name: "Cancel batch", exact: true })).toBeDisabled();
  unavailable = false;
  await confirmation.getByRole("button", { name: "Reload batch" }).click();
  await expect(confirmation).toContainText("This batch is completed.");
  await expect(confirmation.getByRole("button", { name: "Cancel batch", exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.keyboard.press("Escape");
  await expect(confirmation).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancel batch", exact: true })).toBeFocused();
  expect(posts).toBe(0);
});

test("a batch completing between inspection and confirmation requires a fresh status", async ({ page }) => {
  let detail = structuredClone(batch);
  await page.route("**/api/research-batches/batch_running", route => route.fulfill({ json: detail }));
  await page.route("**/api/research-batches/batch_running/cancel", route => {
    detail = { ...detail, status: "succeeded" };
    return route.fulfill({ status: 409, json: { detail: { code: "BATCH_NOT_CANCELLABLE" } } });
  });
  await openBatches(page);
  const confirmation = page.getByRole("alertdialog", { name: "Cancel batch?" });
  await confirmation.getByRole("button", { name: "Cancel batch", exact: true }).click();
  await expect(confirmation.getByRole("alert")).toContainText("Batch state changed");
  await expect(confirmation.getByRole("button", { name: "Cancel batch", exact: true })).toBeDisabled();
  await confirmation.getByRole("button", { name: "Reload batch" }).click();
  await expect(confirmation).toContainText("This batch is completed.");
});

test("server cursor pages and filter survive detail return with deleted children", async ({ page }) => {
  const requests: URLSearchParams[] = [];
  const longKey = "Long strategy 中文 " + "Research".repeat(20);
  const detail = { ...batch, id: "batch_history", status: "completed_with_failures", progress: { completed_factor_tasks: 3, total_factor_tasks: 3 }, items: [
    { ...batch.items[0], item_key: longKey },
    { ...batch.items[1], status: "failed", run_availability: "deleted" },
    { ...batch.items[0], ordinal: 3, research_run_id: "run_short", item_key: "X" },
  ] };
  await page.route("http://127.0.0.1/research-runs/batches", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.route("**/api/research-batches?**", route => {
    const query = new URL(route.request().url()).searchParams;
    requests.push(query);
    return route.fulfill({ json: query.get("cursor") === "page2" ? { items: [detail], next_cursor: null } : { items: [batch], next_cursor: "page2" } });
  });
  await page.route("**/api/research-batches/batch_history", route => route.fulfill({ json: detail }));
  await page.goto("http://127.0.0.1/research-runs/batches");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("button", { name: "All batches", exact: true }).click();
  const pages = page.getByRole("navigation", { name: "Batch pages" });
  await pages.getByRole("button", { name: "Next", exact: true }).click();
  await expect(pages).toContainText("Page 2");
  await page.getByRole("link").filter({ hasText: "batch_history" }).click();
  await expect(page.getByRole("link", { name: longKey, exact: true })).toHaveAttribute("href", "/research-runs/run_complete");
  await expect(page.getByText("Running factor (deleted)", { exact: true })).toBeVisible();
  await expect(page.locator('a[href="/research-runs/run_running"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancel batch", exact: true })).toHaveCount(0);
  for (const width of [1440]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  }
  await page.getByRole("link", { name: "Back to Batches", exact: true }).click();
  await expect(pages).toContainText("Page 2");
  await expect(page.getByRole("button", { name: "All batches", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(requests.at(-1)?.get("cursor")).toBe("page2");
  expect(requests.at(-1)?.get("active_only")).toBe("false");
  expect(requests.at(-1)?.get("limit")).toBe("20");
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "批次分页" })).toContainText("2");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("pending cancellation blocks duplicate confirmation and dismissal until the server accepts", async ({ page }) => {
  let posts = 0;
  let release!: () => void;
  const responseReady = new Promise<void>(resolve => { release = resolve; });
  const detail = { ...batch, progress: { completed_factor_tasks: 0, total_factor_tasks: 20 }, items: Array.from({ length: 20 }, (_, index) => ({ ...batch.items[1], ordinal: index + 1, research_run_id: `run_${index}`, item_key: `Research ${index} 中文 ` + "long".repeat(25) })) };
  await page.route("**/api/research-batches/batch_running", route => route.fulfill({ json: detail }));
  await page.route("**/api/research-batches/batch_running/cancel", async route => {
    posts += 1;
    await responseReady;
    await route.fulfill({ json: { ...detail, status: "cancelling" } });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await openBatches(page);
  const confirmation = page.getByRole("alertdialog", { name: "Cancel batch?" });
  await expect(confirmation).toContainText("20 unfinished");
  expect(await confirmation.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  const confirm = confirmation.getByRole("button", { name: "Cancel batch", exact: true });
  await confirm.evaluate(element => { (element as HTMLButtonElement).click(); (element as HTMLButtonElement).click(); });
  await expect.poll(() => posts).toBe(1);
  await expect(confirmation.getByRole("button", { name: "Keep batch" })).toBeDisabled();
  await expect(confirmation.getByRole("button", { name: "Cancelling…" })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(confirmation).toBeVisible();
  release();
  await expect(confirmation).toHaveCount(0);
  expect(posts).toBe(1);
});
