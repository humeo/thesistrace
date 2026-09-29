import type { Page } from "@playwright/test";
import { expect, test } from "./workbench-fixture";

function recordDocumentRequests(page: Page): string[] {
  const documentRequests: string[] = [];
  page.on("request", (request) => {
    if (request.resourceType() === "document") documentRequests.push(request.url());
  });
  return documentRequests;
}

test("ResearchRun return keeps the selected Type without a document reload", async ({ page }) => {
  const documentRequests = recordDocumentRequests(page);
  await page.route("**/api/research-folders", async (route) => {
    await route.fulfill({
      json: {
        items: [{
          id: "folder_default",
          name: "Default",
          is_default: true,
          created_at: "2026-08-13T00:00:00Z",
        }],
        next_cursor: null,
      },
    });
  });
  await page.route("**/api/research-runs?*", async (route) => {
    await route.fulfill({
      json: {
        items: [{
          id: "run_feedface1234abcd9876",
          status: "succeeded",
          name: "Filtered Factor",
          folder_id: "folder_default",
          created_at: "2026-08-13T01:02:03Z",
          start_date: "2026-08-01",
          end_date: "2026-08-05",
          formula_summary: "rank(close)",
          research_kind: "factor_evaluation",
        }],
        total_count: 1,
      },
    });
  });
  await page.route("**/api/research-runs/run_feedface1234abcd9876", async (route) => {
    await route.fulfill({
      json: {
        id: "run_feedface1234abcd9876",
        status: "succeeded",
        name: "Filtered Factor",
        folder_id: "folder_default",
        created_at: "2026-08-13T01:02:03Z",
        start_date: "2026-08-01",
        end_date: "2026-08-05",
        formula_summary: "rank(close)",
        research_kind: "factor_evaluation",
      },
    });
  });

  await page.goto("/research-runs");
  await page.getByRole("combobox", { name: "Filter by Type", exact: true }).click();
  await page.getByRole("option", { name: "Factor Evaluation", exact: true }).click();
  await page.getByRole("link", { name: "Filtered Factor", exact: true }).click();
  await expect(page).toHaveURL(/\/research-runs\/run_feedface1234abcd9876$/);
  await expect(page.getByRole("heading", { name: "Filtered Factor", exact: true })).toBeVisible();
  documentRequests.length = 0;

  await page.getByRole("link", { name: "Back to Research Runs", exact: true }).click();

  await expect(page).toHaveURL(/\/research-runs$/);
  await expect(page.getByRole("combobox", { name: "Filter by Type", exact: true })).toContainText("Factor Evaluation");
  expect(documentRequests).toEqual([]);
});

test("Start Tracking opens the created DailyTrack without a document reload", async ({ page }) => {
  const runId = "run_feedface1234abcd9876";
  const trackId = "track_cafebabefeed1234";
  const documentRequests = recordDocumentRequests(page);
  const startTrackingMethods: string[] = [];
  await page.route("**/api/research-folders", async (route) => {
    await route.fulfill({
      json: {
        items: [{
          id: "folder_default",
          name: "Default",
          is_default: true,
          created_at: "2026-08-13T00:00:00Z",
        }],
        next_cursor: null,
      },
    });
  });
  await page.route(`**/api/research-runs/${runId}`, async (route) => {
    await route.fulfill({
      json: {
        id: runId,
        status: "succeeded",
        name: "Tracking navigation regression",
        folder_id: "folder_default",
        created_at: "2026-08-13T01:02:03Z",
        start_date: "2026-08-01",
        end_date: "2026-08-05",
        formula_summary: "rank(close)",
        research_kind: "strategy_backtest",
      },
    });
  });
  await page.route(`**/api/research-runs/${runId}/daily-tracks`, async (route) => {
    startTrackingMethods.push(route.request().method());
    await route.fulfill({ status: 201, json: { id: trackId } });
  });

  await page.goto(`/research-runs/${runId}`);
  await expect(page.getByRole("button", { name: "Start Tracking" })).toBeVisible();
  documentRequests.length = 0;

  await page.getByRole("button", { name: "Start Tracking" }).click();

  await expect(page).toHaveURL(new RegExp(`/daily-tracks/${trackId}$`));
  expect(startTrackingMethods).toEqual(["POST"]);
  expect(documentRequests).toEqual([]);
});

test("Research deletion uses an in-page decision instead of a browser dialog", async ({ page }) => {
  const runId = "run_de1e7ed1a109";
  let deleteRequestCount = 0;
  const nativeDialogs: string[] = [];
  page.on("dialog", async (dialog) => {
    nativeDialogs.push(dialog.type());
    await dialog.dismiss();
  });
  await page.route("**/api/research-folders", async (route) => {
    await route.fulfill({
      json: {
        items: [{
          id: "folder_default",
          name: "Default",
          is_default: true,
          created_at: "2026-08-13T00:00:00Z",
        }],
        next_cursor: null,
      },
    });
  });
  await page.route(`**/api/research-runs/${runId}`, async (route) => {
    const request = route.request();
    if (request.method() === "DELETE") {
      deleteRequestCount += 1;
      await route.fulfill({ status: 204 });
      return;
    }
    await route.fulfill({
      json: {
        id: runId,
        status: "succeeded",
        name: "Deletion dialog regression",
        folder_id: "folder_default",
        created_at: "2026-08-13T01:02:03Z",
        start_date: "2026-08-01",
        end_date: "2026-08-05",
        formula_summary: "rank(close)",
        research_kind: "factor_evaluation",
      },
    });
  });
  await page.route("**/api/research-runs?*", async (route) => {
    await route.fulfill({ json: { items: [], total_count: 0 } });
  });

  await page.goto(`/research-runs/${runId}`);
  await page.getByRole("button", { name: "More actions", exact: true }).click();
  await page.getByRole("menuitem", { name: "Delete Research", exact: true }).click();

  const decision = page.getByRole("alertdialog", { name: "Delete Research?" });
  await expect(decision).toBeVisible();
  expect(nativeDialogs).toEqual([]);
  await expect(decision).toContainText("Deletion dialog regression");
  await expect(decision).toContainText("This cannot be undone.");
  await expect(decision).toContainText("DailyTracks will remain.");
  expect(deleteRequestCount).toBe(0);

  await page.keyboard.press("Escape");
  await expect(decision).toHaveCount(0);
  await expect(page.getByRole("button", { name: "More actions", exact: true })).toBeFocused();
  expect(deleteRequestCount).toBe(0);

  await page.getByRole("button", { name: "More actions", exact: true }).click();
  await page.getByRole("menuitem", { name: "Delete Research", exact: true }).click();
  await decision.getByRole("button", { name: "Keep Research" }).click();
  await expect(decision).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`/research-runs/${runId}$`));
  expect(deleteRequestCount).toBe(0);

  await page.getByRole("button", { name: "More actions", exact: true }).click();
  await page.getByRole("menuitem", { name: "Delete Research", exact: true }).click();
  await decision.getByRole("button", { name: "Delete Research", exact: true }).click();
  await expect(page).toHaveURL(/\/research-runs$/);
  expect(deleteRequestCount).toBe(1);
});

test("Notes keeps multiline research context visible", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 958 });
  await page.goto("/research");

  await page.getByRole("button", { name: "Research notes (optional)", exact: true }).click();
  const notes = page.getByLabel("Notes", { exact: true });
  await expect(notes).toBeVisible();
  await notes.fill(
    "Long turnover-amount leaders in Top 300; 20 holdings, rebalance every 5 sessions.",
  );
  const layout = await notes.evaluate((element) => ({
    height: element.getBoundingClientRect().height,
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));

  expect(layout.height).toBeGreaterThanOrEqual(64);
  expect(layout.scrollHeight).toBeLessThanOrEqual(layout.clientHeight);
});

test("Alpha formula editor keeps line numbers on the research workbench", async ({ page }) => {
  await page.goto("/research");

  const editor = page.getByRole("textbox", { name: "Alpha formula", exact: true });
  await expect(editor.locator("..").locator(".cm-gutters")).toContainText("1");
  await expect(editor.locator("..").locator(".cm-activeLineGutter")).toBeVisible();
});

test("date inputs retain manually entered values when focus leaves the field", async ({ page }) => {
  await page.goto("/research?new");
  await page.getByLabel("Research name").fill("Browser populated dates");
  await page.getByRole("textbox", { name: "Alpha formula", exact: true }).click();
  await page.keyboard.type("close");
  await page.getByRole("combobox", { name: "Universe", exact: true }).click();
  await page.getByRole("option", { name: "Top 300", exact: true }).click();

  await page.getByRole("combobox", { name: "Neutralization", exact: true }).click();
  await page.getByRole("option", { name: "None", exact: true }).click();


  for (const [label, value] of [
    ["Research start date", "2025-08-13"],
    ["Research end date", "2026-08-13"],
  ] as const) {
    const input = page.getByLabel(label);
    await input.fill(value);
    await page.keyboard.press("Tab");
  }

  await page.getByRole("button", { name: "Research notes (optional)", exact: true }).click();
  await page.getByLabel("Notes", { exact: true }).fill("Trigger a controlled React rerender.");
  await expect(page.getByLabel("Research start date")).toHaveValue("2025-08-13");
  await expect(page.getByLabel("Research end date")).toHaveValue("2026-08-13");
  await expect(page.getByRole("button", { name: /^Run (backtest|evaluation)$/ })).toBeEnabled();
});


test("Research Batch return keeps server cursor and All filter without document reload", async ({ page }) => {
  const base = { batch_kind: "factor_evaluation", status: "succeeded", created_at: "2026-09-15T00:00:00Z",
    scope: { start_date: "2026-08-04", end_date: "2026-08-05", universe: "top300", neutralization: "none" },
    progress: { completed_factor_tasks: 1, total_factor_tasks: 1 }, live_progress: null, items: [{ ordinal: 1, item_key: "Completed factor", research_run_id: "run_complete", status: "succeeded", run_availability: "available" }],
  };
  const queries: URLSearchParams[] = [];
  await page.route("**/api/research-batches?**", route => {
    const query = new URL(route.request().url()).searchParams;
    queries.push(query);
    return route.fulfill({ json: { items: [{ ...base, id: query.has("cursor") ? "batch_bbbbbbbbbbbbbbbbbbbb" : "batch_aaaaaaaaaaaaaaaaaaaa" }], next_cursor: query.has("cursor") ? null : "second" } });
  });
  await page.route("**/api/research-batches/batch_bbbbbbbbbbbbbbbbbbbb", route => route.fulfill({ json: { ...base, id: "batch_bbbbbbbbbbbbbbbbbbbb" } }));
  await page.goto("/research-runs/batches");
  await page.getByRole("button", { name: "All batches", exact: true }).click();
  const pages = page.getByRole("navigation", { name: "Batch pages", exact: true });
  await pages.getByRole("button", { name: "Next", exact: true }).click();
  await expect(pages).toContainText("Page 2");
  await page.getByRole("link").filter({ hasText: "batch_bbbbbbbbbbbbbbbbbbbb" }).click();
  await expect(page).toHaveURL(/\/research-runs\/batches\/batch_bbbbbbbbbbbbbbbbbbbb$/);
  const documents: string[] = [];
  page.on("request", request => { if (request.resourceType() === "document") documents.push(request.url()); });
  await page.getByRole("link", { name: "Back to Batches", exact: true }).click();
  await expect(pages).toContainText("Page 2");
  await expect(page.getByRole("button", { name: "All batches", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(queries.at(-1)?.get("cursor")).toBe("second");
  expect(queries.at(-1)?.get("active_only")).toBe("false");
  expect(documents).toEqual([]);
});
