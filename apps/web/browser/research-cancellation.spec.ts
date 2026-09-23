import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { build } from "vite";

const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
let script: string;
const summary = {
  id: "run_cancel", status: "running", name: "Cancellation regression",
  folder_id: "folder_default", created_at: "2026-09-15T00:00:00Z",
  start_date: "2026-08-01", end_date: "2026-08-05",
  formula_summary: "rank(-pb)", research_kind: "factor_evaluation",
};
const detail = {
  ...summary,
  input: {
    formula: "rank(-pb)", hypothesis: null, start_date: "2026-08-01", end_date: "2026-08-05",
    universe: "top1000", neutralization: "industry", research_kind: "factor_evaluation",
  },
  progress: {
    phase: "factor", completed_warmup_sessions: 0, total_warmup_sessions: 0,
    completed_research_sessions: 1, total_research_sessions: 5, committed_chunk_count: 1,
    last_completed_warmup_session: null, last_completed_research_session: "2026-08-01",
    remaining_duration_estimate_seconds: null, duration_is_estimate: true,
  },
};

test.beforeAll(async () => {
  const result = await build({
    configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: {
      write: false, minify: false,
      lib: {
        entry: fileURLToPath(new URL("./fixtures/research-cancellation.tsx", import.meta.url)),
        formats: ["iife"], name: "ResearchCancellationFixture",
      },
    },
  });
  if ("on" in result) throw new Error("Expected a one-off build");
  const chunk = (Array.isArray(result) ? result : [result])
    .flatMap(bundle => bundle.output).find(output => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Fixture entry is missing");
  script = chunk.code;
});

async function openResearch(page: Page) {
  await page.route("http://127.0.0.1/", route => route.fulfill({
    contentType: "text/html", body: '<div id="root"></div>',
  }));
  await page.route("**/api/research-folders", route => route.fulfill({ json: {
    items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null,
  } }));
  await page.goto("http://127.0.0.1/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByRole("group", { name: "Research execution conditions" })).toContainText("Top 1000");
}

test("completed execution keeps timing in a keyboard-accessible disclosure on desktop and mobile", async ({ page }) => {
  await page.route("**/api/research-runs/run_cancel", route => route.fulfill({ json: {
    ...detail,
    status: "succeeded",
    progress: { ...detail.progress, phase: "succeeded", completed_research_sessions: 5 },
    execution_timing: {
      started_at: "2026-09-15T00:00:00Z", finished_at: "2026-09-15T00:02:39Z",
      elapsed_seconds: 159, is_final: true,
    },
  } }));
  await openResearch(page);
  const progress = page.getByRole("region", { name: "ResearchRun progress", exact: true });
  const disclosure = progress.locator("summary");
  await expect(progress).toContainText("Execution complete");
  await expect(progress).toContainText("5 / 5 sessions");
  await expect(progress).toContainText("2m 39s");
  await expect(progress.getByRole("progressbar")).toHaveCount(0);
  for (const width of [1050, 390]) {
    await page.setViewportSize({ width, height: 964 });
    await expect(progress.getByText("Started", { exact: true })).not.toBeVisible();
    await disclosure.focus();
    await disclosure.press("Enter");
    await expect(progress.getByText("2026-09-15 00:00:00 UTC")).toBeVisible();
    await expect(progress.getByText("2026-09-15 00:02:39 UTC")).toBeVisible();
    expect(await progress.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    await disclosure.press("Enter");
    await expect(progress.getByText("Started", { exact: true })).not.toBeVisible();
  }
});

test("rejected batch cancellation explains the restriction and keeps live research visible", async ({ page }) => {
  let completedSessions = 1;
  await page.route("**/api/research-runs/run_cancel", route => route.fulfill({ json: {
    ...detail, progress: { ...detail.progress, completed_research_sessions: completedSessions },
  } }));
  await page.route("**/api/research-runs/run_cancel/cancel", route => route.fulfill({
    status: 409, json: { detail: { code: "BATCH_CANCELLATION_REQUIRED" } },
  }));
  await openResearch(page);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Cancel the research batch");
  await expect(page.getByRole("group", { name: "Research execution conditions" })).toContainText("Top 1000");
  completedSessions = 2;
  await expect(page.getByRole("progressbar", { name: "Research execution progress" })).toHaveAttribute("value", "2");
  await expect(page.getByRole("link", { name: "Back to Research Runs" })).toBeVisible();
});

test("cancellation retry keeps its request identity and preserves the frozen inputs", async ({ page }) => {
  let status = "running";
  const requests: string[] = [];
  await page.route("**/api/research-runs/run_cancel", route => route.fulfill({ json: { ...detail, status } }));
  await page.route("**/api/research-runs/run_cancel/cancel", async route => {
    requests.push(route.request().postDataJSON().request_id);
    if (requests.length === 1) return route.abort("failed");
    status = "cancelled";
    await route.fulfill({ json: { ...summary, status } });
  });
  await openResearch(page);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("cancellation failed");
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("取消研究运行失败");
  await expect(page.getByRole("group", { name: "研究执行条件" })).toContainText("rank(-pb)");
  expect(requests).toHaveLength(1);
  await page.getByRole("button", { name: "English", exact: true }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  const facts = page.getByRole("group", { name: "Research execution conditions" });
  await expect(facts).toContainText("cancelled");
  await expect(facts).toContainText("Top 1000");
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(requests).toHaveLength(2);
  expect(requests[0]).toBeTruthy();
  expect(requests[1]).toBe(requests[0]);
});

test("accepted cancellation keeps its details and polls until execution has stopped", async ({ page }) => {
  let status = "running";
  let holdDetail = false;
  let releaseDetail = () => {};
  const nextDetail = new Promise<void>(resolve => { releaseDetail = resolve; });
  await page.route("**/api/research-runs/run_cancel", async route => {
    if (holdDetail) await nextDetail;
    await route.fulfill({ json: { ...detail, status } });
  });
  await page.route("**/api/research-runs/run_cancel/cancel", async route => {
    status = "cancelling";
    holdDetail = true;
    await route.fulfill({ json: { ...summary, status } });
  });
  await openResearch(page);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  const facts = page.getByRole("group", { name: "Research execution conditions" });
  await expect(facts).toContainText("cancelling");
  await expect(facts).toContainText("Top 1000");
  status = "cancelled";
  releaseDetail();
  await expect(facts).toContainText("cancelled");
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
});


test("a late tracking rejection uses the current language and actual configured limit", async ({ page }) => {
  await page.route("**/api/research-runs/run_cancel", route => route.fulfill({ json: { ...summary, status: "succeeded", research_kind: "strategy_backtest" } }));
  let release = () => {};
  let posts = 0;
  const ready = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/research-runs/run_cancel/daily-tracks", async route => {
    posts += 1;
    await ready;
    await route.fulfill({ status: 409, json: { detail: { code: "ACTIVE_DAILY_TRACK_LIMIT_REACHED", limit: 7 } } });
  });
  await page.route("http://127.0.0.1/", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.route("**/api/research-folders", route => route.fulfill({ json: { items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null } }));
  await page.goto("http://127.0.0.1/");
  await page.addScriptTag({ content: script });
  await page.getByRole("button", { name: "Start Tracking", exact: true }).click();
  await expect(page.getByRole("button", { name: "Starting Tracking…" })).toBeDisabled();
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  release();
  await expect(page.getByRole("alert")).toContainText("上限为 7");
  await page.getByRole("button", { name: "English", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("limit is 7");
  expect(posts).toBe(1);
});
