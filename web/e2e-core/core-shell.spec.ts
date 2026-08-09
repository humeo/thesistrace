import { expect, test } from "@playwright/test";

const internalDailyTrackMechanics =
  /(?:^|[^A-Za-z0-9])(?:activation|checkpoint|manifest|object|receipt|progression|claim|attempt|lease|heartbeat|fence|publication|recovery|worker|cache|working_cache|working-cache|cache_root|working_cache_root|physical_path|ordinal|failure_reason|started_at|finished_at|execution_fence|target_release_id|predecessor_release_id)(?:$|[^A-Za-z0-9])/i;

test("uses the four-resource shell as the only active product", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/data$/);

  const navigation = page.getByRole("navigation", { name: "Product resources" });
  await expect(navigation.getByRole("link")).toHaveCount(4);
  for (const [name, path, heading] of [
    ["Data", "/data", "Data overview"],
    ["Definitions", "/definitions", "Definitions"],
    ["Research Runs", "/research-runs", "Research Runs"],
    ["Daily Tracks", "/daily-tracks", "Daily Tracks"],
  ] as const) {
    await navigation.getByRole("link", { name }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Product resources" }).getByRole("link"),
    ).toHaveCount(4);
  }

  await expect(
    page.getByText(
      /研究工作台|login|hosted|workspace dashboard|operations ledger|raw json|download/i,
    ),
  ).toHaveCount(0);

  const removedEntry = await page.request.get("/core.html");
  expect(removedEntry.status()).toBe(404);
});

test("shows current data as a read-only resource", async ({ page }) => {
  await page.goto("/data");

  await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
  await expect(page.getByText("Data not ready")).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh ↻" })).toBeVisible();
  await expect(page.getByRole("button", { name: /update/i })).toHaveCount(0);
  await expect(page.getByText(/Release|Generation|operator|history/i)).toHaveCount(0);
  expect((await page.request.post("/api/data/update")).status()).toBe(404);
  expect((await page.request.get("/api/data/releases")).status()).toBe(404);
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
    current_release_id: run.dataset_release_id,
    definition_id: run.definition_id,
    definition_revision: run.definition_revision,
    result_checksum_sha256: "a".repeat(64),
    strategy_session: "2025-12-31",
  };
  const factorHorizon = (horizon: 1 | 5 | 20) => ({
    horizon,
    summary: {
      ic: { mean: null, sample_deviation: null, icir: null, positive_fraction: null, valid_session_count: 0 },
      rank_ic: { mean: null, sample_deviation: null, icir: null, positive_fraction: null, valid_session_count: 0 },
      quantile_returns: { q1: null, q2: null, q3: null, q4: null, q5: null },
      top_bottom_return: null,
    },
    coverage: {
      signal_session_count: 0,
      ic_valid_session_count: 0,
      rank_ic_valid_session_count: 0,
      quantile_valid_session_count: 0,
    },
  });
  const detail = {
    id: track.id,
    status: track.status,
    origin: {
      seed_run_id: track.seed_run_id,
      seed_release_id: track.seed_release_id,
      definition_id: track.definition_id,
      definition_revision: track.definition_revision,
      result_checksum_sha256: track.result_checksum_sha256,
      strategy_session: track.strategy_session,
    },
    head_release_id: track.current_release_id,
    strategy_session: track.strategy_session,
    lag_releases: 0,
    blocked_reason: null,
    factor: {
      horizons: { "1": factorHorizon(1), "5": factorHorizon(5), "20": factorHorizon(20) },
    },
    strategy: {
      summary: {
        metrics: {
          net_cumulative_return: 0,
          benchmark_cumulative_return: 0,
          annualized_excess_return: 0,
          maximum_drawdown: { value: 0 },
          sharpe: null,
          transaction_costs: { cumulative_amount: 0 },
        },
      },
      benchmark: { universe: "top1000", methodology: "selected_universe_equal_weight" },
      observations: [],
    },
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
    route.fulfill({ contentType: "application/json", body: JSON.stringify(detail) }),
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
  await expect(page.getByText(internalDailyTrackMechanics)).toHaveCount(0);
});

test("handles Start Tracking replay and active limit", async ({ page }) => {
  const replayRun = {
    id: "run_a11ce001",
    status: "succeeded",
    definition_id: "def_a11ce001",
    definition_revision: 1,
    dataset_release_id: "release_tracking_replay",
  };
  const limitRun = {
    ...replayRun,
    id: "run_b11ce002",
    definition_id: "def_b11ce002",
  };
  const acceptedTrack = {
    id: "track_a11ce001",
    status: "active",
    seed_run_id: replayRun.id,
    seed_release_id: replayRun.dataset_release_id,
    current_release_id: replayRun.dataset_release_id,
    definition_id: replayRun.definition_id,
    definition_revision: replayRun.definition_revision,
    result_checksum_sha256: "e".repeat(64),
    strategy_session: "2025-12-31",
  };
  let acceptedRequestId: string | null = null;
  let replayRequests = 0;
  const acceptedTracksByRequestId = new Map<string, typeof acceptedTrack>();
  await page.route(`**/api/research-runs/${replayRun.id}`, (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(replayRun) }),
  );
  await page.route(`**/api/research-runs/${limitRun.id}`, (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(limitRun) }),
  );
  await page.route(`**/api/research-runs/${replayRun.id}/daily-tracks`, async (route) => {
    const body = route.request().postDataJSON() as { request_id: string };
    expect(Object.keys(body)).toEqual(["request_id"]);
    replayRequests += 1;
    if (replayRequests === 1) {
      acceptedRequestId = body.request_id;
      acceptedTracksByRequestId.set(body.request_id, acceptedTrack);
      await route.abort("failed");
      return;
    }
    expect(body.request_id).toBe(acceptedRequestId);
    const replayedTrack = acceptedTracksByRequestId.get(body.request_id);
    expect(replayedTrack).toEqual(acceptedTrack);
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(replayedTrack),
    });
  });
  await page.route(`**/api/research-runs/${limitRun.id}/daily-tracks`, (route) =>
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Active DailyTrack limit of 10 reached" }),
    }),
  );

  await page.goto(`/research-runs/${replayRun.id}`);
  await page.getByRole("button", { name: "Start Tracking", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Start Tracking failed");
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("button", { name: "Start Tracking", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Start Tracking", exact: true }).click();
  await expect(page).toHaveURL(`/daily-tracks/${acceptedTrack.id}`);
  expect(replayRequests).toBe(2);
  expect(acceptedTracksByRequestId.size).toBe(1);

  await page.goto(`/research-runs/${limitRun.id}`);
  const stableLimitUrl = page.url();
  await page.getByRole("button", { name: "Start Tracking", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "10 active or blocked DailyTracks already exist. Stop one before starting another.",
  );
  await expect(page).toHaveURL(stableLimitUrl);
  await expect(
    page.getByText(
      /(?:^|[^A-Za-z])(?:transaction|receipt|unique constraint|lock|quota profile)(?:$|[^A-Za-z])/i,
    ),
  ).toHaveCount(0);
  await expect(page.getByText(internalDailyTrackMechanics)).toHaveCount(0);
});

test("shows recent and cumulative DailyTrack analysis", async ({ page }) => {
  const observations = Array.from({ length: 504 }, (_, index) => ({
    session: new Date(Date.UTC(2024, 0, index + 1)).toISOString().slice(0, 10),
    gross_nav: String(1_000_000 + index * 1_100),
    net_nav: String(1_000_000 + index * 1_000),
    benchmark_nav: String(1_000_000 + index * 700),
    net_cash: "120000",
    transaction_cost_cny: "25",
    holdings_count: 30,
    maximum_single_name_weight: 0.04,
    upper_limit_buy_rejections: 0,
    lower_limit_sell_rejections: 0,
    suspension_rejections: 0,
  }));
  const correlation = {
    mean: 0.04,
    sample_deviation: 0.1,
    icir: 0.4,
    positive_fraction: 0.57,
    valid_session_count: 504,
  };
  const horizon = (value: 1 | 5 | 20) => ({
    horizon: value,
    summary: {
      ic: correlation,
      rank_ic: correlation,
      quantile_returns: { q1: -0.01, q2: -0.005, q3: 0, q4: 0.005, q5: 0.01 },
      top_bottom_return: 0.02,
    },
    coverage: {
      signal_session_count: 504,
      ic_valid_session_count: 504,
      rank_ic_valid_session_count: 504,
      quantile_valid_session_count: 504,
    },
  });
  const detail = {
    id: "track_a11a515",
    status: "active",
    origin: {
      seed_run_id: "run_analysis",
      seed_release_id: "release_origin",
      definition_id: "def_analysis",
      definition_revision: 7,
      result_checksum_sha256: "a".repeat(64),
      strategy_session: "2025-12-31",
    },
    head_release_id: "release_head",
    strategy_session: observations.at(-1)?.session,
    lag_releases: 2,
    blocked_reason: null,
    factor: { horizons: { "1": horizon(1), "5": horizon(5), "20": horizon(20) } },
    strategy: {
      summary: {
        metrics: {
          net_cumulative_return: 0.17,
          benchmark_cumulative_return: 0.11,
          annualized_excess_return: 0.06,
          maximum_drawdown: { value: -0.08 },
          sharpe: 1.2,
          transaction_costs: { cumulative_amount: 12345 },
        },
      },
      benchmark: {
        universe: "top1000",
        methodology: "selected_universe_equal_weight",
      },
      observations,
    },
  };
  let mode: "success" | "empty" | "error" = "success";
  let reads = 0;
  let releaseInitialRead!: () => void;
  const initialRead = new Promise<void>((resolve) => {
    releaseInitialRead = resolve;
  });
  let releaseEmptyRead!: () => void;
  const emptyRead = new Promise<void>((resolve) => {
    releaseEmptyRead = resolve;
  });
  await page.route("**/api/daily-tracks/track_a11a515", async (route) => {
    reads += 1;
    if (reads <= 2) await initialRead;
    if (mode === "empty") await emptyRead;
    if (mode === "error") {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "secret manifest object key" }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...detail,
        strategy: {
          ...detail.strategy,
          observations: mode === "empty" ? [] : observations,
        },
      }),
    });
  });

  const navigation = page.goto("/daily-tracks/track_a11a515", {
    waitUntil: "domcontentloaded",
  });
  await expect(page.getByText("Loading DailyTrack…", { exact: true })).toBeVisible();
  releaseInitialRead();
  await navigation;
  await expect(page.getByRole("heading", { name: "DailyTrack" })).toBeVisible();
  await expect(page.getByText("Status active", { exact: true })).toBeVisible();
  await expect(page.getByText("Head Release release_head", { exact: true })).toBeVisible();
  await expect(page.getByText("Lag 2 Releases behind", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tracking Origin" })).toBeVisible();
  await expect(page.getByRole("link", { name: "run_analysis" })).toHaveAttribute(
    "href",
    "/research-runs/run_analysis",
  );
  for (const value of [1, 5, 20]) {
    const region = page.getByRole("region", { name: `${value}-session Factor` });
    await expect(region).toContainText("504 signal sessions");
  }
  await expect(page.getByRole("heading", { name: "Cumulative Strategy" })).toBeVisible();
  for (const [label, value] of [
    ["Net cumulative", "17.00%"],
    ["Benchmark cumulative", "11.00%"],
    ["Annualized excess", "6.00%"],
    ["Maximum drawdown", "-8.00%"],
    ["Sharpe", "1.200"],
    ["Transaction costs", "CN¥12,345"],
  ]) {
    await expect(page.getByText(label, { exact: true }).locator("..")).toContainText(value);
  }
  await expect(page.getByText("Selected universe top1000", { exact: true })).toBeVisible();
  await expect(page.getByText("504 Research Sessions", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: "Strategy and benchmark NAV" })).toBeVisible();

  mode = "empty";
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("status")).toHaveText("Refreshing DailyTrack…");
  releaseEmptyRead();
  await expect(page.getByText("No recent Strategy observations.", { exact: true })).toBeVisible();

  mode = "error";
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("alert")).toHaveText("DailyTrack unavailable");
  await expect(page.getByText(/secret|manifest|object key/i)).toHaveCount(0);

  mode = "success";
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByText("504 Research Sessions", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Cumulative Strategy" })).toBeVisible();
  await expect(page.getByText(internalDailyTrackMechanics)).toHaveCount(0);
});

test("blocks one failed DailyTrack independently", async ({ page }) => {
  const emptyHorizon = (horizon: 1 | 5 | 20) => ({
    horizon,
    summary: {
      ic: { mean: null, sample_deviation: null, icir: null, positive_fraction: null, valid_session_count: 0 },
      rank_ic: { mean: null, sample_deviation: null, icir: null, positive_fraction: null, valid_session_count: 0 },
      quantile_returns: { q1: null, q2: null, q3: null, q4: null, q5: null },
      top_bottom_return: null,
    },
    coverage: {
      signal_session_count: 0,
      ic_valid_session_count: 0,
      rank_ic_valid_session_count: 0,
      quantile_valid_session_count: 0,
    },
  });
  const analysis = {
    factor: {
      horizons: {
        "1": emptyHorizon(1),
        "5": emptyHorizon(5),
        "20": emptyHorizon(20),
      },
    },
    strategy: {
      summary: {
        metrics: {
          net_cumulative_return: 0.08,
          benchmark_cumulative_return: 0.05,
          annualized_excess_return: 0.03,
          maximum_drawdown: { value: -0.02 },
          sharpe: 0.9,
          transaction_costs: { cumulative_amount: 300 },
        },
      },
      benchmark: {
        universe: "top1000",
        methodology: "selected_universe_equal_weight",
      },
      observations: [],
    },
  };
  const origin = {
    seed_run_id: "run_failure_isolation",
    seed_release_id: "release_seed",
    definition_id: "def_failure_isolation",
    definition_revision: 2,
    result_checksum_sha256: "b".repeat(64),
    strategy_session: "2025-12-31",
  };
  const blocked = {
    id: "track_b10c0ed",
    status: "blocked",
    origin,
    head_release_id: "release_seed",
    strategy_session: "2025-12-31",
    lag_releases: 2,
    blocked_reason: "DailyTrack could not process this Dataset Release.",
    ...analysis,
  };
  const active = {
    ...blocked,
    id: "track_ac71ae",
    status: "active",
    head_release_id: "release_latest",
    strategy_session: "2026-01-02",
    lag_releases: 0,
    blocked_reason: null,
  };
  await page.route("**/api/daily-tracks/track_b10c0ed", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(blocked) }),
  );
  await page.route("**/api/daily-tracks/track_ac71ae", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(active) }),
  );

  await page.goto("/daily-tracks/track_b10c0ed");
  await expect(page.getByText("Status blocked", { exact: true })).toBeVisible();
  await expect(page.getByText("Head Release release_seed", { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      "Blocked DailyTrack could not process this Dataset Release.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Factor Evaluation" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cumulative Strategy" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry blocked target" })).toBeVisible();
  await expect(page.getByText(internalDailyTrackMechanics)).toHaveCount(0);

  await page.goto("/daily-tracks/track_ac71ae");
  await expect(page.getByText("Status active", { exact: true })).toBeVisible();
  await expect(page.getByText("Head Release release_latest", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /retry/i })).toHaveCount(0);

});

test("retries the same blocked DailyTrack target", async ({ page }) => {
  const emptyHorizon = (horizon: 1 | 5 | 20) => ({
    horizon,
    summary: {
      ic: { mean: null, sample_deviation: null, icir: null, positive_fraction: null, valid_session_count: 0 },
      rank_ic: { mean: null, sample_deviation: null, icir: null, positive_fraction: null, valid_session_count: 0 },
      quantile_returns: { q1: null, q2: null, q3: null, q4: null, q5: null },
      top_bottom_return: null,
    },
    coverage: {
      signal_session_count: 0,
      ic_valid_session_count: 0,
      rank_ic_valid_session_count: 0,
      quantile_valid_session_count: 0,
    },
  });
  const analysis = {
    factor: {
      horizons: {
        "1": emptyHorizon(1),
        "5": emptyHorizon(5),
        "20": emptyHorizon(20),
      },
    },
    strategy: {
      summary: {
        metrics: {
          net_cumulative_return: 0,
          benchmark_cumulative_return: 0,
          annualized_excess_return: 0,
          maximum_drawdown: { value: 0 },
          sharpe: null,
          transaction_costs: { cumulative_amount: 0 },
        },
      },
      benchmark: {
        universe: "top1000",
        methodology: "selected_universe_equal_weight",
      },
      observations: [],
    },
  };
  const origin = {
    seed_run_id: "run_retry",
    seed_release_id: "release_seed",
    definition_id: "def_retry",
    definition_revision: 3,
    result_checksum_sha256: "c".repeat(64),
    strategy_session: "2025-12-31",
  };
  const detail = (
    id: string,
    status: "active" | "blocked",
    headRelease: string,
  ) => ({
    id,
    status,
    origin,
    head_release_id: headRelease,
    strategy_session: "2025-12-31",
    lag_releases: headRelease === "release_latest" ? 0 : 2,
    blocked_reason:
      status === "blocked"
        ? "DailyTrack could not process this Dataset Release."
        : null,
    ...analysis,
  });
  const summary = (id: string) => ({
    id,
    status: "active",
    seed_run_id: origin.seed_run_id,
    seed_release_id: origin.seed_release_id,
    current_release_id: "release_seed",
    definition_id: origin.definition_id,
    definition_revision: origin.definition_revision,
    result_checksum_sha256: origin.result_checksum_sha256,
    strategy_session: origin.strategy_session,
  });
  let successfulPhase: "blocked" | "accepted" | "first-target" | "latest" = "blocked";
  let repeatedPhase: "blocked" | "accepted" | "blocked-again" = "blocked";
  const successfulId = "track_34acce55";
  const repeatedId = "track_34fa11ed";

  await page.route(`**/api/daily-tracks/${successfulId}`, (route) => {
    const projected =
      successfulPhase === "blocked"
        ? detail(successfulId, "blocked", "release_seed")
        : successfulPhase === "first-target"
          ? detail(successfulId, "active", "release_failed_target")
          : successfulPhase === "latest"
            ? detail(successfulId, "active", "release_latest")
            : detail(successfulId, "active", "release_seed");
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(projected) });
  });
  await page.route(`**/api/daily-tracks/${repeatedId}`, (route) => {
    const projected =
      repeatedPhase === "accepted"
        ? detail(repeatedId, "active", "release_seed")
        : detail(repeatedId, "blocked", "release_seed");
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(projected) });
  });
  await page.route(`**/api/daily-tracks/${successfulId}/retry`, async (route) => {
    expect(Object.keys(route.request().postDataJSON())).toEqual(["request_id"]);
    expect(route.request().postDataJSON().request_id).toMatch(/^retry_/);
    successfulPhase = "accepted";
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify(summary(successfulId)),
    });
  });
  await page.route(`**/api/daily-tracks/${repeatedId}/retry`, async (route) => {
    expect(Object.keys(route.request().postDataJSON())).toEqual(["request_id"]);
    repeatedPhase = "accepted";
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify(summary(repeatedId)),
    });
  });

  await page.goto(`/daily-tracks/${successfulId}`);
  await expect(page.getByText("Status blocked", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Retry blocked target" }).click();
  await expect(page.getByRole("status")).toHaveText("Retry accepted for the blocked target.");
  await expect(page.getByText("Status active", { exact: true })).toBeVisible();
  await expect(page.getByText("Head Release release_seed", { exact: true })).toBeVisible();
  successfulPhase = "first-target";
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(
    page.getByText("Head Release release_failed_target", { exact: true }),
  ).toBeVisible();
  successfulPhase = "latest";
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByText("Head Release release_latest", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry blocked target" })).toHaveCount(0);

  await page.goto(`/daily-tracks/${repeatedId}`);
  await page.getByRole("button", { name: "Retry blocked target" }).click();
  await expect(page.getByText("Status active", { exact: true })).toBeVisible();
  repeatedPhase = "blocked-again";
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByText("Status blocked", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Blocked DailyTrack could not process this Dataset Release.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry blocked target" })).toBeVisible();
  await expect(page.getByText(/private|exception|target_release_id/i)).toHaveCount(0);
  await expect(page.getByText(internalDailyTrackMechanics)).toHaveCount(0);
});

test("stops a DailyTrack irreversibly", async ({ page }) => {
  const id = "track_570aaed";
  let stopped = false;
  const horizon = (value: 1 | 5 | 20) => ({
    horizon: value,
    summary: {
      ic: { mean: null, sample_deviation: null, icir: null, positive_fraction: null, valid_session_count: 0 },
      rank_ic: { mean: null, sample_deviation: null, icir: null, positive_fraction: null, valid_session_count: 0 },
      quantile_returns: { q1: null, q2: null, q3: null, q4: null, q5: null },
      top_bottom_return: null,
    },
    coverage: {
      signal_session_count: 0,
      ic_valid_session_count: 0,
      rank_ic_valid_session_count: 0,
      quantile_valid_session_count: 0,
    },
  });
  const response = () => ({
    id,
    status: stopped ? "stopped" : "active",
    origin: {
      seed_run_id: "run_stop",
      seed_release_id: "release_seed",
      definition_id: "def_stop",
      definition_revision: 1,
      result_checksum_sha256: "d".repeat(64),
      strategy_session: "2025-12-31",
    },
    head_release_id: "release_committed_head",
    strategy_session: "2026-01-01",
    lag_releases: stopped ? 1 : 0,
    blocked_reason: null,
    factor: { horizons: { "1": horizon(1), "5": horizon(5), "20": horizon(20) } },
    strategy: {
      summary: {
        metrics: {
          net_cumulative_return: 0,
          benchmark_cumulative_return: 0,
          annualized_excess_return: 0,
          maximum_drawdown: { value: 0 },
          sharpe: null,
          transaction_costs: { cumulative_amount: 0 },
        },
      },
      benchmark: { universe: "top1000", methodology: "selected_universe_equal_weight" },
      observations: [],
    },
  });
  await page.route(`**/api/daily-tracks/${id}`, (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(response()) }),
  );
  await page.route(`**/api/daily-tracks/${id}/stop`, async (route) => {
    expect(Object.keys(route.request().postDataJSON())).toEqual(["request_id"]);
    expect(route.request().postDataJSON().request_id).toMatch(/^stop_/);
    stopped = true;
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        id,
        status: "stopped",
        seed_run_id: "run_stop",
        seed_release_id: "release_seed",
        current_release_id: "release_committed_head",
        definition_id: "def_stop",
        definition_revision: 1,
        result_checksum_sha256: "d".repeat(64),
        strategy_session: "2026-01-01",
      }),
    });
  });

  await page.goto(`/daily-tracks/${id}`);
  const stableUrl = page.url();
  await expect(
    page.getByText("Stopping this DailyTrack is irreversible.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Stop DailyTrack" }).click();
  await expect(page.getByRole("status")).toHaveText("DailyTrack stopped permanently.");
  await expect(page).toHaveURL(stableUrl);
  await expect(page.getByText("Status stopped", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Head Release release_committed_head", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Stop DailyTrack" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry blocked target" })).toHaveCount(0);
  await page.goto(stableUrl);
  await expect(page.getByText("Status stopped", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Head Release release_committed_head", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByText("Status stopped", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Head Release release_committed_head", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(internalDailyTrackMechanics)).toHaveCount(0);
});

test("saves and reopens an incomplete nameless Definition", async ({ page }) => {
  await page.goto("/definitions");

  await expect(page.getByRole("heading", { name: "Definitions" })).toBeVisible();
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
  // The worker may claim the admitted run before the browser finishes navigation.
  await expect(page.getByRole("region", { name: "Research Runs" })).toContainText(
    /Status (?:queued|running)/,
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
  const firstRunId = page.url().split("/").at(-1);
  const definitionHref = await page
    .getByRole("link", { name: "Revision 1" })
    .getAttribute("href");
  expect(firstRunId).toMatch(/^run_[a-f0-9]+$/);
  expect(definitionHref).toMatch(/^\/definitions\/def_[a-f0-9]+$/);
  await expect(
    page.getByText(/\b(?:attempt|claim|lease|heartbeat|fence|manifest|object)\b/i),
  ).toHaveCount(0);
  await expect(page.getByText(/download|compare|comparison|continuation/i)).toHaveCount(0);

  await page.goto(definitionHref!);
  await expect(page.getByText("Revision 1", { exact: true })).toBeVisible();
  await page.getByLabel("Hypothesis (optional)").fill(
    "Edited current content creates an independent ResearchRun.",
  );
  const editedWrites: { method: string; pathname: string; body: object }[] = [];
  const captureEditedWrites = (request: import("@playwright/test").Request) => {
    const pathname = new URL(request.url()).pathname;
    if (
      ["POST", "PUT"].includes(request.method()) &&
      pathname.startsWith("/api/definitions")
    ) {
      editedWrites.push({
        method: request.method(),
        pathname,
        body: request.postDataJSON() as object,
      });
    }
  };
  page.on("request", captureEditedWrites);
  const editedRunRequest = page.waitForRequest((request) => {
    const pathname = new URL(request.url()).pathname;
    return (
      request.method() === "POST" &&
      /^\/api\/definitions\/def_[a-f0-9]+\/run$/.test(pathname)
    );
  });
  await page.getByRole("button", { name: "Run" }).click();
  const editedRequest = await editedRunRequest;
  await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/);
  page.off("request", captureEditedWrites);
  expect(editedWrites).toHaveLength(1);
  expect(editedWrites[0]).toMatchObject({
    method: "POST",
    pathname: new URL(editedRequest.url()).pathname,
  });
  expect(editedWrites[0].body).toMatchObject({
    expected_revision: 1,
    hypothesis: "Edited current content creates an independent ResearchRun.",
  });
  const editedRunId = page.url().split("/").at(-1);
  expect(editedRunId).not.toBe(firstRunId);
  await expect(page.getByRole("link", { name: "Revision 2" })).toBeVisible();
  await expect(page.getByText("Status succeeded", { exact: true })).toBeVisible({
    timeout: 90_000,
  });

  await page.goto(`/research-runs/${firstRunId}`);
  await expect(page.getByRole("heading", { name: "Factor Evaluation" })).toBeVisible();

  let releaseReload!: () => void;
  const reloadGate = new Promise<void>((resolve) => {
    releaseReload = resolve;
  });
  const holdReload = async (route: import("@playwright/test").Route) => {
    await reloadGate;
    try {
      await route.continue();
    } catch (error) {
      // React StrictMode can abort its first effect request during remount.
      if (!(error instanceof Error) || !error.message.includes("Route is already handled")) {
        throw error;
      }
    }
  };
  await page.route("**/api/research-runs/*", holdReload);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText("Loading ResearchRun…", { exact: true })).toBeVisible();
  releaseReload();
  await expect(page.getByRole("heading", { name: "Factor Evaluation" })).toBeVisible();
  await page.unroute("**/api/research-runs/*", holdReload);

  let releaseRefresh!: () => void;
  const refreshGate = new Promise<void>((resolve) => {
    releaseRefresh = resolve;
  });
  const holdRefresh = async (route: import("@playwright/test").Route) => {
    await refreshGate;
    await route.continue();
  };
  await page.route("**/api/research-runs/*", holdRefresh);
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("status")).toHaveText("Refreshing ResearchRun…");
  releaseRefresh();
  await expect(page.getByRole("button", { name: "Refresh" })).toBeEnabled();
  await page.unroute("**/api/research-runs/*", holdRefresh);

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
