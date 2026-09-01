import { type Locator, type Page, type Route, type TestInfo } from "@playwright/test";
import { execFileSync, type ChildProcess } from "node:child_process";

import { expect, sameOriginHeaders, test } from "./auth-fixture";
import {
  controlledWorkerExit,
  controlWorker,
  startControlledResearchRun,
} from "./research-run-control";

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
        next_cursor: null,
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
  await page.getByLabel("Filter by Type").selectOption("factor_evaluation");
  await page.getByRole("link", { name: "Filtered Factor", exact: true }).click();
  await expect(page).toHaveURL(/\/research-runs\/run_feedface1234abcd9876$/);
  await expect(page.getByRole("heading", { name: "ResearchRun", exact: true })).toBeVisible();
  documentRequests.length = 0;

  await page.getByRole("link", { name: "Back to Research Runs", exact: true }).click();

  await expect(page).toHaveURL(/\/research-runs$/);
  await expect(page.getByLabel("Filter by Type")).toHaveValue("factor_evaluation");
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
    await route.fulfill({ json: { items: [], next_cursor: null } });
  });

  await page.goto(`/research-runs/${runId}`);
  await page.getByRole("button", { name: "Delete Research", exact: true }).click();

  const decision = page.getByRole("dialog", { name: "Delete Research?" });
  await expect(decision).toBeVisible();
  expect(nativeDialogs).toEqual([]);
  await expect(decision).toContainText("Deletion dialog regression");
  await expect(decision).toContainText("This cannot be undone.");
  await expect(decision).toContainText("DailyTracks will remain.");
  expect(deleteRequestCount).toBe(0);

  await page.keyboard.press("Escape");
  await expect(decision).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Delete Research", exact: true })).toBeFocused();
  expect(deleteRequestCount).toBe(0);

  await page.getByRole("button", { name: "Delete Research", exact: true }).click();
  await decision.getByRole("button", { name: "Keep Research" }).click();
  await expect(decision).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`/research-runs/${runId}$`));
  expect(deleteRequestCount).toBe(0);

  await page.getByRole("button", { name: "Delete Research", exact: true }).click();
  await decision.getByRole("button", { name: "Delete Research", exact: true }).click();
  await expect(page).toHaveURL(/\/research-runs$/);
  expect(deleteRequestCount).toBe(1);
});

test("Notes keeps multiline research context visible", async ({ page }) => {
  await page.setViewportSize({ width: 956, height: 958 });
  await page.goto("/research");

  const notes = page.getByLabel("Notes");
  await notes.fill(
    "Long turnover-amount leaders in Top 300; 20 holdings, rebalance every 5 sessions.",
  );
  const layout = await notes.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));

  expect(layout.clientHeight).toBeGreaterThanOrEqual(72);
  expect(layout.scrollHeight).toBeLessThanOrEqual(layout.clientHeight);
});

test("Alpha formula editor keeps line numbers on the dark workbench surface", async ({ page }) => {
  await page.goto("/research");

  await expect(page.locator(".cm-gutters")).toHaveCSS(
    "background-color",
    "rgb(15, 16, 17)",
  );
  await expect(page.locator(".cm-activeLineGutter")).toHaveCSS(
    "background-color",
    "rgb(20, 21, 22)",
  );
});

test("date inputs retain a browser-populated value when focus leaves the field", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.startsWith("/api/auth/") || pathname === "/api/researcher/bootstrap") {
      await route.continue();
      return;
    }
    if (pathname === "/api/research-folders") {
      await route.fulfill({ json: { items: [{ id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-13T00:00:00Z" }], next_cursor: null } });
      return;
    }
    if (pathname === "/api/alpha/catalog") {
      await route.fulfill({ json: { fields: [], builtins: [] } });
      return;
    }
    if (pathname === "/api/data") {
      await route.fulfill({ json: {
        market_coverage: { start: "2010-01-04", end: "2026-08-13" },
        financial_coverage: null,
        industry_coverage: null,
        benchmark_coverage: null,
        benchmark_snapshot_sha256: null,
        benchmark_last_published_at: null,
        data_through_session: "2026-08-13",
        last_market_refresh_at: null,
        last_financial_refresh_at: null,
        last_industry_refresh_at: null,
        industry_refresh_status: null,
        industry_refresh_failure_code: null,
        market_research_readiness: true,
        benchmark_research_readiness: false,
        financial_research_readiness: "not_ready",
        industry_research_readiness: false,
      } });
      return;
    }
    await route.abort();
  });
  await page.goto("/research?new");
  await page.getByLabel("Research name").fill("Browser populated dates");
  await page.locator(".cm-content").click();
  await page.keyboard.type("close");
  await page.getByLabel("Universe").selectOption("top300");
  await page.getByLabel("Neutralization").selectOption("none");

  for (const [label, value] of [
    ["Research start date", "2025-08-13"],
    ["Research end date", "2026-08-13"],
  ] as const) {
    const input = page.getByLabel(label);
    await input.focus();
    await input.evaluate((element, populatedValue) => {
      (element as HTMLInputElement).value = populatedValue;
    }, value);
    await page.keyboard.press("Tab");
  }

  await page.getByLabel("Notes").fill("Trigger a controlled React rerender.");
  await expect(page.getByLabel("Research start date")).toHaveValue("2025-08-13");
  await expect(page.getByLabel("Research end date")).toHaveValue("2026-08-13");
  await expect(page.getByRole("button", { name: "Run research" })).toBeEnabled();
});

test("Default Folder retains one local Research Draft with authoritative Formula diagnostics", async ({ page, researcher }, testInfo) => {
  test.setTimeout(90_000);
  const defaultDraftKey = `thesistrace.research-draft.${researcher.id}.folder_default`;
  const responses: string[] = [];
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    const hostname = new URL(request.url()).hostname;
    if (hostname !== "127.0.0.1" && hostname !== "localhost") externalRequests.push(request.url());
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/")) {
      responses.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });

  try {
    await page.goto("/data");
    await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
    await expect(page.getByText("Market ready")).toBeVisible();
    await expect(page.getByText("Finance ready")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Research fields" })).toBeVisible();
    await expect(page.getByText("Coverage describes the dataset")).toHaveCount(0);
    await expectRemovedAuthoringControlsToBeAbsent(page);

    await page.getByRole("link", { name: "Research", exact: true }).click();
    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByRole("region", { name: "Research", exact: true })).toBeVisible();
    await expect(page.getByText("Default folder", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Research name")).toHaveValue("");
    await expect(page.locator(".cm-placeholder")).toHaveText("Start with a field or function");
    await expect(page.getByText("Research period", { exact: true })).toHaveCount(0);
    await expectRemovedAuthoringControlsToBeAbsent(page);

    const factorEvaluation = page.getByRole("radio", { name: /Factor Evaluation/ });
    const strategyBacktest = page.getByRole("radio", { name: /Strategy Backtest/ });
    await expect(page.getByRole("group", { name: "Research type" })).toBeVisible();
    await expect(factorEvaluation).toBeChecked();
    await expect(strategyBacktest).not.toBeChecked();
    await expect(page.getByLabel("Holdings count")).toHaveCount(0);
    await expect(page.getByLabel("Rebalance sessions")).toHaveCount(0);
    await page.setViewportSize({ width: 480, height: 900 });
    await expect(factorEvaluation).toBeVisible();
    await expect(strategyBacktest).toBeVisible();
    const maxDateRange = page.getByRole("button", { name: "Use all available data" });
    await expect(maxDateRange).toBeVisible();
    expect((await maxDateRange.boundingBox())?.height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.setViewportSize({ width: 1280, height: 900 });

    const startDate = page.getByLabel("Research start date");
    const endDate = page.getByLabel("Research end date");
    const coverageStart = await startDate.getAttribute("min");
    const coverageEnd = await endDate.getAttribute("max");
    expect(coverageStart).not.toBeNull();
    expect(coverageEnd).not.toBeNull();
    await maxDateRange.click();
    await expect(startDate).toHaveValue(coverageStart!);
    await expect(endDate).toHaveValue(coverageEnd!);

    await factorEvaluation.focus();
    await page.keyboard.press("ArrowRight");
    await expect(strategyBacktest).toBeChecked();
    const holdingsCount = page.getByLabel("Holdings count");
    await expect(holdingsCount).toBeVisible();
    await expect(page.getByLabel("Rebalance sessions")).toBeVisible();
    const decreaseHoldings = page.getByRole("button", { name: "Decrease number of holdings" });
    const increaseHoldings = page.getByRole("button", { name: "Increase number of holdings" });
    const decreaseRebalance = page.getByRole("button", { name: "Decrease rebalance interval" });
    const increaseRebalance = page.getByRole("button", { name: "Increase rebalance interval" });
    await expect(decreaseHoldings).toBeDisabled();
    for (const stepperButton of [decreaseHoldings, increaseHoldings, decreaseRebalance, increaseRebalance]) {
      await expect(stepperButton).toBeVisible();
      const bounds = await stepperButton.boundingBox();
      expect(bounds?.width).toBeGreaterThanOrEqual(44);
      expect(bounds?.height).toBeGreaterThanOrEqual(44);
    }
    await increaseHoldings.click();
    await expect(holdingsCount).toHaveValue("1");
    await increaseHoldings.click();
    await expect(holdingsCount).toHaveValue("2");
    await decreaseHoldings.click();
    await expect(holdingsCount).toHaveValue("1");
    await holdingsCount.fill("10");
    await holdingsCount.press("ArrowUp");
    await expect(holdingsCount).toHaveValue("11");
    await holdingsCount.press("ArrowDown");
    await expect(holdingsCount).toHaveValue("10");

    await page.getByLabel("Research name").fill("Browser Mean Research");
    const editor = page.locator(".cm-content");
    await editor.click();
    await page.keyboard.type("ts_");
    await page.keyboard.press("Control+Space");
    const meanCompletion = page.getByRole("option", { name: /ts_mean/ });
    await expect(meanCompletion).toBeVisible();
    await expect(page.locator(".cm-completionInfo")).toContainText("Complete-window rolling");
    await page.keyboard.press("Escape");
    await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
    await page.keyboard.type("unknown_field");
    await expect(page.getByRole("list", { name: "Formula diagnostics" })).toBeVisible();
    await expect(page.locator(".cm-lintRange-error")).toHaveCount(1);
    await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
    const validDiagnosis = page.waitForResponse((response) => (
      response.url().includes("/api/alpha/diagnostics") &&
      response.request().method() === "POST" &&
      response.ok()
    ));
    await page.keyboard.type("ts_mean(close, 2)");
    await validDiagnosis;
    await expect(editor).toHaveText("ts_mean(close, 2)");
    await expect(page.locator(".cm-alpha-field").first()).toHaveCSS("color", "rgb(139, 213, 202)");
    await expect(page.getByRole("list", { name: "Formula diagnostics" })).toHaveCount(0);
    await page.getByLabel("Notes").fill("Short rolling mean retains signal.");
    await page.getByLabel("Research start date").fill("2026-08-03");
    await page.getByLabel("Research end date").fill("2026-08-05");
    await page.getByLabel("Universe").selectOption("top300");
    await page.getByLabel("Neutralization").selectOption("none");
    await page.getByLabel("Holdings count").fill("10");
    await page.getByLabel("Rebalance sessions").fill("2");

    await strategyBacktest.focus();
    await page.keyboard.press("ArrowLeft");
    await expect(factorEvaluation).toBeChecked();
    await expect(page.getByLabel("Holdings count")).toHaveCount(0);
    await expect(page.getByLabel("Rebalance sessions")).toHaveCount(0);
    await strategyBacktest.check();
    await page.getByLabel("Holdings count").fill("10");
    await page.getByLabel("Rebalance sessions").fill("2");

    const browserKeys = await page.evaluate(() => Object.keys(localStorage));
    expect(browserKeys).toEqual([defaultDraftKey]);
    const retainedDraft = await page.evaluate((draftKey) => JSON.parse(
      localStorage.getItem(draftKey) ?? "null",
    ), defaultDraftKey);
    expect(retainedDraft).toMatchObject({
      name: "Browser Mean Research",
      formula: "ts_mean(close, 2)",
      universe: "top300",
      neutralization: "none",
      researchKind: "strategy_backtest",
      holdingsCount: "10",
      rebalanceEverySessions: "2",
      lastAdmittedBaseline: null,
    });

    await page.reload();
    await expect(page.getByLabel("Research name")).toHaveValue("Browser Mean Research");
    await expect(page.locator(".cm-content")).toHaveText("ts_mean(close, 2)");
    await expect(page.getByLabel("Notes")).toHaveValue("Short rolling mean retains signal.");
    await expect(page.getByLabel("Universe")).toHaveValue("top300");

    page.once("dialog", async (dialog) => dialog.dismiss());
    const workspaceNew = page.locator(".research-workspace-header").getByRole("button", { name: "New research" });
    await workspaceNew.click();
    await expect(page.getByLabel("Research name")).toHaveValue("Browser Mean Research");
    page.once("dialog", async (dialog) => dialog.accept());
    await workspaceNew.click();
    await expect(page.getByLabel("Research name")).toHaveValue("");
    await expect(page.locator(".cm-placeholder")).toHaveText("Start with a field or function");
    expect(await page.evaluate((draftKey) => localStorage.getItem(draftKey), defaultDraftKey)).toBeNull();

    await openResearchFolderMenu(page);
    await page.getByLabel("New Folder").fill("Signals");
    await page.getByRole("button", { name: "Create Folder" }).click();
    await expect(page).toHaveURL(/\/research\?folder=folder_[a-f0-9]+$/);
    const customFolderId = new URL(page.url()).searchParams.get("folder");
    expect(customFolderId).toMatch(/^folder_[a-f0-9]+$/);
    if (customFolderId === null) throw new Error("Custom Folder route is missing folder id");
    await expect(page.getByText("Signals", { exact: true }).first()).toBeVisible();
    await page.getByLabel("Research name").fill("Signals browser Draft");
    await page.locator(".cm-content").click();
    await page.keyboard.type("volume");

    await closeResearchFolderMenu(page);
    page.once("dialog", async (dialog) => dialog.dismiss());
    await workspaceNew.click();
    await expect(page.getByLabel("Research name")).toHaveValue("Signals browser Draft");

    await page.getByRole("link", { name: "Research", exact: true }).click();
    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByLabel("Research name")).toHaveValue("");
    expect(await page.evaluate(
      ({ folderId, activeResearcherId }) => localStorage.getItem(
        `thesistrace.research-draft.${activeResearcherId}.${folderId}`,
      ),
      { folderId: customFolderId, activeResearcherId: researcher.id },
    )).not.toBeNull();
    await openResearchFolderMenu(page);
    await page.getByRole("link", { name: "Signals", exact: true }).click();
    await expect(page.getByLabel("Research name")).toHaveValue("Signals browser Draft");
    await expect(page.locator(".cm-content")).toHaveText("volume");
    expect(await page.evaluate(() => Object.keys(localStorage).sort())).toEqual([
      `thesistrace.research-draft.${researcher.id}.${customFolderId}`,
    ]);

    await openResearchFolderMenu(page);
    await page.getByLabel("Folder name").fill("Momentum");
    await page.getByRole("button", { name: "Rename Folder" }).click();
    await expect(page.getByRole("link", { name: "Momentum", exact: true })).toBeVisible();
    await expect(page.getByLabel("Research name")).toHaveValue("Signals browser Draft");

    const protectedDefault = await page.request.delete("/api/research-folders/folder_default", {
      headers: sameOriginHeaders(),
    });
    expect(protectedDefault.status()).toBe(409);
    page.once("dialog", async (dialog) => dialog.dismiss());
    await page.getByRole("button", { name: "Delete Folder" }).click();
    await expect(page.getByRole("link", { name: "Momentum", exact: true })).toBeVisible();
    page.once("dialog", async (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Delete Folder" }).click();
    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByRole("link", { name: "Momentum", exact: true })).toHaveCount(0);
    expect(await page.evaluate(
      ({ folderId, activeResearcherId }) => localStorage.getItem(
        `thesistrace.research-draft.${activeResearcherId}.${folderId}`,
      ),
      { folderId: customFolderId, activeResearcherId: researcher.id },
    )).toBeNull();

    const folderRead = await page.request.get("/api/research-folders");
    expect(folderRead.ok()).toBeTruthy();
    expect((await folderRead.json()).items).toMatchObject([
      { id: "folder_default", name: "Default", is_default: true },
      {
        id: "folder_batch_research",
        name: "Batch Research",
        is_default: false,
      },
    ]);
    expect(responses.some((entry) => entry.includes("/api/definitions"))).toBe(false);
    expect(externalRequests, "browser journey must remain local-only").toEqual([]);
  } finally {
    await attachResponses(testInfo, responses);
  }
});

test("Financial catalog composes one Formula and starts its DailyTrack", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const responses: string[] = [];
  let runId: string | undefined;
  let trackId: string | undefined;
  let workerPaused = false;
  let controlledWorker: ChildProcess | undefined;
  page.on("response", (response) => {
    if (response.url().includes("/api/")) {
      responses.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });

  try {
    controlWorker("pause");
    workerPaused = true;
    await page.goto("/data");
    await expect(page.getByRole("heading", { name: "Research fields" })).toBeVisible();
    await expect(page.getByText("revenue", { exact: true })).toBeVisible();
    await expect(page.getByText("Latest full year visible on each Research Session").first()).toBeVisible();
    await page.goto("/research?new");
    await fillCompleteDraft(page, {
      name: "Composite financial browser run",
      formula: "rank(close) + rank(revenue)",
    });
    const runCapture = page.waitForResponse((response) => (
      response.url().endsWith("/api/research-runs")
      && response.request().method() === "POST"
    ));
    await page.getByRole("button", { name: "Run research", exact: true }).click();
    const acceptedRun = await runCapture;
    expect(acceptedRun.status()).toBe(202);
    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
    runId = new URL(page.url()).pathname.split("/").at(-1);
    if (runId === undefined) throw new Error("ResearchRun route has no identity");
    await expect(page.locator(".research-run-facts").getByText(/Status\s+queued/)).toBeVisible();
    const barrier = startControlledResearchRun(runId);
    controlledWorker = barrier.process;
    await barrier.claimed;
    await expect(page.locator(".research-run-facts").getByText(/Status\s+running/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Execution progress" })).toBeVisible();
    await expect(
      page.locator("[aria-label='ResearchRun progress']").getByText(/^Running /),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Name and folder" })).toBeVisible();
    expect(await page.locator("[aria-label='ResearchRun progress']").evaluate(
      (progress) => progress.compareDocumentPosition(
        document.querySelector("[aria-label='Name and folder']")!,
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    )).toBeTruthy();
    controlledWorker.stdin?.end("1");
    await controlledWorkerExit(controlledWorker);
    controlledWorker = undefined;
    await expect(page.locator(".research-run-facts").getByText(/Status\s+succeeded/)).toBeVisible({
      timeout: 90_000,
    });
    const comparisonChartLabel = "Net Strategy and CSI 300 performance chart";
    const performanceChart = page.getByLabel(comparisonChartLabel, { exact: true });
    await expect(performanceChart).toBeVisible();
    await expect(performanceChart.locator("canvas").first()).toBeVisible();
    await expect(performanceChart.getByText("Net Strategy", { exact: true })).toBeVisible();
    await expect(performanceChart.getByText("CSI 300", { exact: true })).toBeVisible();
    await expect(performanceChart.getByText("Net Excess", { exact: true })).toHaveCount(0);
    await expect(
      performanceChart.getByRole("link", { name: "TradingView Lightweight Charts™" }),
    ).toHaveAttribute("href", "https://www.tradingview.com/");
    await expect(performanceChart.locator("#tv-attr-logo")).toHaveCount(0);
    await performanceChart.getByRole("button", { name: "1Y" }).click();
    await expect(performanceChart.getByRole("button", { name: "1Y" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await performanceChart.getByRole("button", { name: "All" }).click();
    const canvasBounds = await performanceChart.locator(".strategy-chart-canvas").boundingBox();
    if (canvasBounds === null) throw new Error("Strategy chart has no browser bounds");
    await page.mouse.move(
      canvasBounds.x + (canvasBounds.width * 0.6),
      canvasBounds.y + (canvasBounds.height * 0.5),
    );
    const performanceReadout = performanceChart.locator(".strategy-chart-readout");
    await expect(performanceReadout).toContainText("Net Strategy");
    await expect(performanceReadout).toContainText("CSI 300");
    await expect(performanceReadout).not.toContainText("Net Excess");

    const runDetailPath = `**/api/research-runs/${runId}`;
    await page.route(runDetailPath, async (route) => {
      const response = await route.fetch();
      const body = await response.json() as Record<string, unknown> & {
        result: Record<string, unknown> & {
          strategy: Record<string, unknown>;
        };
      };
      await route.fulfill({
        response,
        json: {
          ...body,
          result: {
            ...body.result,
            strategy: {
              ...body.result.strategy,
              comparison: {
                status: "unavailable",
                reason: "benchmark_snapshot_unavailable",
              },
            },
          },
        },
      });
    });
    await page.reload();
    const unavailableRunComparison = page.getByLabel("CSI 300 Strategy Comparison", {
      exact: true,
    });
    await expect(unavailableRunComparison).toHaveAttribute("role", "status");
    await expect(unavailableRunComparison).toContainText("CSI 300 comparison unavailable");
    await expect(unavailableRunComparison.locator("figure")).toHaveCount(0);
    await expect(page.getByLabel(comparisonChartLabel, { exact: true })).toHaveCount(0);
    await page.unroute(runDetailPath);
    await page.reload();
    await expect(page.getByLabel(comparisonChartLabel, { exact: true })).toBeVisible();
    const terminalProgress = page.locator("[aria-label='ResearchRun progress']");
    await expect(terminalProgress.getByText("Warm-up", { exact: true })).toHaveCount(0);
    await expect(terminalProgress.getByText("Committed chunks", { exact: true })).toHaveCount(0);
    await expect(terminalProgress.getByText("Research sessions", { exact: true })).toBeVisible();
    await expect(terminalProgress.getByText("Started", { exact: true })).toBeVisible();
    await expect(terminalProgress.getByText("Finished", { exact: true })).toBeVisible();
    await expect(terminalProgress.locator("time")).toHaveCount(2);
    await expect(page.getByRole("heading", { name: "Daily Observations" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Provenance" })).toHaveCount(0);
    expect(await page.getByRole("heading", { name: "Strategy Summary" }).evaluate(
      (summary) => summary.compareDocumentPosition(
        document.querySelector("[aria-label='ResearchRun progress']")!,
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    )).toBeTruthy();
    expect(await page.locator("[aria-label='ResearchRun progress']").evaluate(
      (progress) => progress.compareDocumentPosition(
        document.querySelector("[aria-label='Create a draft']")!,
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    )).toBeTruthy();
    controlWorker("unpause");
    workerPaused = false;
    const trackCapture = page.waitForResponse((response) => (
      response.url().endsWith(`/api/research-runs/${runId}/daily-tracks`)
      && response.request().method() === "POST"
    ));
    await page.getByRole("button", { name: "Start Tracking" }).click();
    const acceptedTrack = await trackCapture;
    expect(acceptedTrack.status()).toBe(201);
    await expect(page).toHaveURL(/\/daily-tracks\/track_[a-f0-9]+$/);
    trackId = new URL(page.url()).pathname.split("/").at(-1);
    if (trackId === undefined) throw new Error("DailyTrack route has no identity");
    await expect(page.locator(".research-run-facts").first()).toContainText(
      "Status active",
      { timeout: 30_000 },
    );
    await expect(page.locator(".research-run-facts").first()).toContainText(
      "Advance phase up_to_date",
    );
    const dailyTrackChart = page.getByLabel(comparisonChartLabel, { exact: true });
    await expect(dailyTrackChart).toBeVisible();
    await expect(dailyTrackChart.locator("canvas").first()).toBeVisible();
    await expect(dailyTrackChart.getByText("Net Strategy", { exact: true })).toBeVisible();
    await expect(dailyTrackChart.getByText("CSI 300", { exact: true })).toBeVisible();
    await expect(dailyTrackChart.getByText("Net Excess", { exact: true })).toHaveCount(0);

    const trackDetailPath = `**/api/daily-tracks/${trackId}`;
    await page.route(trackDetailPath, async (route) => {
      const response = await route.fetch();
      const body = await response.json() as Record<string, unknown> & {
        strategy: Record<string, unknown>;
      };
      await route.fulfill({
        response,
        json: {
          ...body,
          strategy: {
            ...body.strategy,
            comparison: {
              status: "unavailable",
              reason: "benchmark_snapshot_unavailable",
            },
          },
        },
      });
    });
    await page.reload();
    const unavailableTrackComparison = page.getByLabel("CSI 300 Strategy Comparison", {
      exact: true,
    });
    await expect(unavailableTrackComparison).toHaveAttribute("role", "status");
    await expect(unavailableTrackComparison).toContainText("CSI 300 comparison unavailable");
    await expect(unavailableTrackComparison.locator("figure")).toHaveCount(0);
    await expect(page.getByLabel(comparisonChartLabel, { exact: true })).toHaveCount(0);
    await page.unroute(trackDetailPath);
    await page.reload();
    await expect(page.getByLabel(comparisonChartLabel, { exact: true })).toBeVisible();

    publishFinancialTrackHead("lagged");
    await page.getByRole("button", { name: "Reload status" }).click();
    const refreshTrack = page.getByRole("button", { name: "Refresh to latest data" });
    await expect(refreshTrack).toBeEnabled();
    await refreshTrack.click();
    await expect.poll(async () => (
      (await (await page.request.get(`/api/daily-tracks/${trackId}`)).json() as { status: string }).status
    ), { timeout: 90_000 }).toBe("blocked");
    await page.getByRole("button", { name: "Reload status" }).click();
    await expect(page.locator(".research-run-facts").first()).toContainText("Status blocked");
    await expect(page.locator(".research-run-facts").first()).toContainText(
      "Advance phase blocked",
    );
    await expect(page.locator(".research-run-facts").first()).toContainText(
      "Frozen target",
    );
    await expect(page.getByText("Financial Coverage ends before the next Research Session.")).toBeVisible();

    publishFinancialTrackHead("recovered");
    const recoveredData = await page.request.get("/api/data");
    expect(recoveredData.status()).toBe(200);
    expect(await recoveredData.json()).toMatchObject({
      data_through_session: "2026-08-11",
      financial_research_readiness: "ready",
    });
    await page.getByRole("button", { name: "Retry blocked target" }).click();
    await expect.poll(async () => {
      const response = await page.request.get(`/api/daily-tracks/${trackId}`);
      const track = await response.json() as { status: string; strategy_session: string };
      return `${track.status}:${track.strategy_session}`;
    }, { timeout: 90_000 }).toBe("active:2026-08-06");
    await expect(refreshTrack).toBeEnabled();
    await refreshTrack.click();
    await expect.poll(async () => {
      const response = await page.request.get(`/api/daily-tracks/${trackId}`);
      return ((await response.json()) as { strategy_session: string }).strategy_session;
    }, { timeout: 90_000 }).toBe("2026-08-11");
    await page.getByRole("button", { name: "Reload status" }).click();
    await expect(page.locator(".research-run-facts").first()).toContainText("Status active");
    await expect(page.locator(".research-run-facts").first()).toContainText("Strategy session 2026-08-11");
  } finally {
    const cleanupErrors: unknown[] = [];
    const cleanup = async (action: () => void | Promise<void>) => {
      try {
        await action();
      } catch (error) {
        cleanupErrors.push(error);
      }
    };
    try {
      await cleanup(() => {
        if (workerPaused) controlWorker("unpause");
        workerPaused = false;
      });
      await cleanup(async () => {
        if (controlledWorker !== undefined) {
          controlledWorker.kill("SIGTERM");
          await controlledWorkerExit(controlledWorker, true);
          controlledWorker = undefined;
        }
      });
      await cleanup(async () => {
        if (trackId === undefined) return;
        const stop = await page.request.post(`/api/daily-tracks/${trackId}/stop`, {
          data: { request_id: `financial-e2e-stop-${trackId}` },
          headers: sameOriginHeaders(),
        });
        expect(stop.status()).toBe(202);
      });
      await cleanup(async () => {
        if (trackId === undefined) return;
        expect((await page.request.delete(`/api/daily-tracks/${trackId}`, {
          headers: sameOriginHeaders(),
        })).status()).toBe(204);
      });
      let runStatus: string | undefined;
      await cleanup(async () => {
        if (runId === undefined) return;
        const detail = await page.request.get(`/api/research-runs/${runId}`);
        if (detail.status() === 404) return;
        expect(detail.status()).toBe(200);
        runStatus = ((await detail.json()) as { status: string }).status;
      });
      await cleanup(async () => {
        if (runId === undefined || (runStatus !== "queued" && runStatus !== "running")) return;
        const cancel = await page.request.post(`/api/research-runs/${runId}/cancel`, {
          data: { request_id: `financial-e2e-cancel-${runId}` },
          headers: sameOriginHeaders(),
        });
        expect(cancel.status()).toBe(200);
        await expect.poll(async () => {
          const detail = await page.request.get(`/api/research-runs/${runId}`);
          if (detail.status() === 404) return "deleted";
          return ((await detail.json()) as { status: string }).status;
        }, { timeout: 20_000 }).toMatch(/^(cancelled|failed|succeeded|deleted)$/);
      });
      await cleanup(async () => {
        if (runId === undefined) return;
        const deleted = await page.request.delete(`/api/research-runs/${runId}`, {
          headers: sameOriginHeaders(),
        });
        expect([204, 404]).toContain(deleted.status());
      });
      if (cleanupErrors.length > 0) throw new AggregateError(cleanupErrors, "E2E cleanup failed");
    } finally {
      await attachResponses(testInfo, responses);
    }
  }
});

test("running Research cancellation stays visible until the child exits", async ({ page }) => {
  test.setTimeout(90_000);
  let workerPaused = false;
  let controlledWorker: ChildProcess | undefined;
  try {
    controlWorker("pause");
    workerPaused = true;
    await page.goto("/research?new");
    await fillCompleteDraft(page, {
      name: "Confirmed browser cancellation",
      formula: "ts_mean(close, 2)",
    });
    await page.getByRole("button", { name: "Run research", exact: true }).click();
    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
    const runId = page.url().split("/").at(-1);
    if (runId === undefined) throw new Error("ResearchRun route has no identity");

    const barrier = startControlledResearchRun(runId);
    controlledWorker = barrier.process;
    await barrier.claimed;
    await expect(page.locator(".research-run-facts").getByText(/Status\s+running/)).toBeVisible();

    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.locator(".research-run-facts").getByText(/Status\s+cancelling/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Create draft" })).toBeVisible();

    controlledWorker.stdin?.end("1");
    await controlledWorkerExit(controlledWorker);
    controlledWorker = undefined;
    await expect(page.locator(".research-run-facts").getByText(/Status\s+cancelled/)).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByRole("button", { name: "Create draft" })).toBeVisible();
    await confirmResearchDeletion(page);
    await expect(page).toHaveURL(/\/research-runs$/);
  } finally {
    if (controlledWorker !== undefined) {
      controlledWorker.kill("SIGTERM");
      await controlledWorkerExit(controlledWorker, true);
    }
    if (workerPaused) controlWorker("unpause");
  }
});

test("Batch children keep ordinary Research organization, reuse, tracking, and deletion", async ({ page }) => {
  test.setTimeout(240_000);
  const admitted = await page.request.post("/api/research-batches", {
    data: {
      request_id: "browser-batch-ordinary-research",
      batch_kind: "strategy_sweep",
      start_date: "2026-08-04",
      end_date: "2026-08-05",
      universe: "top300",
      neutralization: "none",
      alpha: { formula: "close", hypothesis: "Browser Batch hypothesis" },
      strategies: [
        {
          item_key: "browser-focused",
          name: "Browser Batch Focused",
          holdings_count: 10,
          rebalance_every_sessions: 1,
        },
        {
          item_key: "browser-broad",
          name: "Browser Batch Broad",
          holdings_count: 20,
          rebalance_every_sessions: 2,
        },
      ],
    },
    headers: sameOriginHeaders(),
  });
  expect(admitted.status()).toBe(202);
  const admittedBatch = await admitted.json() as {
    id: string;
    items: Array<{ research_run_id: string }>;
  };
  const [firstRunId, siblingRunId] = admittedBatch.items.map((item) => item.research_run_id);
  if (firstRunId === undefined || siblingRunId === undefined) {
    throw new Error("Browser Batch did not admit two child Runs");
  }

  await expect.poll(async () => {
    const response = await page.request.get(`/api/research-batches/${admittedBatch.id}`);
    return ((await response.json()) as { status: string }).status;
  }, { timeout: 90_000 }).toBe("succeeded");

  await page.goto("/research-runs");
  await expect(page.getByRole("link", { name: "Browser Batch Focused" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Browser Batch Broad" })).toBeVisible();
  await page.getByRole("link", { name: "Browser Batch Focused" }).click();
  await expect(page).toHaveURL(new RegExp(`/research-runs/${firstRunId}$`));
  await expect(page.locator(".research-run-facts")).toContainText("Status succeeded");
  await expect(page.getByRole("button", { name: "Create draft" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Batch/, exact: true })).toHaveCount(0);

  const folderResponse = await page.request.post("/api/research-folders", {
    data: { name: "Browser Batch Review" },
    headers: sameOriginHeaders(),
  });
  expect(folderResponse.status()).toBe(201);
  const folderId = ((await folderResponse.json()) as { id: string }).id;
  await page.reload();
  await page.getByLabel("Research name", { exact: true }).fill("Reviewed Batch Child");
  await page.getByLabel("Folder", { exact: true }).selectOption(folderId);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.locator(".research-run-facts")).toContainText("Reviewed Batch Child");

  const organizedBatch = await page.request.get(`/api/research-batches/${admittedBatch.id}`);
  expect(((await organizedBatch.json()) as {
    items: Array<{ research_run_id: string }>;
  }).items.map((item) => item.research_run_id)).toEqual([firstRunId, siblingRunId]);

  await page.getByLabel("Target Folder").selectOption(folderId);
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page).toHaveURL(new RegExp(`/research\\?folder=${folderId}$`));
  await expect(page.getByRole("radio", { name: /Strategy Backtest/ })).toBeChecked();
  await expect(page.locator(".cm-content")).toHaveText("close");
  await expect(page.getByLabel("Notes")).toHaveValue("Browser Batch hypothesis");
  await expect(page.getByLabel("Holdings count")).toHaveValue("10");
  await expect(page.getByLabel("Rebalance sessions")).toHaveValue("1");
  expect((await page.request.get(`/api/research-runs/${firstRunId}`)).status()).toBe(200);

  await page.goto(`/research-runs/${firstRunId}`);
  await page.getByRole("button", { name: "Start Tracking" }).click();
  await expect(page).toHaveURL(/\/daily-tracks\/track_[a-f0-9]+$/);
  const trackId = page.url().split("/").at(-1);
  if (trackId === undefined) throw new Error("Batch child DailyTrack route has no identity");

  await page.goto(`/research-runs/${firstRunId}`);
  await confirmResearchDeletion(page);
  await expect(page).toHaveURL(/\/research-runs$/);
  const firstDeleted = await page.request.get(`/api/research-batches/${admittedBatch.id}`);
  const firstDeletedBatch = await firstDeleted.json() as {
    status: string;
    items: Array<{ research_run_id: string; run_availability: string; outcome: string }>;
  };
  expect(firstDeletedBatch.status).toBe("succeeded");
  expect(firstDeletedBatch.items).toMatchObject([
    { research_run_id: firstRunId, run_availability: "deleted", outcome: "succeeded" },
    { research_run_id: siblingRunId, run_availability: "available", outcome: "succeeded" },
  ]);
  expect((await page.request.get(`/api/research-runs/${siblingRunId}`)).status()).toBe(200);
  expect((await page.request.get(`/api/daily-tracks/${trackId}`)).status()).toBe(200);

  await page.goto(`/research-runs/${siblingRunId}`);
  await confirmResearchDeletion(page);
  await expect(page).toHaveURL(/\/research-runs$/);
  const finalBatch = await page.request.get(`/api/research-batches/${admittedBatch.id}`);
  expect(((await finalBatch.json()) as {
    items: Array<{ run_availability: string }>;
  }).items.map((item) => item.run_availability)).toEqual(["deleted", "deleted"]);

  await page.goto(`/daily-tracks/${trackId}`);
  await expect(page.getByText(`${firstRunId} (deleted)`, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Stop DailyTrack" }).click();
  await expect(page.locator(".research-run-facts").first()).toContainText(
    "Status stopped",
    { timeout: 90_000 },
  );
  page.once("dialog", async (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete DailyTrack" }).click();
  expect((await page.request.delete(`/api/research-folders/${folderId}`, {
    headers: sameOriginHeaders(),
  })).status()).toBe(204);
});

test("Default and custom Folder Drafts run once, retain edits, reject safely, and publish results", async ({ page, researcher }, testInfo) => {
  test.setTimeout(120_000);
  const defaultDraftKey = `thesistrace.research-draft.${researcher.id}.folder_default`;
  const responses: string[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/")) {
      responses.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });

  try {
    publishFinancialTrackHead("lagged");
    const currentData = await page.request.get("/api/data");
    expect(currentData.status()).toBe(200);
    expect(await currentData.json()).toMatchObject({
      data_through_session: "2026-08-11",
    });
    await page.goto("/research?new");
    await expect(page).toHaveURL(/\/research$/);
    await fillCompleteDraft(page, {
      name: "Duplicate Name",
      formula: "ts_mean(close, 2)",
    });

    const commands: Array<Record<string, unknown>> = [];
    let releaseSecond: ((route: Route) => void) | undefined;
    const secondRequest = new Promise<Route>((resolve) => { releaseSecond = resolve; });
    await page.route("**/api/research-runs", async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      commands.push(route.request().postDataJSON() as Record<string, unknown>);
      if (commands.length === 1) {
        await route.abort("failed");
        return;
      }
      releaseSecond?.(route);
    });

    await page.getByRole("button", { name: "Run research", exact: true }).click();
    await expect(page.getByRole("list", { name: "Run issues" })).toContainText("RUN_UNAVAILABLE");
    await page.getByRole("button", { name: "Run research", exact: true }).click();
    const heldRoute = await secondRequest;
    expect(commands).toHaveLength(2);
    expect(commands[1].request_id).toBe(commands[0].request_id);
    expect(commands[1].formula).toBe("ts_mean(close, 2)");
    expect(commands[1]).toMatchObject({
      research_kind: "strategy_backtest",
      holdings_count: 10,
      rebalance_every_sessions: 2,
    });
    await expect(
      page.locator(".research-workspace-header").getByRole("button", { name: "New research" }),
    ).toBeDisabled();

    await replaceFormula(page, "ts_mean(close, 3)");
    await heldRoute.continue();
    await page.unroute("**/api/research-runs");

    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
    const defaultRunId = page.url().split("/").at(-1);
    expect(defaultRunId).toMatch(/^run_[a-f0-9]+$/);
    await expect(page.locator(".research-run-facts").getByText(/Status\s+succeeded/)).toBeVisible({ timeout: 90_000 });
    await expect(page.getByRole("heading", { name: "Execution progress" })).toBeVisible();
    await expect(
      page.locator(".research-run-progress-stats > div").filter({ hasText: "Research" }),
    ).toContainText("2 / 2");
    await expect(page.locator("body")).not.toContainText(/checkpoint|staged payload/i);
    await expect(page.getByRole("heading", { name: "Strategy Summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Final Portfolio" })).toHaveCount(0);
    await expect(page.getByText("Retained account at the Research Period boundary", { exact: true })).toHaveCount(0);
    await expect(page.getByText("No pending signal at this boundary.", { exact: true })).toHaveCount(0);
    await expect(page.locator(".research-run-facts")).toContainText("Research type Strategy Backtest");
    const strategyConditions = page.getByRole("group", { name: "Research execution conditions" });
    await expect(strategyConditions).toContainText("Universe Top 300");
    await expect(strategyConditions).toContainText("Neutralization None");
    await expect(strategyConditions).toContainText("Holdings count 10");
    await expect(strategyConditions).toContainText("Rebalance Every 2 sessions");
    await expect(page.getByRole("button", { name: "Refresh" })).toHaveCount(0);

    const retainedAfterRun = await page.evaluate((draftKey) => JSON.parse(
      localStorage.getItem(draftKey) ?? "null",
    ), defaultDraftKey);
    expect(retainedAfterRun).toMatchObject({
      formula: "ts_mean(close, 3)",
      lastAdmittedBaseline: { formula: "ts_mean(close, 2)" },
      pendingAdmission: null,
    });
    await page.reload();
    await expect(page.getByRole("heading", { name: "Strategy Summary" })).toBeVisible();

    const acceptedHistory = await page.request.get("/api/research-runs");
    expect(acceptedHistory.ok()).toBeTruthy();
    const acceptedItems = (await acceptedHistory.json()).items as Array<{ id: string }>;

    await page.goto("/research");
    await expect(page.locator(".cm-content")).toHaveText("ts_mean(close, 3)");
    await replaceFormula(page, "unknown_field");
    await page.getByRole("button", { name: "Run research", exact: true }).click();
    await expect(page.getByRole("list", { name: "Run issues" })).toContainText("UNKNOWN_IDENTIFIER");
    await expect(page.locator(".cm-lintRange-error")).toHaveCount(1);
    const rejectedHistory = await page.request.get("/api/research-runs");
    expect(((await rejectedHistory.json()).items as unknown[])).toHaveLength(acceptedItems.length);
    await page.reload();
    await expect(page.locator(".cm-content")).toHaveText("unknown_field");

    await openResearchFolderMenu(page);
    await page.getByLabel("New Folder").fill("Signals");
    await page.getByRole("button", { name: "Create Folder" }).click();
    await expect(page).toHaveURL(/\/research\?folder=folder_[a-f0-9]+$/);
    const customFolderId = new URL(page.url()).searchParams.get("folder");
    expect(customFolderId).toMatch(/^folder_[a-f0-9]+$/);
    if (customFolderId === null) throw new Error("Custom Folder route is missing folder id");
    await fillCompleteDraft(page, {
      name: "Duplicate Name",
      formula: "close",
      researchKind: "factor_evaluation",
    });
    await page.getByRole("button", { name: "Run research", exact: true }).click();
    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
    const customRunId = page.url().split("/").at(-1);
    if (customRunId === undefined) throw new Error("Custom Research route is missing run id");
    await expect(page.locator(".research-run-facts").getByText(/Status\s+succeeded/)).toBeVisible({ timeout: 90_000 });
    await expect(page.locator(".research-run-facts")).toContainText("Research type Factor Evaluation");
    const factorConditions = page.getByRole("group", { name: "Research execution conditions" });
    await expect(factorConditions).toContainText("Universe Top 300");
    await expect(factorConditions).toContainText("Neutralization None");
    await expect(factorConditions.getByText("Holdings count", { exact: true })).toHaveCount(0);
    await expect(factorConditions.getByText("Rebalance", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Factor Summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Strategy Summary" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Daily Observations" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Final Portfolio" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Start Tracking" })).toHaveCount(0);
    for (const horizon of [1, 5, 20]) {
      const section = page.getByRole("region", { name: `${horizon}-session Factor` });
      await expect(section.getByText("Rank IC", { exact: true })).toBeVisible();
      await expect(section.getByText("Rank ICIR", { exact: true })).toBeVisible();
      await expect(section.getByText("IC", { exact: true })).toBeVisible();
      await expect(section.getByText("ICIR", { exact: true })).toBeVisible();
      await expect(section.getByText(/Rank IC coverage/)).toBeVisible();
      await expect(section.getByText(/^IC coverage/)).toBeVisible();
    }
    const customDetail = await page.request.get(`/api/research-runs/${customRunId}`);
    expect(await customDetail.json()).toMatchObject({
      folder_id: customFolderId,
      research_kind: "factor_evaluation",
      result: { provenance: { research_kind: "factor_evaluation" } },
    });

    const factorHistoryBeforeReuse = await page.request.get("/api/research-runs");
    const factorHistoryCount = ((await factorHistoryBeforeReuse.json()).items as unknown[]).length;
    await page.getByLabel("Target Folder").selectOption("folder_default");
    page.once("dialog", async (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Create draft" }).click();
    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByRole("radio", { name: /Factor Evaluation/ })).toBeChecked();
    await expect(page.getByLabel("Holdings count")).toHaveCount(0);
    await expect(page.getByLabel("Rebalance sessions")).toHaveCount(0);
    const factorHistoryAfterReuse = await page.request.get("/api/research-runs");
    expect(((await factorHistoryAfterReuse.json()).items as unknown[])).toHaveLength(factorHistoryCount);

    await page.getByRole("radio", { name: /Strategy Backtest/ }).check();
    await expect(page.getByRole("button", { name: "Run research", exact: true })).toBeDisabled();
    await page.getByLabel("Research name").fill("Converted Factor Strategy");
    await page.getByLabel("Holdings count").fill("10");
    await page.getByLabel("Rebalance sessions").fill("2");
    await page.getByRole("button", { name: "Run research", exact: true }).click();
    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
    const convertedRunId = page.url().split("/").at(-1);
    expect(convertedRunId).not.toBe(customRunId);
    if (convertedRunId === undefined) throw new Error("Converted Research route is missing run id");
    await expect(page.locator(".research-run-facts").getByText(/Status\s+succeeded/)).toBeVisible({ timeout: 90_000 });
    await expect(page.locator(".research-run-facts")).toContainText("Research type Strategy Backtest");
    await expect(page.getByRole("heading", { name: "Strategy Summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Daily Observations" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Final Portfolio" })).toHaveCount(0);
    const convertedDetail = await page.request.get(`/api/research-runs/${convertedRunId}`);
    expect(await convertedDetail.json()).toMatchObject({
      id: convertedRunId,
      folder_id: "folder_default",
      research_kind: "strategy_backtest",
      input: {
        research_kind: "strategy_backtest",
        holdings_count: 10,
        rebalance_every_sessions: 2,
      },
    });
    await page.goto(`/research-runs/${customRunId}`);

    const draftsBeforeOrganization = await page.evaluate(() => Object.fromEntries(
      Object.entries(localStorage).filter(([key]) => key.startsWith("thesistrace.research-draft.")),
    ));
    let releaseOrganization: ((route: Route) => void) | undefined;
    const heldOrganization = new Promise<Route>((resolve) => { releaseOrganization = resolve; });
    await page.route(`**/api/research-runs/${customRunId}`, async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.continue();
        return;
      }
      releaseOrganization?.(route);
    });
    await page.getByLabel("Research name", { exact: true }).fill("Renamed Research");
    await page.getByRole("button", { name: "Save changes" }).click();
    const heldOrganizationRoute = await heldOrganization;
    await expect(page.getByLabel("Research name", { exact: true })).toBeDisabled();
    await expect(page.getByLabel("Folder", { exact: true })).toBeDisabled();
    await heldOrganizationRoute.continue();
    await page.unroute(`**/api/research-runs/${customRunId}`);
    await expect(page.locator(".research-run-facts")).toContainText("Renamed Research");
    await page.getByLabel("Research name", { exact: true }).fill("Duplicate Name");
    await page.getByLabel("Folder", { exact: true }).selectOption("folder_default");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.locator(".research-run-facts")).toContainText("Duplicate Name");
    const organizedDetail = await page.request.get(`/api/research-runs/${customRunId}`);
    expect(await organizedDetail.json()).toMatchObject({
      id: customRunId,
      name: "Duplicate Name",
      folder_id: "folder_default",
      status: "succeeded",
    });
    expect(await page.evaluate(() => Object.fromEntries(
      Object.entries(localStorage).filter(([key]) => key.startsWith("thesistrace.research-draft.")),
    ))).toEqual(draftsBeforeOrganization);
    await expect(page.getByRole("heading", { name: "Factor Summary" })).toBeVisible();

    await page.goto("/research-runs");
    await expect(page.getByText("Research history", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Sort by a metric heading to compare Runs.", { exact: true })).toHaveCount(0);
    const researchRunsTable = page.getByRole("table", { name: "Research Runs" });
    await expect(page.getByRole("link", { name: "Duplicate Name" })).toHaveCount(2);
    await expect(page.getByText(defaultRunId ?? "missing-default-run-id", { exact: true })).toHaveCount(0);
    await expect(page.getByText(customRunId, { exact: true })).toHaveCount(0);
    await expect(page.getByText("ts_mean(close, 2)", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("columnheader", { name: "Result summary" })).toBeVisible();
    await expect(page.getByText("1S Rank IC", { exact: true })).toHaveCount(1);
    await expect(page.getByText("Excess", { exact: true })).toHaveCount(2);
    await expect(researchRunsTable.getByText("Factor Evaluation", { exact: true })).toHaveCount(1);
    await expect(researchRunsTable.getByText("Strategy Backtest", { exact: true })).toHaveCount(2);
    await expect(page.getByLabel("Filter by Type")).toHaveValue("");
    await expect(page.getByRole("navigation", { name: "Research Runs pages" })).toContainText("Page 1");
    await page.getByLabel("Filter by Type").selectOption("factor_evaluation");
    await expect(researchRunsTable.getByText("Factor Evaluation", { exact: true })).toHaveCount(1);
    await expect(researchRunsTable.getByText("Strategy Backtest", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("columnheader", { name: "1-session Rank IC" })).toBeVisible();
    await page.getByLabel("Filter by Type").selectOption("strategy_backtest");
    await expect(researchRunsTable.getByText("Strategy Backtest", { exact: true })).toHaveCount(2);
    await expect(page.getByRole("columnheader", { name: "Annualized excess" })).toBeVisible();
    await page.getByLabel("Filter by Type").selectOption("");
    await page.getByLabel("Filter by Folder").selectOption(customFolderId);
    await expect(page.getByText("No Research Runs match these filters.")).toBeVisible();
    await page.getByLabel("Filter by Folder").selectOption("folder_default");
    await expect(page.getByRole("link", { name: "Duplicate Name" })).toHaveCount(2);

    let folderRequestCount = 0;
    await page.route("**/api/research-folders", async (route) => {
      folderRequestCount += 1;
      if (folderRequestCount === 1) {
        await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
        return;
      }
      await route.continue();
    });
    await page.goto("/research-runs");
    await expect(page.getByRole("link", { name: "Duplicate Name" })).toHaveCount(2);
    await expect(page.getByRole("alert")).toHaveText("Research Folders unavailable");
    await page.getByRole("button", { name: "Retry Folders" }).click();
    await expect(page.getByLabel("Filter by Folder")).toBeVisible();
    expect(folderRequestCount).toBe(2);
    await page.unroute("**/api/research-folders");

    await page.goto(`/research?folder=${customFolderId}`);
    await expect(page.locator(".cm-content")).toHaveText("close");
    await page.getByLabel("Research name").fill("Target Local Name");
    await page.goto(`/research-runs/${defaultRunId}`);
    await expect(page.getByRole("button", { name: "Create draft" })).toBeVisible();
    const sourceBeforeReuseResponse = await page.request.get(`/api/research-runs/${defaultRunId}`);
    const sourceBeforeReuse = await sourceBeforeReuseResponse.json();
    const historyBeforeReuse = await page.request.get("/api/research-runs");
    const historyCountBeforeReuse = ((await historyBeforeReuse.json()).items as unknown[]).length;
    await page.getByLabel("Target Folder").selectOption(customFolderId);
    await page.getByRole("button", { name: "Create draft" }).click();
    await expect(page).toHaveURL(new RegExp(`/research\\?folder=${customFolderId}$`));
    await expect(page.getByLabel("Research name")).toHaveValue("Target Local Name");
    await expect(page.locator(".cm-content")).toHaveText("ts_mean(close, 2)");
    await expect(page.getByLabel("Notes")).toHaveValue("Browser Run acceptance.");
    await expect(page.getByLabel("Research start date")).toHaveValue("2026-08-04");
    await expect(page.getByLabel("Research end date")).toHaveValue("2026-08-05");
    await expect(page.getByLabel("Universe")).toHaveValue("top300");
    await expect(page.getByLabel("Neutralization")).toHaveValue("none");
    await expect(page.getByRole("radio", { name: /Strategy Backtest/ })).toBeChecked();
    await expect(page.getByLabel("Holdings count")).toHaveValue("10");
    await expect(page.getByLabel("Rebalance sessions")).toHaveValue("2");
    const historyAfterCopy = await page.request.get("/api/research-runs");
    expect(((await historyAfterCopy.json()).items as unknown[])).toHaveLength(historyCountBeforeReuse);

    await replaceFormula(page, "ts_mean(close, 2) + 1");
    await page.getByRole("button", { name: "Run research", exact: true }).click();
    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
    const reusedRunId = page.url().split("/").at(-1);
    expect(reusedRunId).not.toBe(defaultRunId);
    await expect(page.locator(".research-run-facts").getByText(/Status\s+succeeded/)).toBeVisible({ timeout: 90_000 });
    const reusedDetail = await page.request.get(`/api/research-runs/${reusedRunId}`);
    expect(await reusedDetail.json()).toMatchObject({
      id: reusedRunId,
      folder_id: customFolderId,
      name: "Target Local Name",
      input: { formula: "ts_mean(close, 2) + 1" },
    });
    const sourceAfterReuse = await page.request.get(`/api/research-runs/${defaultRunId}`);
    expect(await sourceAfterReuse.json()).toEqual(sourceBeforeReuse);
    await expectRemovedAuthoringControlsToBeAbsent(page);

    let releaseStartTracking: ((route: Route) => void) | undefined;
    const heldStartTracking = new Promise<Route>((resolve) => {
      releaseStartTracking = resolve;
    });
    const startTrackingPath = `**/api/research-runs/${reusedRunId}/daily-tracks`;
    await page.route(startTrackingPath, async (route) => {
      releaseStartTracking?.(route);
    });
    await page.getByRole("button", { name: "Start Tracking" }).click();
    const heldStartTrackingRoute = await heldStartTracking;
    await expect(page.getByRole("button", { name: "Delete Research" })).toBeDisabled();
    await heldStartTrackingRoute.continue();
    await page.unroute(startTrackingPath);
    await expect(page).toHaveURL(/\/daily-tracks\/track_[a-f0-9]+$/);
    const trackId = page.url().split("/").at(-1);
    expect(trackId).toMatch(/^track_[a-f0-9]+$/);
    if (trackId === undefined) throw new Error("DailyTrack route is missing track id");
    const sourceRunLink = page.getByRole("link", { name: reusedRunId, exact: true });
    await expect(sourceRunLink).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete DailyTrack" })).toHaveCount(0);
    const refreshTrack = page.getByRole("button", { name: "Refresh to latest data" });
    await expect(refreshTrack).toBeEnabled();
    // Clicking only dispatches the request; navigation must wait for admission.
    const refreshAccepted = page.waitForResponse((response) => (
      new URL(response.url()).pathname === `/api/daily-tracks/${trackId}/refresh`
      && response.request().method() === "POST"
    ));
    await refreshTrack.click();
    const refreshResponse = await refreshAccepted;
    expect(refreshResponse.status()).toBe(202);
    expect(await refreshResponse.finished()).toBeNull();

    let injectedDetailFailures = 0;
    const reusedRunPath = `**/api/research-runs/${reusedRunId}`;
    await page.route(reusedRunPath, async (route) => {
      if (route.request().method() === "GET" && injectedDetailFailures === 0) {
        injectedDetailFailures += 1;
        await route.fulfill({ json: { detail: "Authentication unavailable" }, status: 503 });
        return;
      }
      await route.continue();
    });
    await sourceRunLink.click();
    await expect(page).toHaveURL(new RegExp(`/research-runs/${reusedRunId}$`));
    await expect(page.getByRole("alert")).toHaveText("ResearchRun unavailable");
    expect(injectedDetailFailures).toBe(1);
    await page.unroute(reusedRunPath);
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await expect(page.getByRole("button", { name: "Delete Research", exact: true })).toBeVisible();
    const deleteDialog = await openResearchDeleteDialog(page);
    await deleteDialog.getByRole("button", { name: "Keep Research" }).click();
    await expect(page).toHaveURL(new RegExp(`/research-runs/${reusedRunId}$`));
    expect((await page.request.get(`/api/research-runs/${reusedRunId}`)).status()).toBe(200);
    await confirmResearchDeletion(page);
    await expect(page).toHaveURL(/\/research-runs$/);
    expect((await page.request.get(`/api/research-runs/${reusedRunId}`)).status()).toBe(404);

    await expect.poll(async () => {
      const response = await page.request.get(`/api/daily-tracks/${trackId}`);
      if (!response.ok()) return "unavailable";
      return ((await response.json()) as { strategy_session: string }).strategy_session;
    }, { timeout: 90_000 }).toBe("2026-08-11");
    await page.goto(`/daily-tracks/${trackId}`);
    await expectRemovedAuthoringControlsToBeAbsent(page);
    await expect(page.getByText(`${reusedRunId} (deleted)`, { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: reusedRunId, exact: true })).toHaveCount(0);
    await expect(page.locator(".research-run-facts").first()).toContainText(
      "Strategy session 2026-08-11",
    );
    await expect(page.getByRole("button", { name: "Delete DailyTrack" })).toHaveCount(0);

    await page.getByRole("button", { name: "Stop DailyTrack" }).click();
    await expect(page.locator(".research-run-facts").first()).toContainText("Status stopped");
    const deleteTrackButton = page.getByRole("button", { name: "Delete DailyTrack" });
    await expect(deleteTrackButton).toBeVisible();
    page.once("dialog", async (dialog) => dialog.dismiss());
    await deleteTrackButton.click();
    await expect(page).toHaveURL(new RegExp(`/daily-tracks/${trackId}$`));
    expect((await page.request.get(`/api/daily-tracks/${trackId}`)).status()).toBe(200);
    page.once("dialog", async (dialog) => dialog.accept());
    await deleteTrackButton.click();
    await expect(page).toHaveURL(/\/daily-tracks$/);
    expect((await page.request.get(`/api/daily-tracks/${trackId}`)).status()).toBe(404);
    await expect(page.getByText("No DailyTracks yet.")).toBeVisible();
  } finally {
    await attachResponses(testInfo, responses);
  }
});

async function openResearchDeleteDialog(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Delete Research", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Delete Research?" });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function confirmResearchDeletion(page: Page): Promise<void> {
  const dialog = await openResearchDeleteDialog(page);
  await dialog.getByRole("button", { name: "Delete Research", exact: true }).click();
}

async function fillCompleteDraft(
  page: Page,
  values: {
    name: string;
    formula: string;
    researchKind?: "factor_evaluation" | "strategy_backtest";
  },
): Promise<void> {
  const researchKind = values.researchKind ?? "strategy_backtest";
  await page.getByRole("radio", {
    name: researchKind === "factor_evaluation" ? /Factor Evaluation/ : /Strategy Backtest/,
  }).check();
  await page.getByLabel("Research name").fill(values.name);
  await replaceFormula(page, values.formula);
  await page.getByLabel("Notes").fill("Browser Run acceptance.");
  await page.getByLabel("Research start date").fill("2026-08-04");
  await page.getByLabel("Research end date").fill("2026-08-05");
  await page.getByLabel("Universe").selectOption("top300");
  await page.getByLabel("Neutralization").selectOption("none");
  if (researchKind === "strategy_backtest") {
    await page.getByLabel("Holdings count").fill("10");
    await page.getByLabel("Rebalance sessions").fill("2");
  } else {
    await expect(page.getByLabel("Holdings count")).toHaveCount(0);
    await expect(page.getByLabel("Rebalance sessions")).toHaveCount(0);
  }
  await expect(page.getByRole("button", { name: "Run research", exact: true })).toBeEnabled();
}

async function replaceFormula(page: Page, formula: string): Promise<void> {
  const editor = page.locator(".cm-content");
  await editor.click();
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.type(formula);
}

async function openResearchFolderMenu(page: Page): Promise<void> {
  const menu = page.locator(".research-folder-navigation");
  if ((await menu.getAttribute("open")) === null) {
    await menu.locator("summary").click();
  }
}

async function closeResearchFolderMenu(page: Page): Promise<void> {
  const menu = page.locator(".research-folder-navigation");
  if ((await menu.getAttribute("open")) !== null) {
    await menu.locator("summary").click();
  }
}

async function expectRemovedAuthoringControlsToBeAbsent(page: Page): Promise<void> {
  await expect(page.getByRole("link", { name: "Definitions", exact: true })).toHaveCount(0);
  await expect(page.getByText("Revision", { exact: true })).toHaveCount(0);
  for (const name of ["Save", "Refresh", "Rerun", "Add Alpha"]) {
    await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
  }
}

async function attachResponses(testInfo: TestInfo, responses: string[]): Promise<void> {
  await testInfo.attach("api-responses.txt", {
    body: Buffer.from(`${responses.join("\n")}\n`, "utf8"),
    contentType: "text/plain",
  });
}

function testContainer(service: "postgres" | "research-worker"): string {
  const project = process.env.THESISTRACE_TEST_PROJECT_NAME;
  if (!project?.startsWith("thesistrace-test-")) {
    throw new Error("Browser acceptance requires an isolated ThesisTrace Test project");
  }
  return `${project}-${service}-1`;
}

function publishFinancialTrackHead(mode: "lagged" | "recovered"): void {
  execFileSync(
    "uv",
    ["run", "python", "../tests/browser/publish_financial_track_head.py", mode],
    { cwd: process.cwd(), env: process.env, stdio: "pipe" },
  );
}
