import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { build } from "vite";

const styles = ["../src/styles.css", "../src/research-runs/researchBatches.css"]
  .map(path => readFileSync(new URL(path, import.meta.url), "utf8")).join("\n");
let script: string;
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
  const result = await build({
    configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: {
      write: false, minify: false,
      lib: { entry: fileURLToPath(new URL("./fixtures/research-batches.tsx", import.meta.url)), formats: ["iife"], name: "ResearchBatchesFixture" },
    },
  });
  if ("on" in result) throw new Error("Expected a one-off build");
  const chunk = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output)
    .find(output => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Fixture entry is missing");
  script = chunk.code;
});

async function openBatches(page: Page) {
  await page.route("http://127.0.0.1/research-runs/batches", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.route("**/api/research-batches?**", route => route.fulfill({ json: { items: [batch], next_cursor: null } }));
  await page.goto("http://127.0.0.1/research-runs/batches");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("button", { name: "Cancel batch", exact: true }).click();
}

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
  const confirmation = page.getByRole("dialog", { name: "Cancel batch?" });
  await expect(confirmation.getByRole("button", { name: "Keep batch" })).toBeFocused();
  await expect(confirmation).toContainText("1 unfinished research run will be cancelled. Completed results will remain.");
  await expect(confirmation).toContainText("Completed factor");
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
  await page.setViewportSize({ width: 390, height: 844 });
  let unavailable = true;
  let posts = 0;
  await page.route("**/api/research-batches/batch_running", route => route.fulfill(unavailable
    ? { status: 503, json: { detail: "unavailable" } }
    : { json: { ...batch, status: "succeeded", items: batch.items.map(item => ({ ...item, status: "succeeded" })) } }));
  await page.route("**/api/research-batches/batch_running/cancel", route => { posts += 1; return route.fulfill({ status: 409 }); });
  await openBatches(page);
  const confirmation = page.getByRole("dialog", { name: "Cancel batch?" });
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
    return route.fulfill({ status: 409, json: { detail: "Research Batch state does not allow cancellation" } });
  });
  await openBatches(page);
  const confirmation = page.getByRole("dialog", { name: "Cancel batch?" });
  await confirmation.getByRole("button", { name: "Cancel batch", exact: true }).click();
  await expect(confirmation.getByRole("alert")).toContainText("Batch state changed");
  await expect(confirmation.getByRole("button", { name: "Cancel batch", exact: true })).toBeDisabled();
  await confirmation.getByRole("button", { name: "Reload batch" }).click();
  await expect(confirmation).toContainText("This batch is completed.");
});
