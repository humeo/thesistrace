import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";
import { execFileSync, spawn, type ChildProcess } from "node:child_process";

test("Default Folder retains one local Research Draft with authoritative Formula diagnostics", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
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
    await expect(page.getByText("Coverage describes the dataset")).toBeVisible();
    await expectRemovedAuthoringControlsToBeAbsent(page);

    await page.getByRole("link", { name: "New Research", exact: true }).click();
    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByRole("heading", { name: "Research", exact: true })).toBeVisible();
    await expect(page.getByText("Default Folder")).toBeVisible();
    await expect(page.getByLabel("Research name")).toHaveValue("");
    await expect(page.locator(".cm-content")).toHaveText("");
    await expectRemovedAuthoringControlsToBeAbsent(page);

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
    await page.keyboard.type("ts_mean(close_adj, 2)");
    await expect(page.getByText("Valid formula", { exact: true })).toBeVisible();
    await page.getByLabel("Hypothesis").fill("Short rolling mean retains signal.");
    await page.getByLabel("Research start date").fill("2026-08-03");
    await page.getByLabel("Research end date").fill("2026-08-05");
    await page.getByLabel("Universe").selectOption("top300");
    await page.getByLabel("Neutralization").selectOption("none");
    await page.getByLabel("Holdings count").fill("10");
    await page.getByLabel("Rebalance sessions").fill("2");

    const browserKeys = await page.evaluate(() => Object.keys(localStorage));
    expect(browserKeys).toEqual(["thesistrace.research-draft.folder_default"]);
    const retainedDraft = await page.evaluate(() => JSON.parse(
      localStorage.getItem("thesistrace.research-draft.folder_default") ?? "null",
    ));
    expect(retainedDraft).toMatchObject({
      name: "Browser Mean Research",
      formula: "ts_mean(close_adj, 2)",
      universe: "top300",
      neutralization: "none",
      holdingsCount: "10",
      rebalanceEverySessions: "2",
      lastAdmittedBaseline: null,
    });

    await page.reload();
    await expect(page.getByLabel("Research name")).toHaveValue("Browser Mean Research");
    await expect(page.locator(".cm-content")).toHaveText("ts_mean(close_adj, 2)");
    await expect(page.getByLabel("Hypothesis")).toHaveValue("Short rolling mean retains signal.");
    await expect(page.getByLabel("Universe")).toHaveValue("top300");

    page.once("dialog", async (dialog) => dialog.dismiss());
    const workspaceNew = page.locator(".research-workspace-header").getByRole("button", { name: "New Research" });
    await workspaceNew.click();
    await expect(page.getByLabel("Research name")).toHaveValue("Browser Mean Research");
    page.once("dialog", async (dialog) => dialog.accept());
    await workspaceNew.click();
    await expect(page.getByLabel("Research name")).toHaveValue("");
    await expect(page.locator(".cm-content")).toHaveText("");
    expect(await page.evaluate(() => localStorage.getItem("thesistrace.research-draft.folder_default"))).toBeNull();

    await page.getByLabel("New Folder").fill("Signals");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/research\?folder=folder_[a-f0-9]+$/);
    const customFolderId = new URL(page.url()).searchParams.get("folder");
    expect(customFolderId).toMatch(/^folder_[a-f0-9]+$/);
    if (customFolderId === null) throw new Error("Custom Folder route is missing folder id");
    await expect(page.getByText("Signals", { exact: true }).first()).toBeVisible();
    await page.getByLabel("Research name").fill("Signals browser Draft");
    await page.locator(".cm-content").click();
    await page.keyboard.type("volume_shares");

    page.once("dialog", async (dialog) => dialog.dismiss());
    await workspaceNew.click();
    await expect(page.getByLabel("Research name")).toHaveValue("Signals browser Draft");

    await page.getByRole("link", { name: "New Research", exact: true }).click();
    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByLabel("Research name")).toHaveValue("");
    expect(await page.evaluate((folderId) => localStorage.getItem(`thesistrace.research-draft.${folderId}`), customFolderId)).not.toBeNull();
    await page.getByRole("link", { name: "Signals", exact: true }).click();
    await expect(page.getByLabel("Research name")).toHaveValue("Signals browser Draft");
    await expect(page.locator(".cm-content")).toHaveText("volume_shares");
    expect(await page.evaluate(() => Object.keys(localStorage).sort())).toEqual([
      `thesistrace.research-draft.${customFolderId}`,
    ]);

    await page.getByLabel("Folder name").fill("Momentum");
    await page.getByRole("button", { name: "Rename Folder" }).click();
    await expect(page.getByRole("link", { name: "Momentum", exact: true })).toBeVisible();
    await expect(page.getByLabel("Research name")).toHaveValue("Signals browser Draft");

    const protectedDefault = await page.request.delete("/api/research-folders/folder_default");
    expect(protectedDefault.status()).toBe(409);
    page.once("dialog", async (dialog) => dialog.dismiss());
    await page.getByRole("button", { name: "Delete Folder" }).click();
    await expect(page.getByRole("link", { name: "Momentum", exact: true })).toBeVisible();
    page.once("dialog", async (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Delete Folder" }).click();
    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByRole("link", { name: "Momentum", exact: true })).toHaveCount(0);
    expect(await page.evaluate((folderId) => localStorage.getItem(`thesistrace.research-draft.${folderId}`), customFolderId)).toBeNull();

    const folderRead = await page.request.get("/api/research-folders");
    expect(folderRead.ok()).toBeTruthy();
    expect((await folderRead.json()).items).toMatchObject([
      { id: "folder_default", name: "Default", is_default: true },
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
    await page.goto("/research?new");
    const financialHelp = page.getByText("Financial fields", { exact: true });
    await expect(financialHelp).toBeVisible();
    await financialHelp.click();
    await expect(page.getByText("total_revenue_latest_fy", { exact: true })).toBeVisible();
    await expect(page.getByText("Latest full year visible on each Research Session").first()).toBeVisible();
    await fillCompleteDraft(page, {
      name: "Composite financial browser run",
      formula: "cs_rank(close_adj) + cs_rank(total_revenue_latest_fy)",
    });
    let captureRun: ((value: { id: string; status: number }) => void) | undefined;
    const runCapture = new Promise<{ id: string; status: number }>((resolve) => {
      captureRun = resolve;
    });
    await page.route("**/api/research-runs", async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      const response = await route.fetch();
      const body = await response.json() as { id: string };
      captureRun?.({ id: body.id, status: response.status() });
      await route.fulfill({ response });
    });
    await page.getByRole("button", { name: "Run", exact: true }).click();
    const acceptedRun = await runCapture;
    await page.unroute("**/api/research-runs");
    expect(acceptedRun.status).toBe(202);
    runId = acceptedRun.id;
    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
    await expect(page.locator(".research-run-facts").getByText(/Status\s+queued/)).toBeVisible();
    const barrier = startControlledResearchRun(runId);
    controlledWorker = barrier.process;
    await barrier.claimed;
    await expect(page.locator(".research-run-facts").getByText(/Status\s+running/)).toBeVisible();
    controlledWorker.stdin?.end("1");
    await controlledWorkerExit(controlledWorker);
    controlledWorker = undefined;
    await expect(page.locator(".research-run-facts").getByText(/Status\s+succeeded/)).toBeVisible({
      timeout: 90_000,
    });
    controlWorker("unpause");
    workerPaused = false;
    const startTrackingPath = `**/api/research-runs/${runId}/daily-tracks`;
    let captureTrack: ((value: { id: string; status: number }) => void) | undefined;
    const trackCapture = new Promise<{ id: string; status: number }>((resolve) => {
      captureTrack = resolve;
    });
    await page.route(startTrackingPath, async (route) => {
      const response = await route.fetch();
      const body = await response.json() as { id: string };
      captureTrack?.({ id: body.id, status: response.status() });
      await route.fulfill({ response });
    });
    await page.getByRole("button", { name: "Start Tracking" }).click();
    const acceptedTrack = await trackCapture;
    await page.unroute(startTrackingPath);
    expect(acceptedTrack.status).toBe(201);
    trackId = acceptedTrack.id;
    await expect(page).toHaveURL(/\/daily-tracks\/track_[a-f0-9]+$/);
    await expect(page.locator(".research-run-facts").first()).toContainText("Status active");

    publishFinancialTrackHead("lagged");
    await expect.poll(async () => (
      (await (await page.request.get(`/api/daily-tracks/${trackId}`)).json() as { status: string }).status
    ), { timeout: 90_000 }).toBe("blocked");
    await page.getByRole("button", { name: "Reload" }).click();
    await expect(page.locator(".research-run-facts").first()).toContainText("Status blocked");
    await expect(page.getByText("Financial Coverage ends before the next Research Session.")).toBeVisible();

    publishFinancialTrackHead("recovered");
    await page.getByRole("button", { name: "Retry blocked target" }).click();
    await expect.poll(async () => {
      const response = await page.request.get(`/api/daily-tracks/${trackId}`);
      const track = await response.json() as { status: string; strategy_session: string };
      return `${track.status}:${track.strategy_session}`;
    }, { timeout: 90_000 }).toBe("active:2026-08-11");
    await page.getByRole("button", { name: "Reload" }).click();
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
        });
        expect(stop.status()).toBe(202);
      });
      await cleanup(async () => {
        if (trackId === undefined) return;
        expect((await page.request.delete(`/api/daily-tracks/${trackId}`)).status()).toBe(204);
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
        });
        expect(cancel.status()).toBe(200);
      });
      await cleanup(async () => {
        if (runId === undefined) return;
        const deleted = await page.request.delete(`/api/research-runs/${runId}`);
        expect([204, 404]).toContain(deleted.status());
      });
      if (cleanupErrors.length > 0) throw new AggregateError(cleanupErrors, "E2E cleanup failed");
    } finally {
      await attachResponses(testInfo, responses);
    }
  }
});

test("Default and custom Folder Drafts run once, retain edits, reject safely, and publish results", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const responses: string[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/")) {
      responses.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });

  try {
    await page.goto("/research?new");
    await expect(page).toHaveURL(/\/research$/);
    await fillCompleteDraft(page, {
      name: "Duplicate Name",
      formula: "ts_mean(close_adj, 2)",
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

    await page.getByRole("button", { name: "Run", exact: true }).click();
    await expect(page.getByRole("list", { name: "Run issues" })).toContainText("RUN_UNAVAILABLE");
    await page.getByRole("button", { name: "Run", exact: true }).click();
    const heldRoute = await secondRequest;
    expect(commands).toHaveLength(2);
    expect(commands[1].request_id).toBe(commands[0].request_id);
    expect(commands[1].formula).toBe("ts_mean(close_adj, 2)");
    await expect(
      page.locator(".research-workspace-header").getByRole("button", { name: "New Research" }),
    ).toBeDisabled();

    await replaceFormula(page, "ts_mean(close_adj, 3)");
    await heldRoute.continue();
    await page.unroute("**/api/research-runs");

    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
    const defaultRunId = page.url().split("/").at(-1);
    expect(defaultRunId).toMatch(/^run_[a-f0-9]+$/);
    await expect(page.locator(".research-run-facts").getByText(/Status\s+succeeded/)).toBeVisible({ timeout: 90_000 });
    await expect(page.getByRole("heading", { name: "Strategy Summary" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh" })).toHaveCount(0);

    const retainedAfterRun = await page.evaluate(() => JSON.parse(
      localStorage.getItem("thesistrace.research-draft.folder_default") ?? "null",
    ));
    expect(retainedAfterRun).toMatchObject({
      formula: "ts_mean(close_adj, 3)",
      lastAdmittedBaseline: { formula: "ts_mean(close_adj, 2)" },
      pendingAdmission: null,
    });
    await page.reload();
    await expect(page.getByRole("heading", { name: "Strategy Summary" })).toBeVisible();

    const acceptedHistory = await page.request.get("/api/research-runs");
    expect(acceptedHistory.ok()).toBeTruthy();
    const acceptedItems = (await acceptedHistory.json()).items as Array<{ id: string }>;

    await page.goto("/research");
    await expect(page.locator(".cm-content")).toHaveText("ts_mean(close_adj, 3)");
    await replaceFormula(page, "unknown_field");
    await page.getByRole("button", { name: "Run", exact: true }).click();
    await expect(page.getByRole("list", { name: "Run issues" })).toContainText("UNKNOWN_IDENTIFIER");
    await expect(page.locator(".cm-lintRange-error")).toHaveCount(1);
    const rejectedHistory = await page.request.get("/api/research-runs");
    expect(((await rejectedHistory.json()).items as unknown[])).toHaveLength(acceptedItems.length);
    await page.reload();
    await expect(page.locator(".cm-content")).toHaveText("unknown_field");

    await page.getByLabel("New Folder").fill("Signals");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/research\?folder=folder_[a-f0-9]+$/);
    const customFolderId = new URL(page.url()).searchParams.get("folder");
    expect(customFolderId).toMatch(/^folder_[a-f0-9]+$/);
    if (customFolderId === null) throw new Error("Custom Folder route is missing folder id");
    await fillCompleteDraft(page, { name: "Duplicate Name", formula: "close_adj" });
    await page.getByRole("button", { name: "Run", exact: true }).click();
    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
    const customRunId = page.url().split("/").at(-1);
    if (customRunId === undefined) throw new Error("Custom Research route is missing run id");
    await expect(page.locator(".research-run-facts").getByText(/Status\s+succeeded/)).toBeVisible({ timeout: 90_000 });
    await expect(page.getByRole("heading", { name: "Factor Summary" })).toBeVisible();
    const customDetail = await page.request.get(`/api/research-runs/${customRunId}`);
    expect((await customDetail.json()).folder_id).toBe(customFolderId);

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
    await page.getByRole("button", { name: "Update organization" }).click();
    const heldOrganizationRoute = await heldOrganization;
    await expect(page.getByLabel("Research name", { exact: true })).toBeDisabled();
    await expect(page.getByLabel("Research Folder")).toBeDisabled();
    await heldOrganizationRoute.continue();
    await page.unroute(`**/api/research-runs/${customRunId}`);
    await expect(page.locator(".research-run-facts")).toContainText("Renamed Research");
    await page.getByLabel("Research name", { exact: true }).fill("Duplicate Name");
    await page.getByLabel("Research Folder").selectOption("folder_default");
    await page.getByRole("button", { name: "Update organization" }).click();
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
    await expect(page.getByRole("link", { name: "Duplicate Name" })).toHaveCount(2);
    await expect(page.getByText(defaultRunId ?? "missing-default-run-id", { exact: true })).toBeVisible();
    await expect(page.getByText(customRunId, { exact: true })).toBeVisible();
    await expect(page.getByText("ts_mean(close_adj, 2)", { exact: true })).toBeVisible();
    await expect(page.getByText("close_adj", { exact: true })).toBeVisible();
    await page.getByLabel("Filter by Folder").selectOption(customFolderId);
    await expect(page.getByText("No Research Runs yet.")).toBeVisible();
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
    await expect(page.locator(".cm-content")).toHaveText("close_adj");
    await page.getByLabel("Research name").fill("Target Local Name");
    await page.goto(`/research-runs/${defaultRunId}`);
    await expect(page.getByRole("button", { name: "Use as Draft" })).toBeVisible();
    const sourceBeforeReuseResponse = await page.request.get(`/api/research-runs/${defaultRunId}`);
    const sourceBeforeReuse = await sourceBeforeReuseResponse.json();
    const historyBeforeReuse = await page.request.get("/api/research-runs");
    const historyCountBeforeReuse = ((await historyBeforeReuse.json()).items as unknown[]).length;
    await page.getByLabel("Target Folder").selectOption(customFolderId);
    await page.getByRole("button", { name: "Use as Draft" }).click();
    await expect(page).toHaveURL(new RegExp(`/research\\?folder=${customFolderId}$`));
    await expect(page.getByLabel("Research name")).toHaveValue("Target Local Name");
    await expect(page.locator(".cm-content")).toHaveText("ts_mean(close_adj, 2)");
    await expect(page.getByLabel("Hypothesis")).toHaveValue("Browser Run acceptance.");
    await expect(page.getByLabel("Research start date")).toHaveValue("2026-08-04");
    await expect(page.getByLabel("Research end date")).toHaveValue("2026-08-05");
    await expect(page.getByLabel("Universe")).toHaveValue("top300");
    await expect(page.getByLabel("Neutralization")).toHaveValue("none");
    await expect(page.getByLabel("Holdings count")).toHaveValue("10");
    await expect(page.getByLabel("Rebalance sessions")).toHaveValue("2");
    const historyAfterCopy = await page.request.get("/api/research-runs");
    expect(((await historyAfterCopy.json()).items as unknown[])).toHaveLength(historyCountBeforeReuse);

    await replaceFormula(page, "ts_mean(close_adj, 2) + 1");
    await page.getByRole("button", { name: "Run", exact: true }).click();
    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
    const reusedRunId = page.url().split("/").at(-1);
    expect(reusedRunId).not.toBe(defaultRunId);
    await expect(page.locator(".research-run-facts").getByText(/Status\s+succeeded/)).toBeVisible({ timeout: 90_000 });
    const reusedDetail = await page.request.get(`/api/research-runs/${reusedRunId}`);
    expect(await reusedDetail.json()).toMatchObject({
      id: reusedRunId,
      folder_id: customFolderId,
      name: "Target Local Name",
      input: { formula: "ts_mean(close_adj, 2) + 1" },
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
    await expect(page.getByRole("link", { name: reusedRunId, exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete DailyTrack" })).toHaveCount(0);

    await page.goto(`/research-runs/${reusedRunId}`);
    page.once("dialog", async (dialog) => dialog.dismiss());
    await page.getByRole("button", { name: "Delete Research" }).click();
    await expect(page).toHaveURL(new RegExp(`/research-runs/${reusedRunId}$`));
    expect((await page.request.get(`/api/research-runs/${reusedRunId}`)).status()).toBe(200);
    page.once("dialog", async (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Delete Research" }).click();
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

async function fillCompleteDraft(
  page: Page,
  values: { name: string; formula: string },
): Promise<void> {
  await page.getByLabel("Research name").fill(values.name);
  await replaceFormula(page, values.formula);
  await page.getByLabel("Hypothesis").fill("Browser Run acceptance.");
  await page.getByLabel("Research start date").fill("2026-08-04");
  await page.getByLabel("Research end date").fill("2026-08-05");
  await page.getByLabel("Universe").selectOption("top300");
  await page.getByLabel("Neutralization").selectOption("none");
  await page.getByLabel("Holdings count").fill("10");
  await page.getByLabel("Rebalance sessions").fill("2");
  await expect(page.getByRole("button", { name: "Run", exact: true })).toBeEnabled();
}

async function replaceFormula(page: Page, formula: string): Promise<void> {
  const editor = page.locator(".cm-content");
  await editor.click();
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.type(formula);
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

function controlWorker(action: "pause" | "unpause"): void {
  execFileSync("docker", [action, testContainer("research-worker")], { stdio: "pipe" });
}

function startControlledResearchRun(runId: string) {
  const process = spawn(
    "uv",
    [
      "run", "python", "../tests/browser/process_research_run_with_barrier.py",
      runId,
    ],
    { cwd: globalThis.process.cwd(), env: globalThis.process.env, stdio: "pipe" },
  );
  const claimed = new Promise<void>((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    process.stdout?.setEncoding("utf8");
    process.stderr?.setEncoding("utf8");
    process.stderr?.on("data", (chunk: string) => { stderr += chunk; });
    process.stdout?.on("data", (chunk: string) => {
      stdout += chunk;
      if (stdout.includes(`claimed:${runId}`)) resolve();
    });
    process.once("error", reject);
    process.once("exit", (code) => {
      if (!stdout.includes(`claimed:${runId}`)) {
        reject(new Error(`Controlled ResearchRun worker exited ${code}: ${stderr}`));
      }
    });
  });
  return { claimed, process };
}

function controlledWorkerExit(process: ChildProcess, allowTermination = false): Promise<void> {
  if (process.exitCode !== null) {
    return process.exitCode === 0
      ? Promise.resolve()
      : Promise.reject(new Error(`Controlled ResearchRun worker exited with ${process.exitCode}`));
  }
  return new Promise((resolve, reject) => {
    process.once("error", reject);
    process.once("exit", (code, signal) => {
      if (code === 0 || (allowTermination && (signal === "SIGTERM" || code === 143))) resolve();
      else reject(new Error(`Controlled ResearchRun worker exited with ${code ?? signal}`));
    });
  });
}

function publishFinancialTrackHead(mode: "lagged" | "recovered"): void {
  execFileSync(
    "uv",
    ["run", "python", "../tests/browser/publish_financial_track_head.py", mode],
    { cwd: process.cwd(), env: process.env, stdio: "pipe" },
  );
}
