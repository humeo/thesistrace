import { expect, test, workbenchData } from "./workbench-fixture";
import { serveBrandAssets } from "./brand-assets";
import { completedStrategyRun } from "./fixtures/strategy-result";
import { exampleDailyTrack } from "./fixtures/daily-track";

test("Research modules survive refresh, direct opening and browser history without losing edits", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const folderReads: string[] = [];
  page.on("request", request => { if (new URL(request.url()).pathname === "/api/research-folders") folderReads.push(request.url()); });
  await page.goto("/research?folder=folder_default#notes");
  await page.getByRole("button", { name: "Strategy Backtest", exact: true }).click();
  const universe = page.getByRole("tab", { name: "Universe", exact: true });
  await expect(universe).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Portfolio", exact: true }).click();
  await page.getByLabel("Holdings count", { exact: true }).fill("13");
  const notes = page.getByRole("textbox", { name: "Research notes (optional)", exact: true });
  await notes.fill("Keep this draft and module");
  await page.getByRole("tab", { name: "Risk", exact: true }).click();
  await expect(page).toHaveURL(/folder=folder_default.*module=risk#notes$/);
  const reads = folderReads.length;
  await page.getByRole("tab", { name: "Signals", exact: true }).click();
  await expect(page).toHaveURL(/module=signal#notes$/);
  expect(folderReads.length).toBe(reads);
  await page.goBack();
  await expect(page.getByRole("tab", { name: "Risk", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.goForward();
  await expect(page.getByRole("tab", { name: "Signals", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.reload();
  await expect(page.getByRole("tab", { name: "Signals", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(notes).toHaveValue("Keep this draft and module");
  const copy = await context.newPage();
  await serveBrandAssets(copy);
  await copy.goto(page.url());
  await expect(copy.getByRole("tab", { name: "Signals", exact: true })).toHaveAttribute("aria-selected", "true");
  await copy.close();
  await page.getByRole("tab", { name: "Portfolio", exact: true }).click();
  await expect(page.getByLabel("Holdings count", { exact: true })).toHaveValue("13");
  await page.goto("/research?module=unknown");
  await expect(universe).toHaveAttribute("aria-selected", "true");
});

test("Data directory tabs survive refresh and direct links", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.route("**/api/data", route => route.fulfill({ json: { ...workbenchData, field_families: [] } }));
  await page.goto("/data");
  const functions = page.getByRole("tab", { name: /^Aggregate functions/ });
  const industries = page.getByRole("tab", { name: /^Industry codes/ });
  await functions.click();
  await expect(page).toHaveURL(/\/data\?tab=functions$/);
  await page.reload();
  await expect(functions).toHaveAttribute("aria-selected", "true");
  await industries.click();
  await page.goBack();
  await expect(functions).toHaveAttribute("aria-selected", "true");
  await page.goto("/data?tab=industries");
  await expect(industries).toHaveAttribute("aria-selected", "true");
});

test("Research results restore a lazy tab after refresh and navigation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const id = "run_feedface1234abcd";
  await page.route(`**/api/research-runs/${id}`, route => route.fulfill({ json: { ...completedStrategyRun, id } }));
  await page.route(`**/api/research-runs/${id}/events/query`, route => route.fulfill({ json: {
    section: route.request().postDataJSON().section, status: "recorded", rows: [], next_cursor: null,
  } }));
  await page.goto(`/research-runs/${id}`);
  const events = page.getByRole("tab", { name: "Trading events", exact: true });
  await events.click();
  await expect(page).toHaveURL(/\?tab=events$/);
  await page.reload();
  await expect(events).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("No matching Orders records.", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Configuration", exact: true }).click();
  await page.goBack();
  await expect(events).toHaveAttribute("aria-selected", "true");
  await page.goto(`/research-runs/${id}?tab=evidence`);
  await expect(page.getByRole("tab", { name: "Overview", exact: true })).toHaveAttribute("aria-selected", "true");
});

test("Daily tracking restores its review tab and content after refresh", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const id = "track_feedface1234abcd";
  const seed = "run_feedface1234abcd";
  const track = { ...exampleDailyTrack, id, origin: { ...exampleDailyTrack.origin, seed_run_id: seed } };
  await page.route(`**/api/daily-tracks/${id}`, route => route.fulfill({ json: track }));
  await page.route("**/api/daily-tracks", route => route.fulfill({ json: { items: [{
    id, status: track.status, seed_run_id: seed, result_checksum_sha256: track.origin.result_checksum_sha256,
    origin_session: track.origin.strategy_session, strategy_session: track.strategy_session,
  }], next_cursor: null } }));
  await page.route(`**/api/research-runs/${seed}`, route => route.fulfill({ json: { ...completedStrategyRun, id: seed } }));
  await page.route(`**/api/daily-tracks/${id}/events/query`, route => route.fulfill({ json: {
    section: route.request().postDataJSON().section, status: "recorded", rows: [], next_cursor: null,
  } }));
  await page.goto(`/daily-tracks/${id}`);
  const review = page.getByRole("tab", { name: "Daily review", exact: true });
  await review.click();
  await expect(page).toHaveURL(/\?tab=review$/);
  await page.reload();
  await expect(review).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("navigation", { name: "Observation dates", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: /^Holdings/ }).click();
  await page.goBack();
  await expect(review).toHaveAttribute("aria-selected", "true");
  await page.goto(`/daily-tracks/${id}?tab=rebalance`);
  await expect(page.getByRole("tab", { name: "Rebalance", exact: true })).toHaveAttribute("aria-selected", "true");
});
