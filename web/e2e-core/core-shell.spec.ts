import { expect, test } from "@playwright/test";

test("publishes the first Dataset Release through the real Core", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/data");

  const navigation = page.getByRole("navigation", { name: "Product resources" });
  await expect(navigation.getByRole("link")).toHaveCount(4);
  await expect(navigation.getByRole("link", { name: "Data" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(navigation.getByRole("link", { name: "Definitions" })).toHaveAttribute(
    "href",
    "/definitions",
  );
  await expect(navigation.getByRole("link", { name: "Research Runs" })).toHaveAttribute(
    "href",
    "/research-runs",
  );
  await expect(navigation.getByRole("link", { name: "Daily Tracks" })).toHaveAttribute(
    "href",
    "/daily-tracks",
  );
  await expect(page.getByText("No Dataset Releases yet.")).toBeVisible();
  await page.getByRole("button", { name: "Update Data" }).click();
  await expect(page.getByRole("status")).toHaveText("Updating canonical data…");
  await expect(page.getByRole("heading", { name: "Latest Dataset Release" })).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByText("756 Research Sessions")).toBeVisible();
  await expect(page.getByText("First Release")).toBeVisible();
  const firstRelease = await page
    .getByRole("list", { name: "Dataset Release history" })
    .getByRole("listitem")
    .first()
    .textContent();
  await page.getByRole("button", { name: "Update Data" }).click();
  await expect(page.getByRole("status")).toHaveText("Updating canonical data…");
  await expect(page.getByText("757 Research Sessions")).toBeVisible({ timeout: 60_000 });
  const releaseHistory = page.getByRole("list", { name: "Dataset Release history" });
  await expect(releaseHistory.getByRole("listitem")).toHaveCount(2);
  await expect(releaseHistory).toContainText(firstRelease ?? "missing-root-release");
  await expect(page.getByText("Later Release")).toBeVisible();
  const latestRelease = await page
    .getByRole("heading", { name: "Latest Dataset Release" })
    .locator("..")
    .textContent();
  await page.getByRole("button", { name: "Update Data" }).click();
  await expect(page.getByRole("status")).toHaveText("Updating canonical data…");
  await expect(page.getByRole("status")).toHaveText(
    "No new completed Research Session. Latest Release unchanged.",
    { timeout: 60_000 },
  );
  await expect(releaseHistory.getByRole("listitem")).toHaveCount(2);
  await expect(
    page.getByRole("heading", { name: "Latest Dataset Release" }).locator(".."),
  ).toHaveText(latestRelease ?? "missing-latest-release");
  await expect(page.getByText("manifest_sha256")).toHaveCount(0);
  await expect(page.getByText("object_key")).toHaveCount(0);
});

test("shows one sanitized terminal ResearchRun failure", async ({ page }) => {
  await page.route("**/api/research-runs/run_deadbeef", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "run_deadbeef",
        status: "failed",
        definition_id: "def_retry",
        definition_revision: 1,
        dataset_release_id: "release_retry",
        failure_reason:
          "Research execution could not access required infrastructure.",
      }),
    }),
  );

  await page.goto("/research-runs/run_deadbeef");

  await expect(page.getByRole("alert")).toHaveText(
    "Failure Research execution could not access required infrastructure.",
  );
  await expect(page.getByText(/Attempt|retry count|exception|endpoint/i)).toHaveCount(0);
});

test("keeps Cancel authoritative after delayed ResearchRun work returns", async ({ page }) => {
  let cancelled = false;
  let workerReleased = false;
  let observeOldPoll!: () => void;
  const oldPollObserved = new Promise<void>((resolve) => {
    observeOldPoll = resolve;
  });
  await page.exposeFunction("notifyOldPollObserved", observeOldPoll);
  await page.addInitScript(() => {
    type TestWindow = typeof window & {
      delayNextResearchRunBody?: boolean;
      notifyOldPollObserved: () => void;
      releaseOldPollBody?: () => void;
    };
    const scope = window as TestWindow;
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args: Parameters<typeof fetch>) => {
      const request = new Request(...args);
      const response = await originalFetch(...args);
      if (
        request.method !== "GET" ||
        !request.url.endsWith("/api/research-runs/run_cafef00d") ||
        !scope.delayNextResearchRunBody
      ) return response;

      scope.delayNextResearchRunBody = false;
      const body = await response.text();
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          scope.releaseOldPollBody = () => {
            controller.enqueue(new TextEncoder().encode(body));
            controller.close();
          };
        },
      });
      scope.notifyOldPollObserved();
      return new Response(stream, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    };
  });
  const run = {
    id: "run_cafef00d",
    definition_id: "def_cancel",
    definition_revision: 1,
    dataset_release_id: "release_cancel",
  };
  await page.route("**/api/research-runs/run_cafef00d", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...run,
        status: cancelled
          ? "cancelled"
          : workerReleased
            ? "succeeded"
            : "running",
      }),
    });
  });
  await page.route("**/api/research-runs/run_cafef00d/cancel", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      request_id: expect.stringMatching(/^cancel_/),
    });
    cancelled = true;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...run, status: "cancelled" }),
    });
  });

  await page.goto("/research-runs/run_cafef00d");
  await expect(page.getByText(/Status\s+running/)).toBeVisible();
  await page.evaluate(() => {
    (window as typeof window & { delayNextResearchRunBody?: boolean })
      .delayNextResearchRunBody = true;
  });
  await page.getByRole("button", { name: "Refresh" }).click();
  await oldPollObserved;
  await expect(page.getByRole("status")).toHaveText("Refreshing ResearchRun…");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByText(/Status\s+cancelled/)).toBeVisible();
  await expect(page.getByText("Refreshing ResearchRun…", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Refresh" })).toBeEnabled();
  await page.evaluate(() => {
    (window as typeof window & { releaseOldPollBody?: () => void })
      .releaseOldPollBody?.();
  });
  await page.waitForTimeout(100);
  await expect(page.getByText(/Status\s+cancelled/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);

  workerReleased = true;
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByText(/Status\s+cancelled/)).toBeVisible();
  await expect(page.getByText(/Attempt|fence|receipt|manifest|object/i)).toHaveCount(0);
});

test("replays the same Cancel request after its response is lost", async ({ page }) => {
  const requestIds: string[] = [];
  let cancelAttempts = 0;
  const run = {
    id: "run_badf00d",
    status: "running",
    definition_id: "def_cancel_retry",
    definition_revision: 1,
    dataset_release_id: "release_cancel_retry",
  };
  await page.route("**/api/research-runs/run_badf00d", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(run) }),
  );
  await page.route("**/api/research-runs/run_badf00d/cancel", async (route) => {
    requestIds.push(route.request().postDataJSON().request_id as string);
    cancelAttempts += 1;
    if (cancelAttempts === 1) {
      await route.abort();
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...run, status: "cancelled" }),
    });
  });

  await page.goto("/research-runs/run_badf00d");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("ResearchRun cancellation failed");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByText(/Status\s+cancelled/)).toBeVisible();
  expect(requestIds).toHaveLength(2);
  expect(requestIds[1]).toBe(requestIds[0]);
});

test("reruns the selected immutable input at a new stable Run URL", async ({ page }) => {
  const original = {
    id: "run_1111aaaa",
    status: "succeeded",
    definition_id: "def_rerun",
    definition_revision: 1,
    dataset_release_id: "release_original",
  };
  const rerun = {
    ...original,
    id: "run_2222bbbb",
    status: "queued",
    rerun_of_id: original.id,
  };
  let originalReads = 0;
  await page.route("**/api/research-runs/run_1111aaaa", async (route) => {
    originalReads += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(original),
    });
  });
  await page.route("**/api/research-runs/run_1111aaaa/rerun", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      request_id: expect.stringMatching(/^rerun_/),
    });
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify(rerun),
    });
  });
  await page.route("**/api/research-runs/run_2222bbbb", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(rerun) }),
  );

  await page.goto("/research-runs/run_1111aaaa");
  await expect(page.getByText("Status succeeded", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Rerun", exact: true }).click();

  await expect(page).toHaveURL(/\/research-runs\/run_2222bbbb$/);
  await expect(page.getByText("Status queued", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "run_1111aaaa" })).toHaveAttribute(
    "href",
    "/research-runs/run_1111aaaa",
  );
  await expect(page.getByText(/compare|comparison/i)).toHaveCount(0);
  await expect(page.getByText(/Attempt|fence|receipt|manifest|object/i)).toHaveCount(0);
  expect(originalReads).toBeGreaterThan(0);
});

test("starts and reopens one DailyTrack from a succeeded Run", async ({ page }) => {
  const run = {
    id: "run_3333cccc",
    status: "succeeded",
    definition_id: "def_track",
    definition_revision: 1,
    dataset_release_id: "release_track_seed",
  };
  const track = {
    id: "track_4444dddd",
    status: "active",
    seed_run_id: run.id,
    seed_release_id: run.dataset_release_id,
    definition_id: run.definition_id,
    definition_revision: run.definition_revision,
    result_checksum_sha256: "a".repeat(64),
    strategy_session: "2025-12-31",
  };
  await page.route("**/api/research-runs/run_3333cccc", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(run) }),
  );
  await page.route("**/api/research-runs/run_3333cccc/daily-tracks", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      request_id: expect.stringMatching(/^track_/),
    });
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(track),
    });
  });
  await page.route("**/api/daily-tracks/track_4444dddd", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(track) }),
  );

  await page.goto("/research-runs/run_3333cccc");
  await page.getByRole("button", { name: "Start Tracking", exact: true }).click();

  await expect(page).toHaveURL(/\/daily-tracks\/track_4444dddd$/);
  await expect(page.getByText("Status active", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "run_3333cccc" })).toHaveAttribute(
    "href",
    "/research-runs/run_3333cccc",
  );
  await page.reload();
  await expect(page.getByRole("heading", { name: "DailyTrack" })).toBeVisible();
  await expect(page.getByText("Status active", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/Activation|Checkpoint|manifest|object|receipt|Attempt|worker/i),
  ).toHaveCount(0);
});

test("saves and reopens an incomplete nameless Definition", async ({ page }) => {
  await page.goto("/definitions");

  await expect(page.getByRole("heading", { name: "Definitions" })).toBeVisible();
  await expect(page.getByText("No Research Definitions yet.")).toBeVisible();
  await page.getByRole("button", { name: "New Definition" }).click();
  await expect(page.getByLabel("Definition name")).toHaveValue("");
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue("");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("status")).toHaveText("Saved revision 1.");
  const generatedName = await page.getByLabel("Definition name").inputValue();
  expect(generatedName).not.toBe("");
  await expect(page).toHaveURL(/\/definitions\/def_[a-f0-9]+$/);
  const stableUrl = page.url();

  const detailRefresh = page.waitForRequest(
    (request) => request.method() === "GET" && request.url() === stableUrl.replace("/definitions/", "/api/definitions/"),
  );
  await page.getByRole("button", { name: "Refresh" }).click();
  await detailRefresh;
  await expect(page.getByRole("status")).toHaveText("Refreshed.");

  await page.route(`**/api/definitions/${stableUrl.split("/").at(-1)}`, (route) =>
    route.abort(), { times: 1 });
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("alert")).toHaveText("Research Definition unavailable");
  await expect(page.getByRole("status")).toHaveCount(0);
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);

  await page.getByLabel("Hypothesis (optional)").fill("Temporary hypothesis");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved revision 2.");
  await page.getByLabel("Hypothesis (optional)").fill("");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved revision 3.");

  await page.reload();
  await expect(page.getByLabel("Definition name")).toHaveValue(generatedName);
  await expect(page.getByText("Revision 3")).toBeVisible();
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue("");
  await page.getByRole("link", { name: "Definitions" }).click();
  await expect(page.getByRole("link", { name: generatedName })).toBeVisible();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("link", { name: generatedName }).click();
  await expect(page).toHaveURL(stableUrl);
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue("");
  await expect(page.getByText(/Draft|Snapshot|Frozen version/i)).toHaveCount(0);
});

test("authors and reopens an Alpha using authoritative stable IDs", async ({ page }) => {
  await page.goto("/definitions");
  await page.getByRole("button", { name: "New Definition" }).click();
  await page.getByRole("button", { name: "Add Alpha" }).click();

  await page.getByLabel("Alpha operator").selectOption("ts_mean");
  await page.getByLabel("Alpha field 1").selectOption("price.close.adjusted");
  await page.getByLabel("Alpha window 2").fill("20");
  await page.getByLabel("Universe").selectOption("top1000");
  await page.getByLabel("Neutralization").selectOption("industry");
  await page.getByLabel("Holdings count").fill("30");
  await page.getByLabel("Rebalance interval").fill("5");

  const saveRequest = page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/api/definitions"),
  );
  await page.getByRole("button", { name: "Save" }).click();
  const submitted = (await saveRequest).postDataJSON();
  expect(submitted.alpha).toEqual({
    operator_id: "ts_mean",
    operands: [
      { field_id: "price.close.adjusted" },
      { literal: 20 },
    ],
  });
  expect(JSON.stringify(submitted)).not.toContain("close_adj");
  await expect(page.getByRole("status")).toHaveText("Saved revision 1.");

  await page.reload();
  await expect(page.getByLabel("Alpha operator")).toHaveValue("ts_mean");
  await expect(page.getByLabel("Alpha field 1")).toHaveValue("price.close.adjusted");
  await expect(page.getByLabel("Alpha window 2")).toHaveValue("20");
  await expect(page.getByLabel("Universe")).toHaveValue("top1000");
  await expect(page.getByLabel("Neutralization")).toHaveValue("industry");
  await expect(page.getByLabel("Holdings count")).toHaveValue("30");
  await expect(page.getByLabel("Rebalance interval")).toHaveValue("5");
});

test("keeps unsaved editor values after revision and structure errors", async ({ page }) => {
  await page.goto("/definitions");
  await page.getByRole("button", { name: "New Definition" }).click();
  await page.getByLabel("Definition name").fill("Original name");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved revision 1.");
  const definitionId = page.url().split("/").at(-1);
  expect(definitionId).toMatch(/^def_[a-f0-9]+$/);

  await page.evaluate(async (id) => {
    const response = await fetch(`/api/definitions/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: 1, name: "External edit" }),
    });
    if (!response.ok) throw new Error(`external edit failed: ${response.status}`);
  }, definitionId);

  await page.getByLabel("Definition name").fill("My unsaved name");
  await page.getByLabel("Hypothesis (optional)").fill("My unsaved hypothesis");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Definition changed elsewhere at revision 2. Your edits are unchanged.",
  );
  await expect(page.getByLabel("Definition name")).toHaveValue("My unsaved name");
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue(
    "My unsaved hypothesis",
  );
  await expect(page.getByText("Revision 1")).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Refresh" })).toHaveCount(0);
  await page.getByRole("button", {
    name: "Discard my edits and load server version",
  }).click();
  await expect(page.getByRole("status")).toHaveText("Refreshed.");
  await expect(page.getByLabel("Definition name")).toHaveValue("External edit");
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue("");
  await expect(page.getByText("Revision 2")).toBeVisible();

  await page.getByLabel("Definition name").fill("My corrected name");
  await page.getByLabel("Hypothesis (optional)").fill("My corrected hypothesis");
  await page.getByRole("button", { name: "Add Alpha" }).click();
  await page.getByLabel("Alpha operator").selectOption("ts_mean");
  await page.getByLabel("Alpha window 2").evaluate((element) => {
    element.removeAttribute("min");
  });
  await page.getByLabel("Alpha window 2").fill("0");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Definition has structural errors. Your edits are unchanged.",
  );
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Refresh" })).toHaveCount(0);
  await expect(page.getByRole("button", {
    name: "Discard my edits and load server version",
  })).toHaveCount(0);
  await expect(page.getByLabel("Definition name")).toHaveValue("My corrected name");
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue(
    "My corrected hypothesis",
  );
  await expect(page.getByLabel("Alpha window 2")).toHaveValue("0");

  await page.getByLabel("Alpha window 2").fill("20");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved revision 3.");
  await expect(page.getByLabel("Definition name")).toHaveValue("My corrected name");
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue(
    "My corrected hypothesis",
  );
});

test("saves one rejected Run action and shows actionable issues", async ({ page }) => {
  await page.goto("/definitions");
  await page.getByRole("button", { name: "New Definition" }).click();
  await page.getByLabel("Definition name").fill("Incomplete run");

  const writes: string[] = [];
  page.on("request", (request) => {
    if (
      ["POST", "PUT"].includes(request.method()) &&
      new URL(request.url()).pathname.startsWith("/api/definitions")
    ) writes.push(new URL(request.url()).pathname);
  });
  await page.getByRole("button", { name: "Run" }).click();

  await expect(page.getByRole("status")).toHaveText(
    "Run rejected after saving revision 1.",
  );
  expect(writes).toEqual(["/api/definitions/run"]);
  await expect(page).toHaveURL(/\/definitions\/def_[a-f0-9]+$/);
  await expect(page.getByRole("list", { name: "Run validation issues" })).toContainText(
    "Alpha is required",
  );
  await expect(page.getByRole("list", { name: "Run validation issues" })).not.toContainText(
    "hypothesis",
  );
  await expect(page.getByText("Revision 1", { exact: true })).toBeVisible();
});

test("replays the same Run request after its committed response is lost", async ({ page }) => {
  await page.goto("/definitions");
  await page.getByRole("button", { name: "New Definition" }).click();
  await page.getByLabel("Definition name").fill("Retry one logical run");

  const requestIds: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/definitions/run")) {
      requestIds.push(request.postDataJSON().request_id as string);
    }
  });
  await page.route("**/api/definitions/run", async (route) => {
    await route.fetch();
    await route.abort("failed");
  }, { times: 1 });

  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Definition Run response was not received. Run again to retry the same action.",
  );
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Run rejected after saving revision 1.",
  );
  expect(requestIds).toHaveLength(2);
  expect(requestIds[0]).toBe(requestIds[1]);
  await expect(page.getByText("Revision 1", { exact: true })).toBeVisible();
});

test("runs valid content and shows its bounded ResearchRun result", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/definitions");
  await page.getByRole("button", { name: "New Definition" }).click();
  await page.getByLabel("Definition name").fill("Browser admitted run");
  await page.getByRole("button", { name: "Add Alpha" }).click();
  await page.getByLabel("Alpha operator").selectOption("ts_mean");
  await page.getByLabel("Alpha field 1").selectOption("price.close.adjusted");
  await page.getByLabel("Alpha window 2").fill("20");
  await page.getByLabel("Universe").selectOption("top1000");
  await page.getByLabel("Neutralization").selectOption("industry");
  await page.getByLabel("Holdings count").fill("30");
  await page.getByLabel("Rebalance interval").fill("5");

  const writes: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (request.method() === "POST" && pathname.startsWith("/api/definitions")) {
      writes.push(pathname);
    }
  });
  await page.getByRole("button", { name: "Run" }).click();

  await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
  await expect(page.getByRole("heading", { name: "ResearchRun" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Research Runs" })).toContainText(
    "Status queued",
  );
  await expect(page.getByRole("link", { name: "Revision 1" })).toBeVisible();
  expect(writes).toEqual(["/api/definitions/run"]);
  await expect(page.getByText(/Snapshot/i)).toHaveCount(0);
  await expect(page.getByText("Status running", { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("Status succeeded", { exact: true })).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByRole("heading", { name: "Factor Evaluation" })).toBeVisible();
  for (const horizon of [1, 5, 20]) {
    const region = page.getByRole("region", { name: `${horizon}-session Factor` });
    await expect(region).toContainText("504 signal sessions");
    await expect(region).toContainText("Rank IC");
    await expect(region).toContainText("IC");
  }
  await expect(page.getByRole("heading", { name: "Strategy / Benchmark" })).toBeVisible();
  await expect(page.getByText("Selected universe top1000", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: "Strategy and benchmark NAV" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Provenance" })).toBeVisible();
  await expect(
    page.getByText(/\b(?:attempt|claim|lease|heartbeat|fence|manifest|object)\b/i),
  ).toHaveCount(0);
  await expect(page.getByText(/download|compare|comparison|continuation/i)).toHaveCount(0);

  await page.route("**/api/research-runs/*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1_500));
    await route.continue();
  }, { times: 1 });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText("Loading ResearchRun…", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Factor Evaluation" })).toBeVisible();

  await page.route("**/api/research-runs/*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300));
    await route.continue();
  }, { times: 1 });
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("status")).toHaveText("Refreshing ResearchRun…");
  await expect(page.getByRole("button", { name: "Refresh" })).toBeEnabled();

  await page.route("**/api/research-runs/*", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "secret bucket object checksum mismatch" }),
    });
  }, { times: 1 });
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("alert")).toHaveText("ResearchRun unavailable");
  await expect(page.getByText(/secret|bucket|checksum/i)).toHaveCount(0);

  await page.getByRole("link", { name: "Research Runs" }).click();
  await expect(page.getByRole("heading", { name: "Research Runs" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Research Runs" })).toContainText("succeeded");
  await expect(page.getByText(/Snapshot/i)).toHaveCount(0);
});
