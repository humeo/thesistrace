import type { Page } from "@playwright/test";
import { expect, test } from "./workbench-fixture";
import { comparisonValues, exampleDailyTrack } from "./fixtures/daily-track";
import { completedStrategyRun } from "./fixtures/strategy-result";

function recordDocumentRequests(page: Page): string[] {
  const documentRequests: string[] = [];
  page.on("request", (request) => {
    if (request.resourceType() === "document") documentRequests.push(request.url());
  });
  return documentRequests;
}

test("DailyTrack list and detail links keep the authenticated document", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const trackId = "track_cafebabefeed1234";
  const runId = "run_feedface1234abcd9876";
  const track = { ...exampleDailyTrack, id: trackId, seed_name: "Tracked strategy", origin: { ...exampleDailyTrack.origin, seed_run_id: runId } };
  await page.route("**/api/daily-tracks", route => route.fulfill({ json: { items: [{
    id: trackId, status: track.status, seed_name: track.seed_name, seed_run_id: runId, result_checksum_sha256: track.origin.result_checksum_sha256,
    origin_session: track.origin.strategy_session, strategy_session: track.strategy_session,
  }], next_cursor: null } }));
  await page.route(`**/api/daily-tracks/${trackId}`, route => route.fulfill({ json: track }));
  await page.route("**/api/daily-tracks/comparison?*", route => route.fulfill({ json: { items: [{ id: trackId, values: comparisonValues(track) }] } }));
  await page.route(`**/api/research-runs/${runId}`, route => route.fulfill({ json: { name: "Tracked strategy" } }));
  await page.goto("/daily-tracks");
  await expect(page.getByRole("link", { name: trackId, exact: true })).toBeVisible();
  const documents = recordDocumentRequests(page);
  const origin = await page.evaluate(() => performance.timeOrigin);

  await page.getByRole("link", { name: trackId, exact: true }).click();
  const back = page.locator('main a[href="/daily-tracks"]');
  await expect(back).toBeVisible();
  await back.click();
  await expect(page.getByRole("link", { name: trackId, exact: true })).toBeVisible();

  expect(documents).toEqual([]);
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
});

test("Operator section links keep the authenticated document", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.route("**/api/auth/operator/capability", route => route.fulfill({ json: { operator: true } }));
  await page.route("**/api/auth/operator/researchers*", route => route.fulfill({ json: { items: [], next_cursor: null } }));
  // The navigation remains available while operational status is temporarily unavailable.
  await page.route("**/api/operator/data/status", route => route.fulfill({ status: 503, json: { code: "UNAVAILABLE" } }));
  await page.goto("/operator/researchers");
  const data = page.locator('main a[href="/operator/data"]');
  await expect(data).toBeVisible();
  const documents = recordDocumentRequests(page);
  const origin = await page.evaluate(() => performance.timeOrigin);

  await data.click();
  await expect(data).toHaveAttribute("aria-current", "page");
  await page.locator('main a[href="/operator/researchers"]').click();
  await expect(data).not.toHaveAttribute("aria-current", "page");

  expect(documents).toEqual([]);
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
});

test("a lazy workspace route keeps the previous content visible until it can open", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/data");
  const fields = page.locator(".data-field-table");
  await expect(fields).toBeVisible();
  let release!: () => void;
  const available = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/assets/ResearchWorkspacePage-*.js", async route => {
    await available;
    await route.fallback();
  });
  const requested = page.waitForRequest("**/assets/ResearchWorkspacePage-*.js");
  await page.getByRole("link", { name: "Research", exact: true }).click();
  await requested;
  try {
    await expect(fields).toBeVisible();
    await expect(page.getByText("Loading workspace…", { exact: true })).toHaveCount(0);
  } finally { release(); }
  await expect(page.getByRole("button", { name: "Factor Evaluation", exact: true })).toBeVisible();
  await page.goBack();
  await expect(fields).toBeVisible();
  await page.goForward();
  await expect(page.getByRole("button", { name: "Factor Evaluation", exact: true })).toBeVisible();
});

test("a later navigation wins while an earlier lazy route is pending", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.route("**/api/research-runs?*", route => route.fulfill({ json: { items: [], total_count: 0 } }));
  await page.goto("/data");
  await expect(page.locator(".data-field-table")).toBeVisible();
  const documents = recordDocumentRequests(page);
  let release!: () => void;
  const available = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/assets/ResearchWorkspacePage-*.js", async route => { await available; await route.fallback(); });
  const requested = page.waitForRequest("**/assets/ResearchWorkspacePage-*.js");
  try {
    await page.getByRole("link", { name: "Research", exact: true }).click();
    await requested;
    await expect(page.locator(".data-field-table")).toBeVisible();
    await page.getByRole("link", { name: "Research Runs", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Research Runs", exact: true })).toBeVisible();
    const resolved = page.waitForResponse("**/assets/ResearchWorkspacePage-*.js");
    release();
    await resolved;
    await expect(page.getByRole("heading", { name: "Research Runs", exact: true })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole("button", { name: "Factor Evaluation", exact: true })).toBeVisible();
    await page.goForward();
    await expect(page.getByRole("heading", { name: "Research Runs", exact: true })).toBeVisible();
    expect(documents).toEqual([]);
  } finally { release(); }
});

test("changing Researcher clears private content while a lazy route is pending", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  let researcherId = "00000000-0000-4000-8000-000000000001";
  await page.route("**/api/auth/get-session", route => route.fulfill({ json: {
    session: { id: "00000000-0000-4000-8000-000000000002" },
    user: { id: researcherId, email: "browser@example.test", name: "Browser", active: true },
  } }));
  await page.route("**/api/researcher/bootstrap", route => route.fulfill({ json: {
    researcher_id: researcherId, system_folders: { default: "folder_default", batch_research: "folder_batch_research" },
  } }));
  await page.route("**/api/research-runs?*", route => route.fulfill({ json: { items: [{
    id: "run_cafebabefeed1234", name: "First Researcher's private run", research_kind: "factor_evaluation", status: "succeeded",
    folder_id: "folder_default", created_at: "2026-10-05T00:00:00Z", start_date: "2026-08-01", end_date: "2026-08-31", formula_summary: "rank(close)",
  }], total_count: 1 } }));
  await page.goto("/research-runs");
  const privateRun = page.getByRole("link", { name: "First Researcher's private run", exact: true });
  await expect(privateRun).toBeVisible();
  let release!: () => void;
  const available = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/assets/ResearchWorkspacePage-*.js", async route => { await available; await route.fallback(); });
  const requested = page.waitForRequest("**/assets/ResearchWorkspacePage-*.js");
  try {
    await page.getByRole("link", { name: "Research", exact: true }).click();
    await requested;
    await expect(privateRun).toBeVisible();
    researcherId = "00000000-0000-4000-8000-000000000003";
    const bootstrapped = page.waitForResponse("**/api/researcher/bootstrap");
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await bootstrapped;
    await expect(privateRun).toHaveCount(0);
    release();
    await expect(page.getByRole("button", { name: "Factor Evaluation", exact: true })).toBeVisible();
  } finally { release(); }
});

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
  await page.route("**/api/daily-tracks", route => route.fulfill({
    json: { items: [], next_cursor: null },
  }));

  await page.goto(`/research-runs/${runId}`);
  await expect(page.getByRole("button", { name: "Start Tracking" })).toBeVisible();
  documentRequests.length = 0;

  await page.getByRole("button", { name: "Start Tracking" }).click();

  await expect(page).toHaveURL(new RegExp(`/daily-tracks/${trackId}$`));
  expect(startTrackingMethods).toEqual(["POST"]);
  expect(documentRequests).toEqual([]);
});

test("Research deletion uses an in-page decision instead of a browser dialog", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
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
  const documents = recordDocumentRequests(page);
  const origin = await page.evaluate(() => performance.timeOrigin);
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
  expect(documents).toEqual([]);
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
});

test("creating a draft and submitting it keep the authenticated document", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const runId = "run_cafebabefeed1234";
  const acceptedId = "run_deadbeef1234abcd";
  const input = {
    formula: "rank(close)", hypothesis: null, start_date: "2026-08-01", end_date: "2026-08-05",
    universe: "top300", neutralization: "none", research_kind: "factor_evaluation",
  };
  const run = {
    id: runId, status: "failed", name: "Copied factor", input, research_kind: "factor_evaluation",
    folder_id: "folder_default", created_at: "2026-08-13T01:02:03Z", start_date: input.start_date,
    end_date: input.end_date, formula_summary: input.formula,
  };
  await page.route(`**/api/research-runs/${runId}`, route => route.fulfill({ json: run }));
  await page.route(`**/api/research-runs/${acceptedId}`, route => route.fulfill({ json: { ...run, id: acceptedId, name: "Accepted factor", status: "queued" } }));
  const submissions: unknown[] = [];
  await page.route("**/api/research-runs", route => {
    submissions.push(route.request().postDataJSON());
    return route.fulfill({ status: 201, json: { id: acceptedId } });
  });
  await page.goto(`/research-runs/${runId}`);
  await expect(page.getByRole("heading", { name: "Copied factor", exact: true })).toBeVisible();
  const documents = recordDocumentRequests(page);
  const origin = await page.evaluate(() => performance.timeOrigin);
  await page.getByRole("button", { name: "Create draft", exact: true }).click();
  await expect(page).toHaveURL(/\/research$/);
  await expect(page.getByRole("textbox", { name: "Alpha formula", exact: true })).toHaveText(input.formula);
  expect(documents).toEqual([]);
  await page.getByRole("button", { name: "Run evaluation", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/research-runs/${acceptedId}$`));
  await expect(page.getByRole("heading", { name: "Accepted factor", exact: true })).toBeVisible();
  expect(submissions).toHaveLength(1);
  expect(documents).toEqual([]);
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
});

test("deleting a stopped DailyTrack keeps the authenticated document", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const trackId = "track_cafebabefeed1234";
  const runId = "run_feedface1234abcd9876";
  const track = { ...exampleDailyTrack, id: trackId, status: "stopped", origin: { ...exampleDailyTrack.origin, seed_run_id: runId } };
  let deleted = false;
  await page.route("**/api/daily-tracks", route => route.fulfill({ json: { items: deleted ? [] : [{
    id: trackId, status: track.status, seed_run_id: runId, result_checksum_sha256: track.origin.result_checksum_sha256,
    origin_session: track.origin.strategy_session, strategy_session: track.strategy_session,
  }], next_cursor: null } }));
  await page.route(`**/api/daily-tracks/${trackId}`, route => {
    if (route.request().method() === "DELETE") { deleted = true; return route.fulfill({ status: 204 }); }
    return route.fulfill({ json: track });
  });
  await page.route(`**/api/research-runs/${runId}`, route => route.fulfill({ json: { name: "Stopped strategy" } }));
  await page.goto(`/daily-tracks/${trackId}`);
  await expect(page.getByRole("button", { name: "Manage", exact: true })).toBeVisible();
  const documents = recordDocumentRequests(page);
  const origin = await page.evaluate(() => performance.timeOrigin);
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  await page.getByRole("menuitem", { name: "Delete DailyTrack", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete DailyTrack", exact: true }).click();
  await expect(page).toHaveURL(/\/daily-tracks$/);
  expect(deleted).toBe(true);
  expect(documents).toEqual([]);
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
});

test("an expired holdings rerun opens its accepted ResearchRun without reloading", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const runId = "run_cafebabefeed1234";
  const acceptedId = "run_deadbeef1234abcd";
  await page.route(`**/api/research-runs/${runId}`, route => route.fulfill({ json: { ...completedStrategyRun, id: runId } }));
  await page.route(`**/api/research-runs/${runId}/holdings/query`, route => route.fulfill({ json: {
    status: "recorded", units: [{ unit_id: "unit_expired", source_kind: "research_run", first_session: "2026-08-03", last_session: "2026-08-04", expires_at: "2026-08-11T00:00:00Z", status: "expired" }], next_cursor: null,
  } }));
  await page.route(`**/api/research-runs/${acceptedId}`, route => route.fulfill({ json: { ...completedStrategyRun, id: acceptedId, name: "New holdings run", status: "queued", result: undefined } }));
  const submissions: unknown[] = [];
  await page.route("**/api/research-runs", route => {
    submissions.push(route.request().postDataJSON());
    return route.fulfill({ status: 202, json: { id: acceptedId } });
  });
  await page.goto(`/research-runs/${runId}`);
  await page.getByRole("tab", { name: "Daily holdings", exact: true }).click();
  await expect(page.getByRole("button", { name: "Rerun to generate holdings" })).toBeVisible();
  const documents = recordDocumentRequests(page);
  const origin = await page.evaluate(() => performance.timeOrigin);
  await page.getByRole("button", { name: "Rerun to generate holdings" }).click();
  await expect(page.getByRole("heading", { name: "New holdings run", exact: true })).toBeVisible();
  expect(submissions).toHaveLength(1);
  expect(submissions[0]).toMatchObject({ folder_id: "folder_default", rerun_source: { kind: "research_run", run_id: runId } });
  expect(documents).toEqual([]);
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
});

test("Notes keeps multiline research context visible", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 958 });
  await page.goto("/research");
  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();

  await expect(page.getByRole("button", { name: "Research notes (optional)", exact: true })).toHaveCount(0);
  const notes = page.getByLabel("Research notes (optional)", { exact: true });
  await expect(notes).toBeVisible();
  const workbenchBox = (await page.locator(".research-workbench").boundingBox())!;
  const notesBox = (await notes.boundingBox())!;
  expect(notesBox.y - (workbenchBox.y + workbenchBox.height)).toBeGreaterThanOrEqual(32);
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

  await page.reload();
  await expect(notes).toBeVisible();
  await expect(notes).toHaveValue("Long turnover-amount leaders in Top 300; 20 holdings, rebalance every 5 sessions.");
});

test("Alpha formula editor aligns with the conditions by default and remains vertically resizable", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1544, height: 954 });
  await page.goto("/research");
  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();

  await expect(page.getByRole("button", { name: "Expand editor", exact: true })).toHaveCount(0);
  const heading = page.getByRole("heading", { name: "Alpha formula", exact: true });
  await expect(heading).toBeVisible();
  await expect(page.getByText("Ctrl + Space to autocomplete", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Browse fields", exact: true })).toBeVisible();
  const editor = page.getByRole("textbox", { name: "Alpha formula", exact: true });
  await expect(editor.locator(".cm-placeholder")).toHaveText("rank(pct_change(close, 20))");
  const help = page.getByRole("button", { name: "Alpha formula writing rules", exact: true });
  const rules = page.getByRole("dialog", { name: "Alpha formula writing rules", exact: true });
  await help.click();
  await expect(rules).toContainText("Write a single expression");
  await expect(rules).toContainText("Time windows are integers from 1 to 252");
  await expect(rules).toContainText("rank(pct_change(close, 20))");
  await page.keyboard.press("Escape");
  await expect(rules).not.toBeVisible();
  await expect(help).toBeFocused();
  await help.press("Enter");
  await expect(rules).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(editor.locator("..").locator(".cm-gutters")).toContainText("1");
  await expect(editor.locator("..").locator(".cm-activeLineGutter")).toBeVisible();
  await editor.fill("rank(close)");
  const frame = page.getByLabel("Alpha formula editor", { exact: true }).locator("..");
  const box = (await frame.boundingBox())!;
  expect(box.height).toBe(382);
  await expect(frame).toHaveCSS("min-height", "180px");
  await expect(frame).toHaveCSS("resize", "vertical");
  const conditions = (await page.locator(".research-settings-panel").boundingBox())!;
  const headingBox = (await heading.boundingBox())!;
  const helpBox = (await help.boundingBox())!;
  expect(Math.abs(headingBox.y + headingBox.height / 2 - conditions.y - 13)).toBeLessThan(2);
  expect(helpBox.x).toBeGreaterThan(headingBox.x + headingBox.width);
  expect(helpBox.y).toBeGreaterThanOrEqual(conditions.y - 8);
  expect(helpBox.y + helpBox.height).toBeLessThan(box.y);
  expect(Math.abs(box.y + box.height - conditions.y - conditions.height)).toBeLessThan(1);
  await page.screenshot({ path: testInfo.outputPath("formula-aligned-with-conditions.png") });
  await expect(frame).not.toHaveCSS("box-shadow", "none");
  const numberAlignment = await editor.locator("..").locator(".cm-activeLineGutter").evaluate(number => {
    const text = document.createRange();
    text.selectNodeContents(number);
    const textBox = text.getBoundingClientRect();
    const gutterBox = number.closest(".cm-gutters")!.getBoundingClientRect();
    return Math.abs(textBox.x + textBox.width / 2 - gutterBox.x - gutterBox.width / 2);
  });
  expect(numberAlignment).toBeLessThan(2);
  const browse = page.getByRole("button", { name: "Browse fields", exact: true });
  const browseBox = (await browse.boundingBox())!;
  expect(browseBox.y + browseBox.height).toBeLessThan(box.y);
  expect(Math.abs(browseBox.y + browseBox.height / 2 - headingBox.y - headingBox.height / 2)).toBeLessThan(1);
  expect(Math.abs(browseBox.x + browseBox.width - box.x - box.width)).toBeLessThan(2);
  expect(helpBox.x + helpBox.width).toBeLessThan(headingBox.x + headingBox.width + 40);
  await expect(frame.getByRole("button", { name: "Browse fields", exact: true })).toHaveCount(0);
  const lineBox = (await editor.locator(".cm-line").boundingBox())!;
  expect(box.x + box.width - lineBox.x - lineBox.width).toBeLessThan(16);
  await page.mouse.move(box.x + box.width - 3, box.y + box.height - 3);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width - 3, box.y + box.height + 97, { steps: 10 });
  await page.mouse.up();
  await expect.poll(async () => (await frame.boundingBox())!.height).toBeGreaterThan(box.height + 60);
  const resizedHeight = (await frame.boundingBox())!.height;
  await expect(editor).toHaveText("rank(close)");
  await editor.fill(Array.from({ length: 30 }, () => "close").join("\n"));
  expect((await frame.boundingBox())!.height).toBe(resizedHeight);
  const scroller = editor.locator("..");
  await expect(scroller).toHaveCSS("overflow-y", "auto");
  const scrollSize = await scroller.evaluate(element => ({ height: element.clientHeight, contentHeight: element.scrollHeight }));
  expect(scrollSize.contentHeight).toBeGreaterThan(scrollSize.height);
  await editor.press("ControlOrMeta+End");
  await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
  await editor.fill("rank(close)");
  await browse.click();
  const fields = page.getByRole("dialog", { name: "Field browser", exact: true });
  await expect(fields.getByRole("searchbox", { name: "Search fields", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(fields).not.toBeVisible();
  await expect(browse).toBeFocused();
  await editor.press("ControlOrMeta+A");
  await browse.click();
  await fields.getByRole("searchbox", { name: "Search fields", exact: true }).fill("close");
  await fields.getByRole("button", { name: "Insert into formula", exact: true }).click();
  await expect(fields).not.toBeVisible();
  await expect(editor).toHaveText("close");
  await expect(editor).toBeFocused();
  await editor.fill("rank(close)");
  await page.reload();
  await expect(editor).toHaveText("rank(close)");
  expect((await frame.boundingBox())!.height).toBe(382);
});

test("Configuration feedback follows the actions after checking, without a validation header", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1528, height: 954 });
  let finish!: () => void;
  const pending = new Promise<void>(resolve => { finish = resolve; });
  let checks = 0;
  await page.route("**/api/research/diagnostics", async route => {
    checks += 1;
    if (checks === 1) {
      await pending;
      return route.fulfill({ json: { valid: false, issues: [{
        code: "WINDOW_OUT_OF_RANGE", field: "formula", severity: "error",
        message: "Window must be between 1 and 252", details: { kind: "window", expected: [1, 252], actual: "253" },
        range: { start: { offset: 15, line: 1, column: 16 }, end: { offset: 18, line: 1, column: 19 } },
      }] } });
    }
    if (checks === 2) return route.fulfill({ json: { valid: true, issues: [] } });
    return route.fulfill({ status: 503 });
  });
  await page.goto("/research?new");
  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();
  const actions = page.getByRole("group", { name: "Research actions", exact: true });
  const check = actions.getByRole("button", { name: "Check configuration", exact: true });
  const formula = page.getByRole("textbox", { name: "Alpha formula", exact: true });
  await expect(formula).toBeVisible();
  await expect(formula.locator(".cm-placeholder")).toHaveText("rank(pct_change(close, 20))");
  await expect(page.getByText("Not checked yet", { exact: true })).toHaveCount(0);
  await expect(actions.getByRole("status")).toHaveCount(0);

  await check.click();
  await expect(actions.getByRole("alert")).toContainText("Choose a ranking rule or enter a formula.");
  await expect(formula).toBeFocused();
  expect(checks).toBe(0);
  await formula.fill("ts_mean(close, 253)");
  await page.getByLabel("Research start date").fill("2026-08-01");
  await page.getByLabel("Research end date").fill("2026-08-05");
  await page.getByRole("combobox", { name: "Universe", exact: true }).click();
  await page.getByRole("option", { name: "Top 300", exact: true }).click();
  await expect(actions.getByRole("alert")).toHaveCount(0);
  await check.click();
  await expect(actions.getByRole("status")).toHaveText("Checking configuration…");
  await expect(check).toBeDisabled();
  finish();
  const issues = actions.getByRole("list", { name: "Configuration issues", exact: true });
  await expect(issues).toContainText("Window must be between 1 and 252; received 253.");
  await expect(actions.getByRole("status")).toHaveText("Resolve the configuration issues.");
  await expect(page.locator(".research-workbench").getByRole("status")).toHaveCount(0);
  await issues.getByRole("button").click();
  await expect(formula).toBeFocused();
  const actionBox = (await actions.boundingBox())!;
  expect(actionBox.y + actionBox.height).toBeLessThanOrEqual(954 - 16);
  const notes = page.getByRole("textbox", { name: "Research notes (optional)", exact: true });
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const notesBox = (await notes.boundingBox())!;
  expect(notesBox.y + notesBox.height).toBeLessThan(actionBox.y - 8);
  await page.screenshot({ path: testInfo.outputPath("configuration-issues-with-actions.png") });

  await formula.fill("rank(close)");
  await expect(issues).toHaveCount(0);
  await expect(actions.getByRole("status")).toHaveText("Configuration changed · check again");
  await check.click();
  await expect(actions.getByRole("status")).toContainText("Configuration is valid.");
  await expect(actions.getByRole("alert")).toHaveCount(0);
  await check.click();
  await expect(actions.getByRole("status")).toHaveText("Configuration check is unavailable. Try again.");
  await expect(formula).toHaveText("rank(close)");
  await expect(check).toBeEnabled();
});

test("date inputs retain manually entered values when focus leaves the field", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/research?new");
  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();
  await page.getByTitle("Edit research name", { exact: true }).click();
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

  await page.getByLabel("Research notes (optional)", { exact: true }).fill("Trigger a controlled React rerender.");
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
