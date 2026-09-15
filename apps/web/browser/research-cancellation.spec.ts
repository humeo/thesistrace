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

test("rejected batch cancellation explains the restriction and keeps live research visible", async ({ page }) => {
  let completedSessions = 1;
  await page.route("**/api/research-runs/run_cancel", route => route.fulfill({ json: {
    ...detail, progress: { ...detail.progress, completed_research_sessions: completedSessions },
  } }));
  await page.route("**/api/research-runs/run_cancel/cancel", route => route.fulfill({
    status: 409, json: { detail: "Batch-owned ResearchRun cancellation is controlled by its Research Batch" },
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
