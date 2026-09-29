import { expect, test, type Page } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";
import { emptyResearchDraft, researchDraftKey } from "../src/research/draft";

let script: string;
let styles: string;
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
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/research-cancellation.tsx", import.meta.url), "ResearchCancellationFixture"));
});

async function openResearch(page: Page, expectFacts = true) {
  await page.route("http://127.0.0.1/", route => route.fulfill({
    contentType: "text/html", body: '<div id="root"></div>',
  }));
  await page.route("**/api/research-folders", route => route.fulfill({ json: {
    items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null,
  } }));
  await page.goto("http://127.0.0.1/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  if (expectFacts) await expect(page.getByRole("group", { name: "Research execution conditions" })).toContainText("Top 1000");
}

const horizon = (value: 1 | 5 | 20) => ({
  horizon: value,
  summary: {
    ic: { mean: value === 1 ? 0.12345 : null, sample_deviation: null, icir: null, positive_fraction: null, valid_session_count: 8 },
    rank_ic: { mean: 0, sample_deviation: null, icir: 1.82, positive_fraction: null, valid_session_count: 9 },
    quantile_returns: { q1: null, q2: null, q3: null, q4: null, q5: null }, top_bottom_return: null,
  },
  coverage: { signal_session_count: 10, ic_valid_session_count: 8, rank_ic_valid_session_count: 9,
    quantile_valid_session_count: 0 },
});

test("completed Factor result preserves metrics, visited views, folders and mobile layout", async ({ page }, testInfo) => {
  const reads: string[] = [];
  await page.route("**/api/research-runs/run_cancel/factor-periods?**", route => {
    reads.push("evidence");
    return route.fulfill({ json: { section: "factor_periods", items: [], next_cursor: null } });
  });
  await page.route("**/api/research-runs/run_cancel/common-input-observations?**", route => {
    reads.push("inputs");
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  await page.route("**/api/research-runs/run_cancel", route => route.fulfill({ json: {
    ...detail, status: "succeeded", progress: { ...detail.progress, phase: "succeeded" },
    result: { factor: { horizons: { "1": horizon(1), "5": horizon(5), "20": horizon(20) } },
      provenance: { schema_version: "research-result-v3", research_kind: "factor_evaluation", research_run_id: detail.id,
        immutable_input_sha256: "a".repeat(64), calculation_contracts: {}, semantic_versions: {} } },
  } }));
  await openResearch(page, false);
  await expect(page.getByRole("heading", { name: "Cancellation regression" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("data-active", "");
  await expect(page.getByRole("group", { name: "1-session Factor" })).toContainText("0.123");
  await expect(page.getByRole("group", { name: "1-session Factor" })).toContainText("0.000");
  await expect(page.getByRole("group", { name: "5-session Factor" })).toContainText("—");
  expect(reads).toEqual([]);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({ path: testInfo.outputPath("factor-overview-1280.png"), fullPage: true });
  await page.setViewportSize({ width: 320, height: 900 });
  await page.screenshot({ path: testInfo.outputPath("factor-overview-320.png"), fullPage: true });
  await page.getByRole("tab", { name: "Factor evidence" }).click();
  await expect(page.getByText("No observations in this selection.")).toBeVisible();
  await page.getByRole("combobox", { name: "Horizon" }).click();
  await page.getByRole("option", { name: "20 sessions" }).click();
  await page.getByRole("tab", { name: "Common inputs" }).click();
  await expect(page.getByText("This research does not use common market inputs.")).toBeVisible();
  await page.getByRole("tab", { name: "Factor evidence" }).click();
  await expect(page.getByRole("combobox", { name: "Horizon" })).toContainText("20 sessions");
  expect(reads).toEqual(["evidence", "evidence", "inputs"]);
  await page.getByRole("tab", { name: "Configuration" }).click();
  await expect(page.getByRole("group", { name: "Research execution conditions" })).toContainText("Top 1000");
  await page.getByRole("combobox", { name: "Folder", exact: true }).click();
  await expect(page.getByRole("option", { name: "Default" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "More actions", exact: true }).click();
  await page.getByRole("menuitem", { name: "Delete Research", exact: true }).click();
  const decision = page.getByRole("alertdialog");
  await expect(decision).toContainText("DailyTracks will remain.");
  await decision.getByRole("button", { name: "Keep Research" }).focus();
  await page.locator('nav[aria-label="Fixture language"] button').nth(1).evaluate(element => (element as HTMLButtonElement).click());
  await expect(decision).toContainText("每日跟踪将保留。");
  await expect(decision.getByRole("button", { name: "保留研究" })).toBeFocused();
  await page.locator('nav[aria-label="Fixture language"] button').nth(0).evaluate(element => (element as HTMLButtonElement).click());
  await page.keyboard.press("Escape");
  await expect(page.getByRole("alertdialog")).not.toBeVisible();
  await expect(page.getByRole("tab", { name: "Configuration" })).toHaveAttribute("data-active", "");
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  await page.screenshot({ path: testInfo.outputPath("factor-result-320.png"), fullPage: true });
});

test("failed Factor run leads with the server reason and keeps its frozen configuration", async ({ page }) => {
  await page.route("**/api/research-runs/run_cancel", route => route.fulfill({ json: {
    ...detail, status: "failed", failure_reason: "WorkerLost",
  } }));
  await openResearch(page);
  const failure = page.getByRole("alert", { name: "Failure" });
  await expect(failure).toContainText("research worker stopped responding");
  const configuration = page.getByRole("group", { name: "Research execution conditions" });
  await expect(configuration).toContainText("rank(-pb)");
  await expect(configuration).toContainText("Top 1000");
  await expect(page.getByRole("button", { name: "More actions" })).toBeVisible();
});

test("reusing a Factor run asks before replacing unsent browser changes", async ({ page }) => {
  const key = researchDraftKey("test", "folder_default");
  const draft = { ...emptyResearchDraft(), formula: "local unsent formula", storageSchema: "research-draft/v7" };
  await page.route("**/api/research-runs/run_cancel", route => route.fulfill({ json: { ...detail, status: "failed" } }));
  await page.route("http://127.0.0.1/research", route => route.fulfill({ contentType: "text/html", body: "<div id=\"root\"></div>" }));
  await openResearch(page);
  await page.evaluate(({ key, draft }) => localStorage.setItem(key, JSON.stringify(draft)), { key, draft });
  await page.getByRole("button", { name: "Create draft" }).click();
  const decision = page.getByRole("alertdialog");
  await expect(decision).toContainText("discard unexecuted browser changes");
  await decision.getByRole("button", { name: "Keep current draft" }).click();
  await expect(decision).not.toBeVisible();
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? "null").formula, key)).toBe("local unsent formula");
  await page.getByRole("button", { name: "Create draft" }).click();
  await page.evaluate(key => {
    const setItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (name, value) {
      if (name === key) {
        Storage.prototype.setItem = setItem;
        throw new DOMException("Storage full", "QuotaExceededError");
      }
      setItem.call(this, name, value);
    };
  }, key);
  await decision.getByRole("button", { name: "Replace draft" }).click();
  await expect(decision).not.toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "could not be copied" })).toBeVisible();
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? "null").formula, key)).toBe("local unsent formula");
  await page.getByRole("button", { name: "Create draft" }).click();
  await decision.getByRole("button", { name: "Replace draft" }).click();
  await expect(page).toHaveURL("http://127.0.0.1/research");
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? "null").formula, key)).toBe("rank(-pb)");
});

test("a missing or forbidden Factor run offers a way back to Research Runs", async ({ page }) => {
  let status = 404;
  await page.route("**/api/research-runs/run_cancel", route => route.fulfill({ status }));
  await page.route("**/api/research-folders", route => route.fulfill({ json: { items: [], next_cursor: null } }));
  await page.route("http://127.0.0.1/", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.goto("http://127.0.0.1/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByRole("alert")).toHaveText("This research is no longer available.");
  await expect(page.getByRole("link", { name: "Back to Research Runs" })).toHaveAttribute("href", "/research-runs");
  status = 403;
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("alert")).toHaveText("You do not have access to this research.");
});

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
  const disclosure = progress.getByRole("button", { name: /Timing details/ });
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
  await expect(page.getByRole("progressbar", { name: "Research execution progress" })).toHaveAttribute("aria-valuenow", "2");
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
